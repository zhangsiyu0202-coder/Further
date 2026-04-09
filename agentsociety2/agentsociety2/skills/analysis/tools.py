"""Local tool implementations for analysis module

Simplified versions of tools previously in backend/tools.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import platform
import re
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel

from agentsociety2.logger import get_logger

logger = get_logger()


class ToolResult(BaseModel):
    """Tool execution result"""

    success: bool
    content: str
    error: str | None = None
    data: Any = None


class GlobTool:
    """Find files matching glob patterns"""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path).resolve()

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        """Execute glob search"""
        try:
            pattern = arguments.get("pattern", "")
            path_arg = arguments.get("path", ".")

            search_dir = self.workspace_path / path_arg
            if not search_dir.exists():
                return ToolResult(
                    success=False,
                    content=f"Path not found: {search_dir}",
                    error="path_not_found",
                )

            matches = []
            for item in sorted(search_dir.rglob(pattern)):
                if item.is_file():
                    try:
                        rel_path = item.relative_to(self.workspace_path)
                        matches.append(str(rel_path))
                    except ValueError:
                        continue

            return ToolResult(
                success=True,
                content=f"Found {len(matches)} files matching '{pattern}'",
                data={"matches": matches, "count": len(matches)},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"Glob failed: {e}",
                error=str(e),
            )


class ListDirectoryTool:
    """List directory contents"""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path).resolve()

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        """Execute directory listing"""
        try:
            rel_path = arguments.get("path", ".").strip()
            ignore_patterns = arguments.get("ignore", [])

            target_dir = (self.workspace_path / rel_path).resolve()

            # Security check
            try:
                target_dir.relative_to(self.workspace_path)
            except ValueError:
                return ToolResult(
                    success=False,
                    content="Path is outside workspace",
                    error="path_outside_workspace",
                )

            if not target_dir.exists() or not target_dir.is_dir():
                return ToolResult(
                    success=False,
                    content=f"Not a directory: {rel_path}",
                    error="not_a_directory",
                )

            entries = []
            for entry in target_dir.iterdir():
                should_ignore = False
                for pattern in ignore_patterns:
                    if fnmatch.fnmatch(entry.name, pattern):
                        should_ignore = True
                        break

                if should_ignore:
                    continue

                entries.append(
                    {
                        "name": entry.name,
                        "type": "directory" if entry.is_dir() else "file",
                    }
                )

            # Sort: directories first, then alphabetically
            entries.sort(key=lambda x: (x["type"] != "directory", x["name"]))

            return ToolResult(
                success=True,
                content=f"Listed {len(entries)} entries in {rel_path}",
                data={"entries": entries, "path": rel_path},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"List directory failed: {e}",
                error=str(e),
            )


class ReadFileTool:
    """Read file contents"""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path).resolve()

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        """Execute file read"""
        try:
            file_path = arguments.get("path", "").strip()
            limit = arguments.get("limit")

            target_file = (self.workspace_path / file_path).resolve()

            # Security check
            try:
                target_file.relative_to(self.workspace_path)
            except ValueError:
                return ToolResult(
                    success=False,
                    content="Path is outside workspace",
                    error="path_outside_workspace",
                )

            if not target_file.exists() or not target_file.is_file():
                return ToolResult(
                    success=False,
                    content=f"File not found: {file_path}",
                    error="file_not_found",
                )

            content = target_file.read_text(encoding="utf-8")
            if limit and len(content) > limit:
                content = content[:limit] + "\n... (truncated)"

            return ToolResult(
                success=True,
                content=f"Read {len(content)} characters from {file_path}",
                data={"path": file_path, "content": content},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"Read file failed: {e}",
                error=str(e),
            )


class WriteFileTool:
    """Write file contents"""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path).resolve()

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        """Execute file write"""
        try:
            file_path = arguments.get("path", "").strip()
            content = arguments.get("content", "")
            create_directories = arguments.get("create_directories", False)

            target_file = (self.workspace_path / file_path).resolve()

            # Security check
            try:
                target_file.relative_to(self.workspace_path)
            except ValueError:
                return ToolResult(
                    success=False,
                    content="Path is outside workspace",
                    error="path_outside_workspace",
                )

            if create_directories:
                target_file.parent.mkdir(parents=True, exist_ok=True)

            target_file.write_text(content, encoding="utf-8")

            return ToolResult(
                success=True,
                content=f"Wrote {len(content)} characters to {file_path}",
                data={"path": file_path},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"Write file failed: {e}",
                error=str(e),
            )


class SearchFileContentTool:
    """Search for content in files"""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path).resolve()

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        """Execute content search"""
        try:
            pattern = arguments.get("pattern", "")
            path_arg = arguments.get("path", ".")
            case_sensitive = arguments.get("case_sensitive", False)

            search_dir = (self.workspace_path / path_arg).resolve()
            results = []

            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)

            for item in search_dir.rglob("*"):
                if not item.is_file():
                    continue
                try:
                    content = item.read_text(encoding="utf-8", errors="ignore")
                    matches = []
                    for line_num, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            matches.append({"line": line_num, "text": line})
                    if matches:
                        rel_path = item.relative_to(self.workspace_path)
                        results.append(
                            {
                                "path": str(rel_path),
                                "matches": matches[:10],  # Limit matches
                            }
                        )
                except Exception:
                    continue

            return ToolResult(
                success=True,
                content=f"Found pattern in {len(results)} files",
                data={"results": results, "count": len(results)},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"Search failed: {e}",
                error=str(e),
            )


class ReplaceTool:
    """Replace text in files"""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path).resolve()

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        """Execute text replacement"""
        try:
            file_path = arguments.get("path", "").strip()
            old_text = arguments.get("old_text", "")
            new_text = arguments.get("new_text", "")

            target_file = (self.workspace_path / file_path).resolve()

            # Security check
            try:
                target_file.relative_to(self.workspace_path)
            except ValueError:
                return ToolResult(
                    success=False,
                    content="Path is outside workspace",
                    error="path_outside_workspace",
                )

            if not target_file.exists():
                return ToolResult(
                    success=False,
                    content=f"File not found: {file_path}",
                    error="file_not_found",
                )

            content = target_file.read_text(encoding="utf-8")
            count = content.count(old_text)
            new_content = content.replace(old_text, new_text)

            target_file.write_text(new_content, encoding="utf-8")

            return ToolResult(
                success=True,
                content=f"Replaced {count} occurrence(s) in {file_path}",
                data={"path": file_path, "count": count},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"Replace failed: {e}",
                error=str(e),
            )


class RunShellCommandTool:
    """Execute shell commands"""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path).resolve()

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        """Execute shell command"""
        try:
            command = arguments.get("command", "").strip()
            directory = arguments.get("directory")

            if not command:
                return ToolResult(
                    success=False,
                    content="Command is required",
                    error="missing_command",
                )

            exec_dir = self.workspace_path
            if directory:
                exec_dir = (self.workspace_path / directory).resolve()

            if not exec_dir.exists():
                return ToolResult(
                    success=False,
                    content=f"Directory not found: {exec_dir}",
                    error="directory_not_found",
                )

            # Get shell command
            if platform.system() == "Windows":
                shell_executable = os.environ.get("ComSpec", "powershell.exe")
                if shell_executable.endswith("powershell.exe"):
                    shell_args = ["-NoProfile", "-Command"]
                else:
                    shell_args = ["/c"]
            else:
                shell_executable = "/bin/bash"
                shell_args = ["-c"]

            full_command = shell_args + [command]

            process = await asyncio.create_subprocess_exec(
                shell_executable,
                *full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(exec_dir),
            )

            stdout_data, stderr_data = await process.communicate()

            stdout = (
                stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
            )
            stderr = (
                stderr_data.decode("utf-8", errors="replace") if stderr_data else ""
            )
            exit_code = process.returncode

            content_parts = [f"Command: {command}", f"Exit Code: {exit_code}"]
            if stdout:
                content_parts.append(f"\nStdout:\n{stdout}")
            if stderr:
                content_parts.append(f"\nStderr:\n{stderr}")

            return ToolResult(
                success=exit_code == 0,
                content="\n".join(content_parts),
                data={
                    "command": command,
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": exit_code,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"Shell command failed: {e}",
                error=str(e),
            )


class WriteTodoTool:
    """Manage todo lists"""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path).resolve()

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        """Execute todo update"""
        try:
            todos_data = arguments.get("todos", [])
            if not isinstance(todos_data, list):
                return ToolResult(
                    success=False,
                    content="Invalid argument: 'todos' must be an array",
                    error="InvalidArgument",
                )

            in_progress_count = sum(
                1 for t in todos_data if t.get("status") == "in_progress"
            )

            if in_progress_count > 1:
                return ToolResult(
                    success=False,
                    content="Only one task can be marked as 'in_progress' at a time",
                    error="MultipleInProgress",
                )

            if not todos_data:
                content_text = "Todo list cleared."
            else:
                status_icons = {
                    "pending": "⏳",
                    "in_progress": "🔄",
                    "completed": "✅",
                    "cancelled": "❌",
                }
                content_text = f"Todo list updated with {len(todos_data)} items.\n\n"
                for todo in todos_data:
                    icon = status_icons.get(todo.get("status", "pending"), "•")
                    content_text += (
                        f"{icon} {todo.get('description', '')} ({todo.get('status')})\n"
                    )

            return ToolResult(
                success=True,
                content=content_text,
                data={"todos": todos_data, "count": len(todos_data)},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"Todo update failed: {e}",
                error=str(e),
            )


class LoadLiteratureTool:
    """Load literature entries"""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path).resolve()

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        """Load literature"""
        try:
            path = arguments.get("path", "papers/literature_index.json")
            target_file = (self.workspace_path / path).resolve()

            if not target_file.exists():
                return ToolResult(
                    success=False,
                    content=f"Literature file not found: {path}",
                    error="file_not_found",
                )

            import json

            data = json.loads(target_file.read_text(encoding="utf-8"))
            entries = data.get("entries", [])

            return ToolResult(
                success=True,
                content=f"Loaded {len(entries)} literature entries",
                data={"entries": entries, "count": len(entries)},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"Load literature failed: {e}",
                error=str(e),
            )


class LiteratureSearchTool:
    """Literature search tool"""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path).resolve()

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        """Execute literature search"""
        try:
            from agentsociety2.skills.literature.search import search_literature

            query = arguments.get("query", "")
            limit = arguments.get("limit", 10)

            result = await search_literature(
                workspace_path=self.workspace_path,
                query=query,
                limit=limit,
            )

            if result.get("success"):
                return ToolResult(
                    success=True,
                    content=result.get("content", ""),
                    data=result,
                )
            else:
                return ToolResult(
                    success=False,
                    content=result.get("content", ""),
                    error=result.get("error"),
                )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"Literature search failed: {e}",
                error=str(e),
            )
