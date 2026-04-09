"""Base module registry class

Provides a centralized registry for agent classes and environment modules.
Supports lazy loading - modules are only discovered when first accessed.
"""

from __future__ import annotations

from typing import Dict, List, Tuple, Type, Optional, Any
from pathlib import Path
from importlib import import_module
import inspect

from agentsociety2.agent.base import AgentBase
from agentsociety2.env.base import EnvBase
from agentsociety2.logger import get_logger

logger = get_logger()


class ModuleRegistry:
    """Central registry for agent and environment modules

    This class manages registration and retrieval of agent classes and
    environment modules, supporting both built-in and custom modules.

    Implements lazy loading - built-in modules are only discovered on first access.
    """

    _instance: Optional["ModuleRegistry"] = None

    def __new__(cls) -> "ModuleRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._env_modules: Dict[str, Type[EnvBase]] = {}
        self._agent_modules: Dict[str, Type[AgentBase]] = {}
        self._workspace_path: Optional[Path] = None

        # Lazy loading flags
        self._builtin_loaded: bool = False
        self._custom_loaded: bool = False
        self._lazy_enabled: bool = True  # Can be disabled to force eager loading

        logger.info("ModuleRegistry initialized (lazy loading enabled)")

    def _ensure_builtin_loaded(self) -> None:
        """Ensure built-in modules are loaded (lazy loading trigger)"""
        if not self._lazy_enabled:
            return
        if self._builtin_loaded:
            return

        from agentsociety2.registry.modules import discover_and_register_builtin_modules

        discover_and_register_builtin_modules(self)
        self._builtin_loaded = True

    def _ensure_custom_loaded(self) -> None:
        """Ensure custom modules are loaded (lazy loading trigger)"""
        if not self._lazy_enabled:
            return
        if not self._workspace_path:
            # No workspace set, nothing to load
            self._custom_loaded = True
            return
        if self._custom_loaded:
            return

        from agentsociety2.registry.modules import scan_and_register_custom_modules

        scan_and_register_custom_modules(self._workspace_path, self)
        self._custom_loaded = True

    def _ensure_loaded(self) -> None:
        """Ensure all modules are loaded (lazy loading trigger)"""
        self._ensure_builtin_loaded()
        self._ensure_custom_loaded()

    @property
    def env_modules(self) -> Dict[str, Type[EnvBase]]:
        """Get all registered environment modules (triggers lazy loading)"""
        self._ensure_loaded()
        return self._env_modules.copy()

    @property
    def agent_modules(self) -> Dict[str, Type[AgentBase]]:
        """Get all registered agent modules (triggers lazy loading)"""
        self._ensure_loaded()
        return self._agent_modules.copy()

    def register_env_module(
        self, module_type: str, module_class: Type[EnvBase], is_custom: bool = False
    ) -> None:
        """Register an environment module

        Args:
            module_type: The type identifier (e.g., "simple_social_space")
            module_class: The environment module class
            is_custom: Whether this is a custom module
        """
        if module_type in self._env_modules and not is_custom:
            logger.debug(f"Env module '{module_type}' already registered, skipping")
            return

        self._env_modules[module_type] = module_class
        logger.debug(f"Registered env module: {module_type} -> {module_class.__name__}")

    def register_agent_module(
        self, agent_type: str, agent_class: Type[AgentBase], is_custom: bool = False
    ) -> None:
        """Register an agent module

        Args:
            agent_type: The type identifier (e.g., "person_agent")
            agent_class: The agent class
            is_custom: Whether this is a custom agent
        """
        if agent_type in self._agent_modules and not is_custom:
            logger.debug(f"Agent '{agent_type}' already registered, skipping")
            return

        self._agent_modules[agent_type] = agent_class
        logger.debug(f"Registered agent: {agent_type} -> {agent_class.__name__}")

    def get_env_module(self, module_type: str) -> Optional[Type[EnvBase]]:
        """Get an environment module class by type (triggers lazy loading)

        Args:
            module_type: The type identifier

        Returns:
            The environment module class, or None if not found
        """
        self._ensure_builtin_loaded()
        return self._env_modules.get(module_type)

    def get_agent_module(self, agent_type: str) -> Optional[Type[AgentBase]]:
        """Get an agent module class by type (triggers lazy loading)

        Args:
            agent_type: The type identifier

        Returns:
            The agent class, or None if not found
        """
        self._ensure_builtin_loaded()
        return self._agent_modules.get(agent_type)

    def list_env_modules(self) -> List[Tuple[str, Type[EnvBase]]]:
        """List all registered environment modules (triggers lazy loading)

        Returns:
            List of (module_type, module_class) tuples
        """
        self._ensure_loaded()
        return list(self._env_modules.items())

    def list_agent_modules(self) -> List[Tuple[str, Type[AgentBase]]]:
        """List all registered agent modules (triggers lazy loading)

        Returns:
            List of (agent_type, agent_class) tuples
        """
        self._ensure_loaded()
        return list(self._agent_modules.items())

    def set_workspace(self, workspace_path: Path) -> None:
        """Set the workspace path for custom module discovery

        Args:
            workspace_path: Path to the workspace directory
        """
        self._workspace_path = workspace_path.resolve()
        # Reset custom loaded flag so modules will be discovered on next access
        self._custom_loaded = False
        logger.debug(f"Registry workspace set to: {self._workspace_path}")

    def load_builtin_modules(self) -> None:
        """Eagerly load built-in modules"""
        self._ensure_builtin_loaded()

    def load_custom_modules(self) -> None:
        """Eagerly load custom modules"""
        self._ensure_custom_loaded()

    def load_all_modules(self) -> None:
        """Eagerly load all modules"""
        self._ensure_loaded()

    def clear_custom_modules(self) -> None:
        """Clear all custom modules from the registry"""
        to_remove = [
            mt for mt, mc in self._env_modules.items()
            if getattr(mc, "_is_custom", False)
        ]
        for mt in to_remove:
            del self._env_modules[mt]

        to_remove = [
            at for at, ac in self._agent_modules.items()
            if getattr(ac, "_is_custom", False)
        ]
        for at in to_remove:
            del self._agent_modules[at]

        # Reset custom loaded flag so modules will be re-discovered on next access
        self._custom_loaded = False

        logger.info(f"Cleared {len(to_remove)} custom modules")

    def get_module_info(self, module_type: str, kind: str) -> Dict[str, Any]:
        """Get information about a module (triggers lazy loading)

        Args:
            module_type: The type identifier
            kind: Either "env_module" or "agent"

        Returns:
            Dictionary with module information
        """
        self._ensure_builtin_loaded()

        if kind == "env_module":
            cls = self.get_env_module(module_type)
        else:
            cls = self.get_agent_module(module_type)

        if cls is None:
            return {
                "success": False,
                "error": f"Module '{module_type}' not found",
            }

        # Try to get description
        description = ""
        try:
            if hasattr(cls, "mcp_description"):
                description = cls.mcp_description()
            else:
                description = cls.__doc__ or f"{cls.__name__}"
        except Exception:
            description = f"{cls.__name__}"

        # Get constructor signature
        params = {}
        try:
            sig = inspect.signature(cls.__init__)
            for name, param in list(sig.parameters.items())[1:]:  # Skip 'self'
                params[name] = {
                    "annotation": str(param.annotation)
                    if param.annotation != inspect.Parameter.empty
                    else "Any",
                    "default": str(param.default)
                    if param.default != inspect.Parameter.empty
                    else None,
                    "kind": str(param.kind),
                }
        except Exception:
            pass

        return {
            "success": True,
            "type": module_type,
            "class_name": cls.__name__,
            "description": description,
            "parameters": params,
            "is_custom": getattr(cls, "_is_custom", False),
        }


# Global registry instance
_registry: Optional[ModuleRegistry] = None


def get_registry() -> ModuleRegistry:
    """Get the global module registry instance"""
    global _registry
    if _registry is None:
        _registry = ModuleRegistry()
    return _registry
