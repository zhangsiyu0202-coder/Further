"""
代码执行器

所有代码均在受限 Docker Sandbox 中执行。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, Optional

from agentsociety2.code_executor.docker_runner import DockerRunner
from agentsociety2.code_executor.models import ExecutionResult
from agentsociety2.code_executor.runtime_config import DockerRuntimeConfig
from agentsociety2.logger import get_logger

logger = get_logger()

# 在基础镜像中已预装的常用依赖，避免重复安装占用磁盘
PREINSTALLED_DEPENDENCIES = {
    "numpy",
    "pandas",
    "matplotlib",
    "pillow",
    "seaborn",
    "scikit-learn",
    "openpyxl",
    "json-repair",
    "PyYAML",
    "pyyaml",
}


class CodeExecutor:
    """容器化代码执行器。"""

    def __init__(
        self,
        work_dir: Path,
        docker_config: Optional[DockerRuntimeConfig] = None,
        artifacts_dir: Optional[Path] = None,
    ):
        """
        Args:
            work_dir: 宿主工作目录，用于挂载到容器（必需参数）
            docker_config: Docker 沙箱配置
            artifacts_dir: 执行产物保存目录
        """
        self._docker_config = docker_config or DockerRuntimeConfig.from_env()
        self._runner = DockerRunner(
            self._docker_config,
            work_dir=work_dir,
            artifacts_dir=artifacts_dir,
        )

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
        在 Docker 沙箱中执行代码。

        Args:
            code: Python 代码
            dependencies: 需要预先安装的依赖包列表（可选）
            timeout: 超时时间（秒）
            input_data: 标准输入
        """

        start_time = time.time()

        # 过滤掉基础镜像中已经预装的依赖，避免重复安装占用磁盘空间
        deps = [
            dep.strip()
            for dep in (dependencies or [])
            if dep.strip() and dep.strip() not in PREINSTALLED_DEPENDENCIES
        ]

        result = await self._runner.execute(
            code,
            dependencies=deps or None,
            timeout=timeout,
            input_data=input_data,
            extra_files=extra_files,
            program_args=program_args,
        )

        execution_time = time.time() - start_time
        return result.model_copy(update={"execution_time": execution_time})
