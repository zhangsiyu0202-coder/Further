"""
本地代码执行器

直接使用当前Python解释器执行代码，不使用Docker。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from agentsociety2.code_executor.models import ExecutionResult
from agentsociety2.logger import get_logger

logger = get_logger()


class LocalCodeExecutor:
    """本地代码执行器，直接使用当前Python解释器执行代码"""

    def __init__(self, work_dir: Path):
        """
        Args:
            work_dir: 工作目录，用于执行代码
        """
        self._work_dir = Path(work_dir)
        self._work_dir.mkdir(parents=True, exist_ok=True)

    async def execute(
        self,
        code: str,
        *,
        dependencies: Optional[Iterable[str]] = None,
        timeout: int = 300,
        input_data: Optional[str] = None,
        extra_files: Optional[Iterable[Path | str]] = None,
        program_args: Optional[Iterable[str]] = None,
    ) -> ExecutionResult:
        """
        在当前Python解释器中执行代码

        Args:
            code: Python 代码
            dependencies: 需要预先安装的依赖包列表（可选，会尝试安装）
            timeout: 超时时间（秒）
            input_data: 标准输入
            extra_files: 额外文件（暂不支持）
            program_args: 程序参数（暂不支持）

        Returns:
            执行结果
        """
        start_time = time.time()

        # 创建临时文件保存代码
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            dir=self._work_dir,
            delete=False,
            encoding="utf-8",
        ) as tmp_file:
            tmp_file.write(code)
            tmp_file_path = Path(tmp_file.name)

        try:
            # 准备环境变量：显式传递父进程的环境变量
            env = os.environ.copy()

            # 如果需要安装依赖
            if dependencies:
                deps_list = [dep.strip() for dep in dependencies if dep.strip()]
                if deps_list:
                    logger.info(f"安装依赖: {deps_list}")
                    try:
                        # 尝试安装依赖（非阻塞，如果失败继续执行）
                        install_process = await asyncio.create_subprocess_exec(
                            sys.executable,
                            "-m",
                            "pip",
                            "install",
                            "--quiet",
                            *deps_list,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            env=env,  # 显式传递环境变量
                        )
                        await install_process.wait()
                        if install_process.returncode != 0:
                            logger.warning(f"依赖安装失败，但继续执行代码")
                    except Exception as e:
                        logger.warning(f"依赖安装出错: {e}，但继续执行代码")

            # 执行代码
            logger.info(f"执行代码文件: {tmp_file_path}")
            
            # 使用subprocess执行，捕获输出
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(tmp_file_path),
                stdin=subprocess.PIPE if input_data else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self._work_dir),
                env=env,  # 显式传递环境变量
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=input_data.encode("utf-8") if input_data else None),
                    timeout=timeout,
                )
                success = process.returncode == 0
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                stdout = b""
                stderr = f"执行超时（超过{timeout}秒）".encode("utf-8")
                success = False
                logger.error(f"代码执行超时: {tmp_file_path}")

            execution_time = time.time() - start_time

            return ExecutionResult(
                success=success,
                stdout=stdout.decode("utf-8", errors="replace") if stdout else "",
                stderr=stderr.decode("utf-8", errors="replace") if stderr else "",
                return_code=process.returncode if process.returncode is not None else -1,
                execution_time=execution_time,
                artifacts_path=None,  # 本地执行不支持artifacts
            )

        finally:
            # 清理临时文件
            try:
                tmp_file_path.unlink()
            except Exception as e:
                logger.warning(f"清理临时文件失败: {e}")

