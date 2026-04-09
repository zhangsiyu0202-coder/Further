"""
World Package: Core LLM-driven virtual world engine.

Expose world models and services lazily so backend startup only loads the
specific world components it needs.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "SeedMaterial",
    "ExtractedFact",
    "Entity",
    "Relation",
    "Persona",
    "AgentState",
    "WorldEvent",
    "GlobalVariable",
    "WorldState",
    "SimulationRun",
    "Intervention",
    "Report",
    "SeedIngest",
    "WorldExtractor",
    "ExtractionResult",
    "ActorSelector",
    "PersonaBuilder",
    "SimulationInitBuilder",
    "GraphBuilder",
    "WorldStateManager",
    "SimulationEngine",
    "WorldInteraction",
    "WorldRepository",
    "ReportAgent",
]

_LAZY_IMPORTS = {
    "SeedMaterial": ("agentsociety2.world.models", "SeedMaterial"),
    "ExtractedFact": ("agentsociety2.world.models", "ExtractedFact"),
    "Entity": ("agentsociety2.world.models", "Entity"),
    "Relation": ("agentsociety2.world.models", "Relation"),
    "Persona": ("agentsociety2.world.models", "Persona"),
    "AgentState": ("agentsociety2.world.models", "AgentState"),
    "WorldEvent": ("agentsociety2.world.models", "WorldEvent"),
    "GlobalVariable": ("agentsociety2.world.models", "GlobalVariable"),
    "WorldState": ("agentsociety2.world.models", "WorldState"),
    "SimulationRun": ("agentsociety2.world.models", "SimulationRun"),
    "Intervention": ("agentsociety2.world.models", "Intervention"),
    "Report": ("agentsociety2.world.models", "Report"),
    "SeedIngest": ("agentsociety2.world.seed_ingest", "SeedIngest"),
    "WorldExtractor": ("agentsociety2.world.extraction", "WorldExtractor"),
    "ExtractionResult": ("agentsociety2.world.extraction", "ExtractionResult"),
    "ActorSelector": ("agentsociety2.world.actor_selector", "ActorSelector"),
    "PersonaBuilder": ("agentsociety2.world.persona_builder", "PersonaBuilder"),
    "SimulationInitBuilder": ("agentsociety2.world.simulation_init_builder", "SimulationInitBuilder"),
    "GraphBuilder": ("agentsociety2.world.graph_builder", "GraphBuilder"),
    "WorldStateManager": ("agentsociety2.world.world_state", "WorldStateManager"),
    "SimulationEngine": ("agentsociety2.world.simulation_engine", "SimulationEngine"),
    "WorldInteraction": ("agentsociety2.world.interaction", "WorldInteraction"),
    "WorldRepository": ("agentsociety2.world.repository", "WorldRepository"),
    "ReportAgent": ("agentsociety2.world.report_agent", "ReportAgent"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module 'agentsociety2.world' has no attribute {name!r}")

    module_name, attr_name = _LAZY_IMPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
