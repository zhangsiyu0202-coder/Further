from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "get_available_models",
    "Config",
    "get_llm_router",
    "get_llm_router_and_model",
    "get_model_name",
    "extract_json",
]

_LAZY_IMPORTS = {
    "get_available_models": ("agentsociety2.config.list_models", "get_available_models"),
    "Config": ("agentsociety2.config.config", "Config"),
    "get_llm_router": ("agentsociety2.config.config", "get_llm_router"),
    "get_llm_router_and_model": ("agentsociety2.config.config", "get_llm_router_and_model"),
    "get_model_name": ("agentsociety2.config.config", "get_model_name"),
    "extract_json": ("agentsociety2.config.config", "extract_json"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module 'agentsociety2.config' has no attribute {name!r}")

    module_name, attr_name = _LAZY_IMPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
