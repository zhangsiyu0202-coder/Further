"""
分析子智能体内部执行器：为 DataExplorer 提供内置工具与代码执行能力。
"""

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from litellm import AllMessageValues
from pydantic import BaseModel

from .tools import (
    GlobTool,
    ListDirectoryTool,
    ReadFileTool,
    ReplaceTool,
    SearchFileContentTool,
    WriteFileTool,
    LoadLiteratureTool,
    LiteratureSearchTool,
    RunShellCommandTool,
    WriteTodoTool,
)
from agentsociety2.code_executor.code_generator import CodeGenerator
from agentsociety2.code_executor.dependency_detector import DependencyDetector
from agentsociety2.code_executor.local_executor import LocalCodeExecutor
from agentsociety2.config import get_llm_router_and_model
from agentsociety2.logger import get_logger

from .models import AnalysisConfig
from .prompts import judgment_prompt
from .utils import (
    XmlParseError,
    extract_database_schema,
    format_database_schema_markdown,
    collect_experiment_files,
    parse_llm_xml_to_model,
)


class ExecutionResult(BaseModel):
    """代码执行结果判断"""

    success: bool
    reason: str
    should_retry: bool = False
    retry_instruction: str = ""


class AnalysisRunner:
    """为分析子智能体执行内置工具（文件、搜索、文献等）与生成的 Python 代码。"""

    def __init__(
        self,
        workspace_path: Path,
        output_dir: Path,
        tool_registry: Optional[Any] = None,
        config: Optional[AnalysisConfig] = None,
    ):
        self.workspace_path = workspace_path
        self.output_dir = output_dir
        self.logger = get_logger()
        self._config = config

        self._tool_registry = tool_registry
        self._builtin_tools = {}
        profile = config.llm_profile_coder if config else "coder"
        self._router, self._model_name = get_llm_router_and_model(profile)
        self._initialize_builtin_tools()

    def _initialize_builtin_tools(self):
        """初始化数据分析需要的内置工具。"""
        # Mapping of tool classes to their metadata
        tool_classes = {
            "list_directory": (ListDirectoryTool, "List directory contents"),
            "read_file": (ReadFileTool, "Read file contents"),
            "write_file": (WriteFileTool, "Write content to files"),
            "glob": (GlobTool, "Find files matching glob patterns"),
            "search_file_content": (
                SearchFileContentTool,
                "Search for content in files",
            ),
            "replace": (ReplaceTool, "Replace text in files"),
            "run_shell_command": (RunShellCommandTool, "Execute shell commands"),
            "write_todos": (WriteTodoTool, "Manage todo lists"),
            "literature_search": (LiteratureSearchTool, "Search literature"),
            "load_literature": (LoadLiteratureTool, "Load literature entries"),
        }

        for tool_name, (tool_class, description) in tool_classes.items():
            self._builtin_tools[tool_name] = {
                "class": tool_class,
                "description": description,
                "type": "builtin",
            }

        self.logger.info(
            "Initialized %s built-in tools for data analysis",
            len(self._builtin_tools),
        )

    def discover_tools(self) -> Dict[str, Dict[str, Any]]:
        """返回所有可用的内置工具。"""
        return {
            name: {
                "description": info.get("description", ""),
                "type": "builtin",
                "usage": f"Use tool name '{name}' in your analysis plan",
            }
            for name, info in self._builtin_tools.items()
        }

    def discover_tools_with_schemas(self) -> Dict[str, Dict[str, Any]]:
        """返回内置工具及其参数 schema，供 DataExplorer 调用时使用正确参数名。"""
        result = {}
        for name, info in self._builtin_tools.items():
            entry = {
                "description": info.get("description", ""),
                "type": "builtin",
                "usage": f"Use tool name '{name}' in your analysis plan",
                "parameters": [],
                "parameters_description": "varies by tool",
            }
            result[name] = entry
        return result

    async def execute_tool(
        self,
        tool_name: str,
        tool_type: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行一个工具，并传递给定的参数。

        Args:
            tool_name: 工具名称
            tool_type: 工具类型 ("builtin", "code_executor")
            parameters: 传递给工具的参数

        Returns:
            执行结果字典
        """
        if tool_type == "builtin":
            return await self._execute_builtin_tool(tool_name, parameters)
        elif tool_type == "code_executor":
            return await self._execute_code(parameters)
        else:
            return {
                "success": False,
                "error": f"Unknown tool type: {tool_type}",
            }

    async def _execute_builtin_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行一个内置工具。"""
        if tool_name not in self._builtin_tools:
            return {
                "success": False,
                "error": f"Built-in tool '{tool_name}' not found",
            }

        tool_info = self._builtin_tools[tool_name]
        tool_class = tool_info["class"]

        # Instantiate tool with workspace path
        tool = tool_class(workspace_path=self.workspace_path)

        # Execute tool
        result = await tool.execute(parameters)

        # Return result in expected format
        return {
            "success": result.success,
            "content": result.content,
            "error": result.error,
            "data": result.data,
        }

    def _discover_database_schema(self, db_path: str) -> Optional[str]:
        """
        发现数据库模式并返回格式化的模式信息。

        Args:
            db_path: SQLite 数据库文件路径

        Returns:
            格式化的 markdown 字符串，包含模式信息，如果发现失败则返回 None
        """
        db_path_obj = Path(db_path)
        schema = extract_database_schema(db_path_obj)
        if not schema:
            return None

        return format_database_schema_markdown(
            schema, include_row_counts=True, db_path=db_path_obj
        )

    async def _execute_code(
        self,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行Python代码。

        Args:
            parameters: 参数字典，包含:
                - code_description: 代码描述
                - db_path: 数据库文件路径
                - extra_files: 额外的文件路径列表
                - timeout: 执行超时时间，秒 (可选，默认600)

        Returns:
            执行结果字典
        """
        code_generator = CodeGenerator()
        dependency_detector = DependencyDetector()

        code_description = (
            parameters.get("code_description") or parameters.get("description") or ""
        )
        if not code_description:
            return {
                "success": False,
                "error": "No code description provided",
            }

        db_path = parameters.get("db_path")
        extra_files = parameters.get("extra_files", [])
        default_timeout = self._config.code_execution_timeout if self._config else 600
        timeout = parameters.get("timeout", default_timeout)

        work_dir = Path(tempfile.mkdtemp(prefix="analysis_", dir=self.output_dir))
        local_executor = LocalCodeExecutor(work_dir=work_dir)

        files_before_execution = {p for p in work_dir.rglob("*") if p.is_file()}

        schema_info = ""
        if db_path:
            discovered_schema = self._discover_database_schema(db_path)
            if discovered_schema:
                schema_info = f"""
## Database Schema

{discovered_schema}

**IMPORTANT**: 
- The schema above is the ONLY source of truth. Use ONLY tables and columns listed there.
- Do NOT assume any other table exists. If a table is not in the schema, it does not exist.
- Your code MUST read and verify the database structure before processing. Do NOT hardcode table or column names.
"""
                self.logger.info(
                    "Database schema discovered and will be included in code generation prompt"
                )

        db_filename = None
        if db_path:
            src_db = Path(db_path)
            if src_db.exists() and src_db.is_file():
                db_filename = src_db.name
                shutil.copy2(src_db, work_dir / db_filename)

        for f_path in extra_files:
            src = Path(f_path)
            if not src.exists() or not src.is_file():
                continue
            if db_path and str(Path(db_path)) == str(src):
                continue
            shutil.copy2(src, work_dir / src.name)

        # Build file path info for prompt (always include if db_path exists)
        file_path_info = ""
        if db_path:
            db_filename = db_filename or Path(db_path).name

            other_files_list = [
                f"- {Path(f_path).name}"
                for f_path in extra_files
                if Path(f_path).name != db_filename
            ]
            other_files_str = (
                "\n".join(other_files_list) if other_files_list else "None"
            )

            file_path_info = f"""
## Available Files

- Database: `{db_filename}` (in current working directory)
- Output directory: `{self.output_dir}` (save all output files here)
- Other files: {other_files_str if other_files_str != "None" else "None"}

"""

        full_description = f"""{code_description}
{schema_info}
{file_path_info}
## Important Guidelines

- **No Command-Line Arguments**: Do NOT use argparse, sys.argv, or any command-line argument parsing. All file paths are provided in the context above and files are already in the current working directory.
- **Imports**: If you use sys, add `import sys` at the top. Use standard imports: sqlite3, pandas, etc., as needed.
- **File Reading**: ALWAYS read and examine file contents FIRST before processing. For databases, query the schema programmatically. For other files, read and inspect their structure and content first. Do NOT hardcode assumptions about file structure.
- **Database Schema**: Use ONLY tables from the schema above. ALWAYS verify the database structure before processing. Do NOT hardcode table or column names.
- **Error Handling**: Use try-except blocks for file/database operations. If the core task cannot be completed, exit with `sys.exit(1)` (and ensure `import sys` is present).
- **Type Safety**: SQLite often stores mixed types. Use `pd.to_numeric(..., errors='coerce')` for numeric conversion.
- **JSON Serialization**: When using json.dumps or writing JSON, convert numpy/pandas types (int64, float64) to native Python: use `int(x)` or `float(x)` for scalars, or `df.astype(object)` before to_dict.
- **Output Files**: Save charts with plt.savefig('chart.png') in current directory, or to output directory. PNG/CSV/JSON files will be collected automatically."""

        max_retries = self._config.max_code_gen_retries if self._config else 5

        conversation_messages: List[AllMessageValues] = []
        generated_code = None
        exec_result = None

        initial_prompt = code_generator._build_prompt(full_description)
        conversation_messages.append({"role": "user", "content": initial_prompt})

        try:
            for current_try in range(max_retries):
                response = await code_generator._router.acompletion(
                    model=code_generator._model_name,
                    messages=conversation_messages,
                )

                generated_text = response.choices[0].message.content  # type: ignore
                if not generated_text:
                    if current_try < max_retries - 1:
                        conversation_messages.append(
                            {
                                "role": "user",
                                "content": "Code generator returned empty content. Please generate valid Python code.",
                            }
                        )
                    continue

                generated_code = code_generator._extract_code(generated_text)
                if not generated_code or not generated_code.strip():
                    if current_try < max_retries - 1:
                        conversation_messages.append(
                            {
                                "role": "user",
                                "content": "Code generator returned empty code. Please generate valid Python code.",
                            }
                        )
                    continue

                conversation_messages.append(
                    {"role": "assistant", "content": generated_code}
                )

                detected_dependencies = dependency_detector.detect(generated_code)
                exec_result = await local_executor.execute(
                    generated_code,
                    dependencies=detected_dependencies,
                    timeout=timeout,
                )

                judgment = await self._judge_execution_result(
                    generated_code, exec_result, work_dir, files_before_execution
                )

                if judgment.success:
                    break

                if judgment.should_retry and current_try < max_retries - 1:
                    self.logger.info(
                        f"Execution failed, will retry. Reason: {judgment.reason}"
                    )
                    execution_output = f"""## Code Execution Result (Attempt {current_try + 1})

**Return Code**: {exec_result.return_code if exec_result else "N/A"}

**STDOUT**:
```
{exec_result.stdout if exec_result else "No output"}
```

**STDERR**:
```
{exec_result.stderr if exec_result else "No error"}
```

**Generated Code**:
```python
{generated_code}
```

**Analysis**: {judgment.reason}

**What to fix**: {judgment.retry_instruction}

Please generate corrected code that addresses the issues above."""
                    conversation_messages.append(
                        {"role": "user", "content": execution_output}
                    )
                else:
                    break

            if not exec_result:
                self.logger.warning("No execution result after all attempts")
                return {
                    "success": False,
                    "error": "No execution result after all attempts",
                    "code_generated": generated_code or "",
                }

            final_judgment = await self._judge_execution_result(
                generated_code, exec_result, work_dir, files_before_execution
            )

            if not final_judgment.success:
                self.logger.warning(
                    f"All {max_retries} attempts failed. Reason: {final_judgment.reason}"
                )
                return {
                    "success": False,
                    "error": f"Failed after {max_retries} attempts. {final_judgment.reason}",
                    "code_generated": generated_code or "",
                }

            artifact_extensions = {
                ".png",
                ".jpg",
                ".jpeg",
                ".svg",
                ".pdf",
                ".webp",
                ".csv",
                ".json",
                ".txt",
            }
            files_after_execution = {
                p
                for p in work_dir.rglob("*")
                if p.is_file()
                and p not in files_before_execution
                and p.suffix.lower() in artifact_extensions
            }
            artifacts: List[str] = []
            self.output_dir.mkdir(parents=True, exist_ok=True)
            for idx, p in enumerate(files_after_execution):
                dest = self.output_dir / p.name
                if dest.exists() and dest.resolve() != p.resolve():
                    stem, suf = p.stem, p.suffix
                    dest = self.output_dir / f"{stem}_{idx}{suf}"
                if not dest.exists() or dest.resolve() != p.resolve():
                    shutil.copy2(p, dest)
                artifacts.append(str(dest))

            for p in self.output_dir.glob("**/*"):
                if p.is_file() and p.suffix.lower() in artifact_extensions:
                    if str(p) not in artifacts:
                        artifacts.append(str(p))

            return {
                "success": True,
                "code_generated": generated_code or "",
                "stdout": exec_result.stdout or "",
                "stderr": exec_result.stderr or "",
                "artifacts": artifacts,
            }
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _judge_execution_result(
        self,
        generated_code: str,
        exec_result: Any,
        work_dir: Path,
        files_before_execution: set,
    ) -> ExecutionResult:
        """
        使用LLM判断代码执行结果是否成功。

        Args:
            generated_code: 生成的代码
            exec_result: 执行结果对象
            work_dir: 工作目录
            files_before_execution: 执行前的文件集合

        Returns:
            ExecutionResult 判断结果
        """
        # Collect artifacts
        artifact_extensions = {
            ".png",
            ".jpg",
            ".jpeg",
            ".svg",
            ".pdf",
            ".webp",
            ".csv",
            ".json",
            ".txt",
        }
        files_after = {
            p
            for p in work_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in artifact_extensions
        }
        new_files = files_after - files_before_execution
        output_dir_files = list(self.output_dir.glob("**/*"))

        def _fallback_check() -> ExecutionResult:
            if (
                exec_result
                and exec_result.return_code == 0
                and (exec_result.stdout.strip() or new_files or output_dir_files)
            ):
                return ExecutionResult(
                    success=True, reason="Execution completed with output"
                )
            return ExecutionResult(
                success=False,
                reason="LLM judgment failed, execution may have failed",
                should_retry=True,
                retry_instruction="Check the execution output and fix any errors",
            )

        def _trunc(s: str, max_len: int = 4000) -> str:
            if not s:
                return s
            t = str(s).strip()
            if len(t) <= max_len:
                return t
            return t[
                :max_len
            ] + "\n[output truncated for display, full length=%d]" % len(t)

        stdout_trunc = _trunc(exec_result.stdout if exec_result else "", 4000)
        stderr_trunc = _trunc(exec_result.stderr if exec_result else "", 2000)
        code_preview_len = 4000
        code_trunc = (generated_code or "")[:code_preview_len]
        code_suffix = (
            "\n[code truncated for display, full length=%d]" % len(generated_code or "")
            if len(generated_code or "") > code_preview_len
            else ""
        )

        execution_summary = f"""## Code Execution Result

**IMPORTANT**: STDOUT, STDERR, and Generated Code below may be truncated for display. The "[truncated for display]" marker means WE cut the text for brevity—the script ran in full and its output was complete. Do NOT treat display truncation as script incompleteness. Judge by: return code, files created, and the visible content.

**Return Code**: {exec_result.return_code if exec_result else "N/A"}

**STDOUT**:
```
{stdout_trunc or "No output"}
```

**STDERR**:
```
{stderr_trunc or "No error"}
```

**New Files Created in Work Directory**: {len(new_files)} files
**Output Directory Files**: {len(output_dir_files)} files

**Generated Code** (preview):
```python
{code_trunc}{code_suffix}
```

You should analyze the execution result and determine:
1. Did the code execute successfully (exit 0)?
2. Did it produce the expected output or files matching the task?
3. Are there any errors in stderr that indicate failure?
4. Is the result reasonable and complete for the described task (not partial or wrong output)?
5. success=true only if the outcome is both correct and complete.

{judgment_prompt()}"""

        messages: List[AllMessageValues] = [
            {"role": "user", "content": execution_summary}
        ]

        response = await self._router.acompletion(
            model=self._model_name,
            messages=messages,
        )

        content = response.choices[0].message.content  # type: ignore
        if not content:
            return _fallback_check()

        try:
            return parse_llm_xml_to_model(content, ExecutionResult, root_tag="judgment")
        except XmlParseError:
            return _fallback_check()
