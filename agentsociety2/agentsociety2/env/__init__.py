from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "EnvBase",
    "RouterBase",
    "WorldRouter",
    "ReActRouter",
    "PlanExecuteRouter",
    "TwoTierReActRouter",
    "TwoTierPlanExecuteRouter",
    "SearchToolRouter",
    "tool",
    "EnvRouterBenchmarkData",
]

_LAZY_IMPORTS = {
    "EnvBase": ("agentsociety2.env.base", "EnvBase"),
    "tool": ("agentsociety2.env.base", "tool"),
    "RouterBase": ("agentsociety2.env.router_base", "RouterBase"),
    "ReActRouter": ("agentsociety2.env.router_react", "ReActRouter"),
    "PlanExecuteRouter": ("agentsociety2.env.router_plan_execute", "PlanExecuteRouter"),
    "TwoTierReActRouter": ("agentsociety2.env.router_two_tier_react", "TwoTierReActRouter"),
    "TwoTierPlanExecuteRouter": (
        "agentsociety2.env.router_two_tier_plan_execute",
        "TwoTierPlanExecuteRouter",
    ),
    "SearchToolRouter": ("agentsociety2.env.router_search_tool", "SearchToolRouter"),
    "WorldRouter": ("agentsociety2.env.router_world", "WorldRouter"),
    "EnvRouterBenchmarkData": ("agentsociety2.env.benchmark", "EnvRouterBenchmarkData"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module 'agentsociety2.env' has no attribute {name!r}")

    module_name, attr_name = _LAZY_IMPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
