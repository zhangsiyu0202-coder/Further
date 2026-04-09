"""
路径配置模块

提供统一的路径配置管理，支持自定义所有路径。
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator, ConfigDict


DEFAULT_ROOT_DIR = (Path(__file__).resolve().parents[2] / "log").resolve()
DEFAULT_WORK_SUBDIR = "workspace"
DEFAULT_SAVE_SUBDIR = "generated_code"
DEFAULT_ARTIFACTS_SUBDIR = "artifacts"


class PathConfig(BaseModel):
    """
    路径配置类

    管理临时工作目录和代码保存目录。
    """

    work_dir: Optional[str] = Field(
        default=None,
        description="沙箱工作目录根路径，用于挂载到容器，可选",
    )
    default_save_dir: Optional[str] = Field(
        default=None,
        description="默认代码保存目录，默认为工作目录下的 generated_code",
    )
    log_dir: Optional[str] = Field(
        default=None,
        description="日志目录，默认使用 log 根目录",
    )
    artifacts_dir: Optional[str] = Field(
        default=None,
        description="执行产物目录，默认使用 log/artifacts",
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("work_dir", "default_save_dir", "log_dir", "artifacts_dir", mode="before")
    @classmethod
    def expand_path_vars(cls, v: Optional[str]) -> Optional[str]:
        """
        展开路径中的环境变量和用户目录

        Args:
            v: 路径字符串

        Returns:
            展开后的路径字符串
        """
        if v is None:
            return None

        v = os.path.expandvars(v)
        v = os.path.expanduser(v)

        return v

    @classmethod
    def from_env(cls) -> "PathConfig":
        """
        从环境变量创建路径配置

        支持的环境变量：
        - CODE_EXECUTOR_WORK_DIR: 工作目录
        - CODE_EXECUTOR_SAVE_DIR: 代码保存目录

        Returns:
            路径配置实例
        """
        return cls(
            work_dir=os.getenv("CODE_EXECUTOR_WORK_DIR"),
            default_save_dir=os.getenv("CODE_EXECUTOR_SAVE_DIR"),
            log_dir=os.getenv("CODE_EXECUTOR_LOG_DIR"),
            artifacts_dir=os.getenv("CODE_EXECUTOR_ARTIFACTS_DIR"),
        )

    @classmethod
    def default(cls) -> "PathConfig":
        """
        创建默认路径配置

        Returns:
            默认路径配置实例
        """
        return cls()

    def _default_root(self) -> Path:
        DEFAULT_ROOT_DIR.mkdir(parents=True, exist_ok=True)
        return DEFAULT_ROOT_DIR

    def get_work_dir(self) -> Path:
        """
        获取工作目录的完整路径

        Returns:
            工作目录的Path对象
        """
        if self.work_dir:
            base = Path(self.work_dir)
        else:
            base = self._default_root() / DEFAULT_WORK_SUBDIR
        base.mkdir(parents=True, exist_ok=True)
        return base

    def get_default_save_dir(self) -> Path:
        """
        获取默认代码保存目录的完整路径

        Returns:
            默认代码保存目录的Path对象
        """
        if self.default_save_dir:
            save_dir = Path(self.default_save_dir)
        else:
            save_dir = self._default_root() / DEFAULT_SAVE_SUBDIR
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir

    def get_log_dir(self) -> Path:
        """
        获取日志目录路径
        """
        if self.log_dir:
            log_dir = Path(self.log_dir)
        else:
            log_dir = self._default_root()
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def get_artifacts_dir(self) -> Path:
        """
        获取执行产物（如生成的文件）保存目录
        """
        if self.artifacts_dir:
            artifacts_dir = Path(self.artifacts_dir)
        else:
            artifacts_dir = self._default_root() / DEFAULT_ARTIFACTS_SUBDIR
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        return artifacts_dir

    def get_code_filename(self, unique_id: Optional[str] = None) -> str:
        """
        获取代码文件名

        Args:
            unique_id: 可选的唯一标识符（如UUID），用于避免文件名冲突

        Returns:
            代码文件名，格式：generated_code_YYYYMMDD_HHMMSS_ffffff_xxxxxxxx.py
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        if unique_id:
            short_id = unique_id[:8]
            return f"generated_code_{timestamp}_{short_id}.py"
        else:
            short_uuid = uuid.uuid4().hex[:8]
            return f"generated_code_{timestamp}_{short_uuid}.py"
