"""
AgentSociety 2 package entrypoint.

Keep package import lightweight so backend-only usage does not pull optional
runtime dependencies like mem0 during module discovery.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import version, PackageNotFoundError
from typing import Any

try:
    __version__ = version("agentsociety2")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = [
    "AgentBase",
    "PersonAgent",
    "WorldSimAgent",
    "EnvBase",
    "RouterBase",
    "WorldRouter",
    "ReActRouter",
    "PlanExecuteRouter",
    "TwoTierReActRouter",
    "TwoTierPlanExecuteRouter",
    "SearchToolRouter",
    "tool",
    "AgentSocietyHelper",
    "ReplayWriter",
]

_LAZY_IMPORTS = {
    "AgentBase": ("agentsociety2.agent", "AgentBase"),
    "PersonAgent": ("agentsociety2.agent", "PersonAgent"),
    "WorldSimAgent": ("agentsociety2.agent.world_sim_agent", "WorldSimAgent"),
    "EnvBase": ("agentsociety2.env", "EnvBase"),
    "RouterBase": ("agentsociety2.env", "RouterBase"),
    "WorldRouter": ("agentsociety2.env", "WorldRouter"),
    "ReActRouter": ("agentsociety2.env", "ReActRouter"),
    "PlanExecuteRouter": ("agentsociety2.env", "PlanExecuteRouter"),
    "TwoTierReActRouter": ("agentsociety2.env", "TwoTierReActRouter"),
    "TwoTierPlanExecuteRouter": ("agentsociety2.env", "TwoTierPlanExecuteRouter"),
    "SearchToolRouter": ("agentsociety2.env", "SearchToolRouter"),
    "tool": ("agentsociety2.env", "tool"),
    "AgentSocietyHelper": ("agentsociety2.society", "AgentSocietyHelper"),
    "ReplayWriter": ("agentsociety2.storage", "ReplayWriter"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module 'agentsociety2' has no attribute {name!r}")

    module_name, attr_name = _LAZY_IMPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
