from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["AgentBase", "DIALOG_TYPE_REFLECTION", "PersonAgent", "WorldSimAgent"]

_LAZY_IMPORTS = {
    "AgentBase": ("agentsociety2.agent.base", "AgentBase"),
    "DIALOG_TYPE_REFLECTION": ("agentsociety2.agent.base", "DIALOG_TYPE_REFLECTION"),
    "PersonAgent": ("agentsociety2.agent.person", "PersonAgent"),
    "WorldSimAgent": ("agentsociety2.agent.world_sim_agent", "WorldSimAgent"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module 'agentsociety2.agent' has no attribute {name!r}")

    module_name, attr_name = _LAZY_IMPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
