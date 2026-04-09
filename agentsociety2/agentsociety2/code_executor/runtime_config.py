"""
执行沙箱配置

构建命令：
    docker build -t agentsociety2/code-executor:latest -f docker/code_executor.Dockerfile .

参考: docker/CODE_EXECUTOR_BUILD.md
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DockerRuntimeConfig(BaseModel):
    """
    Docker 沙箱配置。

    大部分运行参数为固定默认值，仅保留少量必要的可调参数。
    """

    # 固定值（一般不需要修改）
    IMAGE: str = "agentsociety2/code-executor:latest"
    BINARY: str = "docker"
    NETWORK_MODE: str = "bridge"
    READ_ONLY_ROOT: bool = True
    WORKDIR: str = "/sandbox"
    ENABLE_TMPFS: bool = True
    RUNTIME: Optional[str] = None
    EXTRA_ARGS: list[str] = []

    # 资源限制
    CPUS: float = 1.0
    MEMORY: str = "1g"
    PIDS_LIMIT: int = 128
    TMPFS_SIZE_MB: int = 64
    pip_index_url: Optional[str] = Field(
        default=None,
        description="pip index url（可选，用于加速或私有源）",
    )
    pip_extra_index_url: Optional[str] = Field(
        default=None,
        description="pip extra index url（可选）",
    )

    model_config = {"extra": "forbid"}

    @property
    def cpus(self) -> float:
        """容器 CPU 限制"""
        return self.CPUS

    @property
    def memory(self) -> str:
        """容器内存限制"""
        return self.MEMORY

    @property
    def pids_limit(self) -> int:
        """容器进程数限制"""
        return self.PIDS_LIMIT

    @property
    def tmpfs_size_mb(self) -> int:
        """tmpfs 大小（MB）"""
        return self.TMPFS_SIZE_MB

    @property
    def image(self) -> str:
        """执行代码所需的基础镜像"""
        return self.IMAGE

    @property
    def binary(self) -> str:
        """docker 命令路径"""
        return self.BINARY

    @property
    def network_mode(self) -> str:
        """容器网络模式"""
        return self.NETWORK_MODE

    @property
    def read_only_root(self) -> bool:
        """是否将容器根文件系统设为只读"""
        return self.READ_ONLY_ROOT

    @property
    def workdir(self) -> str:
        """容器内工作目录"""
        return self.WORKDIR

    @property
    def enable_tmpfs(self) -> bool:
        """是否在 /tmp 挂载 tmpfs"""
        return self.ENABLE_TMPFS

    @property
    def runtime(self) -> Optional[str]:
        """可选的 runtime"""
        return self.RUNTIME

    @property
    def extra_args(self) -> list[str]:
        """额外 docker run 参数"""
        return self.EXTRA_ARGS.copy()

    @classmethod
    def from_env(cls) -> "DockerRuntimeConfig":
        """
        使用类中写死的默认配置创建运行时配置。

        当前版本不再从环境变量读取任何参数，如需自定义，
        请在创建 CodeExecutorAPI 时显式传入 DockerRuntimeConfig 实例。
        """
        return cls()
