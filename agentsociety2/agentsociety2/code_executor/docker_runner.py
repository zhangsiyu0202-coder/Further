"""
Docker 执行沙箱。

负责将生成的代码放入临时工作目录，并使用受限 Docker 容器执行。
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Iterable, Optional

from agentsociety2.code_executor.models import ExecutionResult
from agentsociety2.code_executor.runtime_config import DockerRuntimeConfig
from agentsociety2.logger import get_logger

logger = get_logger()


class DockerRunner:
    """封装 docker run 调用。"""

    def __init__(
        self,
        config: DockerRuntimeConfig,
        work_dir: Path,
        artifacts_dir: Optional[Path] = None,
    ):
        self._config = config
        self._docker_bin = shutil.which(config.binary)
        if not self._docker_bin:
            raise RuntimeError(f"Docker命令不可用: {config.binary}")
        base_dir = Path(work_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        self._work_dir = base_dir
        self._artifact_dir = Path(artifacts_dir) if artifacts_dir else None
        if self._artifact_dir:
            self._artifact_dir.mkdir(parents=True, exist_ok=True)

    async def execute(
        self,
        code: str,
        dependencies: Optional[Iterable[str]] = None,
        *,
        timeout: int = 300,
        input_data: Optional[str] = None,
        extra_files: Optional[Iterable[str | Path]] = None,
        program_args: Optional[Iterable[str]] = None,
    ) -> ExecutionResult:
        """
        在受限 Docker 环境中执行代码。

        Args:
            code: 需要执行的 Python 代码。
            dependencies: 运行时需要安装的依赖。
            timeout: 执行超时时间（秒）。
            input_data: 传入标准输入的数据。
            extra_files: 挂载到容器工作目录的额外文件列表。
            program_args: 作为命令行参数传给 main.py 的参数列表。
        """

        dependencies = list(dependencies or [])
        program_args = list(program_args or [])
        tmp_dir = tempfile.mkdtemp(prefix="code_executor_", dir=str(self._work_dir))
        tmp_path = Path(tmp_dir)

        try:
            os.chmod(tmp_path, 0o777)
        except Exception as e:
            logger.warning(f"无法设置临时目录权限: {e}")

        code_path = tmp_path / "main.py"
        code_path.write_text(code, encoding="utf-8")
        # 确保文件对容器内的 sandbox 用户可读
        try:
            os.chmod(code_path, 0o644)
        except Exception as e:
            logger.warning(f"无法设置代码文件权限: {e}")

        requirements_path = None
        if dependencies:
            requirements_path = tmp_path / "requirements.txt"
            requirements_path.write_text("\n".join(dependencies), encoding="utf-8")
            # 确保文件对容器内的 sandbox 用户可读
            try:
                os.chmod(requirements_path, 0o644)
            except Exception as e:
                logger.warning(f"无法设置依赖文件权限: {e}")

        # 复制额外需要在容器中访问的输入文件
        extra_files = list(extra_files or [])
        for file_path in extra_files:
            try:
                src = Path(file_path)
                if not src.exists():
                    logger.warning(f"额外输入文件不存在，跳过复制: {src}")
                    continue

                dst = tmp_path / src.name
                shutil.copy2(src, dst)
                try:
                    os.chmod(dst, 0o644)
                except Exception as e:
                    logger.warning(f"无法设置输入文件权限: {dst}, 错误: {e}")
            except Exception as e:
                logger.warning(f"复制额外输入文件失败: {file_path}, 错误: {e}")

        mount_spec = f"{self._normalize_host_path(tmp_path)}:{self._config.workdir}:rw"
        container_name = f"codeexec-{uuid.uuid4().hex[:12]}"

        cmd = [self._docker_bin, "run", "--rm", "--name", container_name]

        if self._config.network_mode:
            cmd += ["--network", self._config.network_mode]

        if self._config.read_only_root:
            cmd.append("--read-only")

        if self._config.enable_tmpfs:
            cmd += [
                "--tmpfs",
                f"/tmp:rw,noexec,nosuid,size={self._config.tmpfs_size_mb}m",
            ]

        if self._config.runtime:
            cmd += ["--runtime", self._config.runtime]

        if self._config.cpus:
            cmd += ["--cpus", str(self._config.cpus)]

        if self._config.memory:
            cmd += ["--memory", str(self._config.memory)]

        if self._config.pids_limit:
            cmd += ["--pids-limit", str(self._config.pids_limit)]

        if self._config.extra_args:
            cmd += list(self._config.extra_args)

        cmd += ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]

        cmd += [
            "-v",
            mount_spec,
            "-w",
            self._config.workdir,
        ]

        # 使用宿主机当前用户身份运行容器，避免生成的文件无法在宿主机删除
        try:
            uid = os.getuid()
            gid = os.getgid()
            cmd += ["--user", f"{uid}:{gid}"]
        except Exception as e:
            # 如果获取 UID/GID 失败，回退到 sandbox 用户
            logger.warning(f"获取宿主机 UID/GID 失败，回退为 sandbox 用户: {e}")
            cmd += ["--user", "sandbox"]

        env_vars: list[str] = []
        # 透传 pip 相关配置
        if self._config.pip_index_url:
            env_vars += ["-e", f"PIP_INDEX_URL={self._config.pip_index_url}"]
        if self._config.pip_extra_index_url:
            env_vars += [
                "-e",
                f"PIP_EXTRA_INDEX_URL={self._config.pip_extra_index_url}",
            ]

        # 透传与 LLM 调用相关的环境变量到沙箱中
        # 这样在容器内执行的 main.py 也能正常读取 API_KEY / API_BASE 等
        for key in [
            "API_KEY",
            "API_BASE",
            "AGENT_EVALUATOR_MODEL",
            "AGENT_FILTER_MODEL",
        ]:
            value = os.environ.get(key)
            if value:
                env_vars += ["-e", f"{key}={value}"]

        shell_script = self._build_shell_command(
            has_requirements=requirements_path is not None,
            program_args=program_args,
        )

        cmd += env_vars
        cmd += [self._config.image, "/bin/sh", "-c", shell_script]

        logger.debug("Docker命令: %s", " ".join(shlex.quote(part) for part in cmd))

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if input_data else None,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        artifacts_path: Optional[Path] = None
        try:
            stdout, stderr = process.communicate(input=input_data, timeout=timeout)
            success = process.returncode == 0
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            success = False
            stderr += f"\n执行超时（超过{timeout}秒）"
            logger.error("Docker执行超时, 容器: %s", container_name)
        finally:
            try:
                artifacts_path = self._persist_artifacts(tmp_path)
                shutil.rmtree(tmp_path, ignore_errors=True)
            except Exception as exc:
                logger.warning("清理临时目录失败: %s", exc)

        execution_time = 0.0  # 具体耗时由 CodeExecutor 记录
        return ExecutionResult(
            success=success,
            stdout=stdout or "",
            stderr=stderr or "",
            return_code=process.returncode if process.returncode is not None else -1,
            execution_time=execution_time,
            artifacts_path=str(artifacts_path) if artifacts_path else None,
        )

    def _build_shell_command(
        self,
        *,
        has_requirements: bool,
        program_args: Optional[Iterable[str]] = None,
    ) -> str:
        deps_dir = ".deps"
        lines = [
            "set -eu",
            "export PYTHONUNBUFFERED=1",
        ]

        if has_requirements:
            lines += [
                'echo "[sandbox] Installing dependencies..."',
                f"mkdir -p {deps_dir}",
                f"python -m pip install --no-cache-dir -r requirements.txt --target {deps_dir}",
                f'export PYTHONPATH="$PWD/{deps_dir}:${{PYTHONPATH:-}}"',
            ]

        args_str = " ".join(shlex.quote(str(arg)) for arg in (program_args or []))

        lines += [
            'echo "[sandbox] Starting code execution..."',
            f"exec python main.py {args_str}".rstrip(),
        ]

        return "\n".join(lines)

    @staticmethod
    def _normalize_host_path(path: Path) -> str:
        # Docker Desktop 在 Windows 上接受形如 C:/path 的写法
        return path.resolve().as_posix()

    def _persist_artifacts(self, tmp_path: Path) -> Optional[Path]:
        """
        将执行过程中生成的文件复制到持久化目录
        """
        if not self._artifact_dir:
            return None

        dest_dir = self._artifact_dir / tmp_path.name
        try:
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)

            ignore = shutil.ignore_patterns("main.py", "requirements.txt", ".deps", ".deps/*")
            shutil.copytree(tmp_path, dest_dir, ignore=ignore)

            if not any(dest_dir.iterdir()):
                shutil.rmtree(dest_dir, ignore_errors=True)
                return None

            logger.info("执行产物已保存到: %s", dest_dir)
            return dest_dir
        except Exception as exc:
            logger.warning("保存执行产物失败: %s", exc)
            try:
                if dest_dir.exists():
                    shutil.rmtree(dest_dir, ignore_errors=True)
            except Exception:
                pass
            return None
