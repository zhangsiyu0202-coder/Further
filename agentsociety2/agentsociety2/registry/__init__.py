"""AgentSociety2 Module Registry

Centralized registry for agent classes and environment modules.
Supports both built-in modules (from contrib) and custom modules (from custom/ directory).

Implements lazy loading - modules are only discovered when first accessed.
Use load_all_modules() to eagerly load all modules if needed.
"""

from agentsociety2.registry.base import ModuleRegistry, get_registry
from agentsociety2.registry.modules import (
    get_registered_env_modules,
    get_registered_agent_modules,
    get_env_module_class,
    get_agent_module_class,
    list_all_modules,
    reload_modules,
    scan_and_register_custom_modules,
    discover_and_register_builtin_modules,
)
from agentsociety2.registry.models import (
    EnvModuleInitConfig,
    AgentInitConfig,
    CreateInstanceRequest,
    AskRequest,
    InterventionRequest,
)

__all__ = [
    # Registry
    "ModuleRegistry",
    "get_registry",
    "get_registered_env_modules",
    "get_registered_agent_modules",
    "get_env_module_class",
    "get_agent_module_class",
    "list_all_modules",
    "reload_modules",
    "scan_and_register_custom_modules",
    "discover_and_register_builtin_modules",
    # Models
    "EnvModuleInitConfig",
    "AgentInitConfig",
    "CreateInstanceRequest",
    "AskRequest",
    "InterventionRequest",
]
