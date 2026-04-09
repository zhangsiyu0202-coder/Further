"""
代码保存器

将生成的代码保存到文件。
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from agentsociety2.code_executor.path_config import PathConfig
from agentsociety2.logger import get_logger

logger = get_logger()


class CodeSaver:
    """
    代码保存器

    将生成的代码保存到指定路径。
    """

    def __init__(self, path_config: PathConfig):
        """
        初始化代码保存器

        Args:
            path_config: 路径配置对象
        """
        self._path_config = path_config
        self._default_save_dir = path_config.get_default_save_dir()

        # 确保目录存在
        self._default_save_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"CodeSaver初始化: 默认保存目录={self._default_save_dir}")

    def save(
        self,
        code: str,
        save_path: Optional[str] = None,
        filename: Optional[str] = None,
        unique_id: Optional[str] = None,
    ) -> str:
        """
        保存代码到文件

        Args:
            code: 要保存的代码
            save_path: 保存路径（文件路径或目录路径）。如果为None，使用默认目录。
            filename: 文件名（仅在save_path为目录时有效）。如果为None，使用时间戳生成文件名。
            unique_id: 可选的唯一标识符，用于生成唯一的文件名

        Returns:
            保存的文件路径
        """
        # 确定保存路径
        if save_path is None:
            save_dir = self._default_save_dir
            if filename is None:
                filename = self._path_config.get_code_filename(unique_id=unique_id)
            save_file = save_dir / filename
        else:
            save_file = Path(save_path)
            if save_file.is_dir() or (not save_file.suffix and not save_file.exists()):
                if filename is None:
                    filename = self._path_config.get_code_filename(unique_id=unique_id)
                save_file = save_file / filename
            # 确保目录存在
            save_file.parent.mkdir(parents=True, exist_ok=True)

        # 确保文件扩展名为.py
        if save_file.suffix != ".py":
            save_file = save_file.with_suffix(".py")

        # 保存代码
        try:
            with open(save_file, "w", encoding="utf-8") as f:
                f.write(code)

            logger.info(f"代码已保存到: {save_file}")
            return str(save_file)

        except Exception as e:
            logger.error(f"保存代码失败: {e}")
            raise
