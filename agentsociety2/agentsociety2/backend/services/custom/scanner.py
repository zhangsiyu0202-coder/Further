"""
自定义模块扫描服务

扫描 custom/ 目录，发现用户自定义的 Agent 和环境模块。
"""

from pathlib import Path
from typing import List, Dict, Any
import importlib.util
import sys
import inspect


class CustomModuleScanner:
    """自定义模块扫描服务"""

    def __init__(self, workspace_path: str):
        """
        初始化扫描器

        Args:
            workspace_path: 工作区路径
        """
        self.workspace_path = Path(workspace_path).resolve()
        self.custom_dir = self.workspace_path / "custom"

    def scan_all(self) -> Dict[str, Any]:
        """
        扫描所有自定义模块

        Returns:
            包含 agents, envs, errors 的字典
        """
        result = {"agents": [], "envs": [], "errors": []}

        if not self.custom_dir.exists():
            result["errors"].append(f"custom/ 目录不存在: {self.custom_dir}")
            return result

        # 扫描 Agent（跳过 examples 子目录）
        agents_dir = self.custom_dir / "agents"
        if agents_dir.exists():
            result["agents"] = self._scan_agents(agents_dir, skip_examples=True)
        else:
            result["errors"].append(f"custom/agents/ 目录不存在")

        # 扫描环境模块（跳过 examples 子目录）
        envs_dir = self.custom_dir / "envs"
        if envs_dir.exists():
            result["envs"] = self._scan_envs(envs_dir, skip_examples=True)
        else:
            result["errors"].append(f"custom/envs/ 目录不存在")

        return result

    def _scan_agents(
        self, agents_dir: Path, skip_examples: bool = True
    ) -> List[Dict[str, Any]]:
        """
        扫描 Agent 目录

        Args:
            agents_dir: Agent 目录路径
            skip_examples: 是否跳过 examples 子目录

        Returns:
            发现的 Agent 列表
        """
        agents = []

        for py_file in agents_dir.rglob("*.py"):
            # 跳过 __init__.py
            if py_file.name.startswith("__"):
                continue

            # 跳过 examples 目录
            if skip_examples and "examples" in py_file.parts:
                continue

            try:
                agent_classes = self._extract_agent_classes(py_file)
                for cls in agent_classes:
                    agents.append(
                        {
                            "type": cls.__name__,
                            "class_name": cls.__name__,
                            "module_path": str(
                                py_file.relative_to(self.workspace_path)
                            ),
                            "file_path": str(py_file),
                            "description": self._get_safe_description(cls),
                        }
                    )
            except Exception as e:
                # 记录错误但继续扫描
                pass

        return agents

    def _scan_envs(
        self, envs_dir: Path, skip_examples: bool = True
    ) -> List[Dict[str, Any]]:
        """
        扫描环境模块目录

        Args:
            envs_dir: 环境模块目录路径
            skip_examples: 是否跳过 examples 子目录

        Returns:
            发现的环境模块列表
        """
        envs = []

        for py_file in envs_dir.rglob("*.py"):
            # 跳过 __init__.py
            if py_file.name.startswith("__"):
                continue

            # 跳过 examples 目录
            if skip_examples and "examples" in py_file.parts:
                continue

            try:
                env_classes = self._extract_env_classes(py_file)
                for cls in env_classes:
                    envs.append(
                        {
                            "type": cls.__name__,
                            "class_name": cls.__name__,
                            "module_path": str(
                                py_file.relative_to(self.workspace_path)
                            ),
                            "file_path": str(py_file),
                            "description": self._get_safe_description(cls),
                        }
                    )
            except Exception as e:
                pass

        return envs

    def _extract_agent_classes(self, file_path: Path) -> List:
        """
        从文件中提取 Agent 类

        Args:
            file_path: Python 文件路径

        Returns:
            Agent 类列表
        """
        # 动态导入模块
        spec = importlib.util.spec_from_file_location(
            f"custom_module_{id(file_path)}", file_path
        )
        if spec is None or spec.loader is None:
            return []

        module = importlib.util.module_from_spec(spec)

        # 设置模块名称以避免冲突
        module_name = f"custom_module_{id(file_path)}"
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            # 导入失败，返回空列表
            del sys.modules[module_name]
            return []

        try:
            from agentsociety2.agent.base import AgentBase

            agents = []
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # 检查是否是 AgentBase 的子类，且不是 AgentBase 本身
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, AgentBase)
                    and obj is not AgentBase
                    and obj.__module__ == module_name
                ):
                    if self._validate_agent_class(obj):
                        agents.append(obj)

            return agents
        finally:
            # 清理模块
            if module_name in sys.modules:
                del sys.modules[module_name]

    def _extract_env_classes(self, file_path: Path) -> List:
        """
        从文件中提取环境模块类

        Args:
            file_path: Python 文件路径

        Returns:
            环境模块类列表
        """
        # 动态导入模块
        spec = importlib.util.spec_from_file_location(
            f"custom_module_{id(file_path)}", file_path
        )
        if spec is None or spec.loader is None:
            return []

        module = importlib.util.module_from_spec(spec)
        module_name = f"custom_module_{id(file_path)}"
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception:
            del sys.modules[module_name]
            return []

        try:
            from agentsociety2.env.base import EnvBase

            envs = []
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, EnvBase)
                    and obj is not EnvBase
                    and obj.__module__ == module_name
                ):
                    if self._validate_env_class(obj):
                        envs.append(obj)

            return envs
        finally:
            if module_name in sys.modules:
                del sys.modules[module_name]

    def _validate_agent_class(self, cls) -> bool:
        """
        验证 Agent 类是否实现必需方法

        Args:
            cls: 要验证的类

        Returns:
            是否有效
        """
        required_methods = ["ask", "step", "dump", "load"]
        for method in required_methods:
            if not hasattr(cls, method):
                return False
        return True

    def _validate_env_class(self, cls) -> bool:
        """
        验证环境模块类是否有效

        Args:
            cls: 要验证的类

        Returns:
            是否有效
        """
        required_methods = ["step"]
        for method in required_methods:
            if not hasattr(cls, method):
                return False
        # 检查是否有工具方法
        if not hasattr(cls, "_registered_tools"):
            return False
        return len(cls._registered_tools) > 0

    def _get_safe_description(self, cls) -> str:
        """
        安全地获取类的描述

        Args:
            cls: 类对象

        Returns:
            描述字符串
        """
        try:
            if hasattr(cls, "mcp_description"):
                return cls.mcp_description()
            return cls.__doc__ or f"{cls.__name__}: 无描述"
        except Exception:
            return f"{cls.__name__}: 描述获取失败"
