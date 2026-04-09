"""Module auto-discovery and registration

Automatically discovers and registers built-in modules from contrib
and custom modules from the custom/ directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple, Type, Optional, Any
import importlib
import pkgutil

from agentsociety2.agent.base import AgentBase
from agentsociety2.env.base import EnvBase
from agentsociety2.logger import get_logger

from agentsociety2.registry.base import ModuleRegistry, get_registry

logger = get_logger()


def _discover_contrib_env_modules() -> Dict[str, Type[EnvBase]]:
    """Discover all environment modules from contrib.env

    Returns:
        Dict mapping class_name to module_class
    """
    modules = {}

    try:
        from agentsociety2.contrib import env as env_package

        # Walk through all modules in contrib.env
        for importer, modname, ispkg in pkgutil.walk_packages(
            env_package.__path__, env_package.__name__ + "."
        ):
            if modname.startswith("__"):
                continue

            try:
                module = importlib.import_module(modname)

                # Find EnvBase subclasses in this module
                for name, obj in vars(module).items():
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, EnvBase)
                        and obj is not EnvBase
                        and obj.__module__ == modname
                    ):
                        # Use class name directly as the key
                        if name and name not in modules:
                            modules[name] = obj
                            logger.debug(
                                f"Discovered env module: {name}"
                            )

            except Exception as e:
                logger.debug(f"Failed to import {modname}: {e}")

    except ImportError as e:
        logger.warning(f"Failed to import contrib.env: {e}")

    return modules


def _discover_contrib_agents() -> Dict[str, Type[AgentBase]]:
    """Discover all agents from contrib.agent

    Returns:
        Dict mapping class_name to agent_class
    """
    agents = {}

    try:
        from agentsociety2.contrib import agent as agent_package

        # Walk through all modules in contrib.agent
        for importer, modname, ispkg in pkgutil.walk_packages(
            agent_package.__path__, agent_package.__name__ + "."
        ):
            if modname.startswith("__"):
                continue

            try:
                module = importlib.import_module(modname)

                # Find AgentBase subclasses in this module
                for name, obj in vars(module).items():
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, AgentBase)
                        and obj is not AgentBase
                        and obj.__module__ == modname
                    ):
                        # Use class name directly as the key
                        if name and name not in agents:
                            agents[name] = obj
                            logger.debug(f"Discovered agent: {name}")

            except Exception as e:
                logger.debug(f"Failed to import {modname}: {e}")

    except ImportError as e:
        logger.warning(f"Failed to import contrib.agent: {e}")

    return agents


def _discover_builtin_agents() -> Dict[str, Type[AgentBase]]:
    """Discover built-in agents from agentsociety2.agent

    Returns:
        Dict mapping class_name to agent_class
    """
    agents = {}

    try:
        from agentsociety2.agent import person

        # Check PersonAgent
        if hasattr(person, "PersonAgent"):
            agents["PersonAgent"] = person.PersonAgent
            logger.debug("Discovered built-in agent: PersonAgent")

    except ImportError as e:
        logger.warning(f"Failed to import agentsociety2.agent: {e}")

    return agents


def _class_name_to_type(class_name: str) -> Optional[str]:
    """Convert a class name to a type identifier

    e.g., SimpleSocialSpace -> simple_social_space
         PersonAgent -> person_agent

    Args:
        class_name: The class name

    Returns:
        The type identifier, or None if conversion fails
    """
    import re

    # Handle special cases
    if class_name == "LLMDonorAgent":
        return "llm_donor_agent"
    if class_name == "SocialMediaSpace":
        return "social_media"

    # Convert CamelCase to snake_case
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", class_name)
    snake_case = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # Remove trailing "_agent" or "_env" if present
    if snake_case.endswith("_agent"):
        snake_case = snake_case[:-6] + "_agent"
    elif snake_case.endswith("_environment"):
        snake_case = snake_case[:-12]

    return snake_case


def discover_and_register_builtin_modules(registry: Optional[ModuleRegistry] = None) -> None:
    """Discover and register all built-in modules

    Args:
        registry: The registry to use. If None, uses the global registry.
    """
    if registry is None:
        registry = get_registry()

    # Discover and register environment modules
    env_modules = _discover_contrib_env_modules()
    for module_type, module_class in env_modules.items():
        registry.register_env_module(module_type, module_class, is_custom=False)

    # Discover and register agents
    agents = {}
    agents.update(_discover_contrib_agents())
    agents.update(_discover_builtin_agents())

    for agent_type, agent_class in agents.items():
        registry.register_agent_module(agent_type, agent_class, is_custom=False)

    logger.info(
        f"Registered {len(env_modules)} env modules and {len(agents)} agents "
        f"from built-in modules"
    )


def scan_and_register_custom_modules(
    workspace_path: Path, registry: Optional[ModuleRegistry] = None
) -> Dict[str, Any]:
    """Scan and register custom modules from custom/ directory

    Args:
        workspace_path: Path to the workspace
        registry: The registry to use. If None, uses the global registry.

    Returns:
        Scan result with agents, envs, and errors
    """
    if registry is None:
        registry = get_registry()

    # Clear any previously registered custom modules to avoid accumulation
    # when user changes class names or module structure
    registry.clear_custom_modules()

    registry.set_workspace(workspace_path)

    from agentsociety2.backend.services.custom.scanner import CustomModuleScanner

    scanner = CustomModuleScanner(str(workspace_path))
    scan_result = scanner.scan_all()

    # Register custom environment modules
    for env_info in scan_result.get("envs", []):
        # Import the class
        try:
            spec = __import__("importlib.util").util.spec_from_file_location(
                f"custom_env_{env_info['type']}", env_info["file_path"]
            )
            if spec and spec.loader:
                module = __import__("importlib.util").util.module_from_spec(spec)
                import sys
                sys.modules[f"custom_env_{env_info['type']}"] = module
                spec.loader.exec_module(module)

                # Get the class
                env_class = getattr(module, env_info["class_name"])
                env_class._is_custom = True  # Mark as custom

                # Use class name directly as the key
                module_type = env_info["class_name"]

                registry.register_env_module(module_type, env_class, is_custom=True)
        except Exception as e:
            logger.warning(f"Failed to register custom env module {env_info.get('type')}: {e}")

    # Register custom agents
    for agent_info in scan_result.get("agents", []):
        try:
            spec = __import__("importlib.util").util.spec_from_file_location(
                f"custom_agent_{agent_info['type']}", agent_info["file_path"]
            )
            if spec and spec.loader:
                module = __import__("importlib.util").util.module_from_spec(spec)
                import sys
                sys.modules[f"custom_agent_{agent_info['type']}"] = module
                spec.loader.exec_module(module)

                # Get the class
                agent_class = getattr(module, agent_info["class_name"])
                agent_class._is_custom = True  # Mark as custom

                # Use class name directly as the key
                agent_type = agent_info["class_name"]

                registry.register_agent_module(agent_type, agent_class, is_custom=True)
        except Exception as e:
            logger.warning(f"Failed to register custom agent {agent_info.get('type')}: {e}")

    logger.info(
        f"Registered {len(scan_result.get('envs', []))} custom env modules and "
        f"{len(scan_result.get('agents', []))} custom agents"
    )

    return scan_result


# Convenience functions

def get_registered_env_modules() -> List[Tuple[str, Type[EnvBase]]]:
    """Get all registered environment modules

    Returns:
        List of (module_type, module_class) tuples
    """
    return get_registry().list_env_modules()


def get_registered_agent_modules() -> List[Tuple[str, Type[AgentBase]]]:
    """Get all registered agent modules

    Returns:
        List of (agent_type, agent_class) tuples
    """
    return get_registry().list_agent_modules()


def get_env_module_class(module_type: str) -> Optional[Type[EnvBase]]:
    """Get an environment module class by type

    Args:
        module_type: The type identifier

    Returns:
        The environment module class, or None if not found
    """
    return get_registry().get_env_module(module_type)


def get_agent_module_class(agent_type: str) -> Optional[Type[AgentBase]]:
    """Get an agent module class by type

    Args:
        agent_type: The type identifier

    Returns:
        The agent class, or None if not found
    """
    return get_registry().get_agent_module(agent_type)


def list_all_modules() -> Dict[str, List[Dict[str, Any]]]:
    """List all registered modules with their info

    Returns:
        Dict with 'env_modules' and 'agents' keys
    """
    registry = get_registry()

    env_modules = []
    for module_type, module_class in registry.list_env_modules():
        try:
            description = module_class.mcp_description() if hasattr(module_class, "mcp_description") else module_class.__doc__ or ""
        except Exception:
            description = ""
        env_modules.append({
            "type": module_type,
            "class_name": module_class.__name__,
            "description": description,
            "is_custom": getattr(module_class, "_is_custom", False),
        })

    agents = []
    for agent_type, agent_class in registry.list_agent_modules():
        try:
            description = agent_class.mcp_description() if hasattr(agent_class, "mcp_description") else agent_class.__doc__ or ""
        except Exception:
            description = ""
        agents.append({
            "type": agent_type,
            "class_name": agent_class.__name__,
            "description": description,
            "is_custom": getattr(agent_class, "_is_custom", False),
        })

    return {
        "env_modules": env_modules,
        "agents": agents,
    }


def reload_modules(workspace_path: Optional[Path] = None) -> None:
    """Reload all modules (clear and re-discover)

    Args:
        workspace_path: Optional workspace path for custom modules
    """
    registry = get_registry()

    # Clear registry
    registry._env_modules.clear()
    registry._agent_modules.clear()

    # Reset lazy loading flags
    registry._builtin_loaded = False
    registry._custom_loaded = False

    # Set workspace if provided
    if workspace_path:
        registry.set_workspace(workspace_path)

    logger.info("Module registry cleared (modules will be loaded on demand)")
