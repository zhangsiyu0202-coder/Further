"""
World Models: Core Pydantic data models for the LLM-driven virtual world engine.

职责：
- 定义世界所有核心数据结构
- SeedMaterial, ExtractedFact, Entity, Relation, Persona, AgentState,
  WorldEvent, GlobalVariable, WorldState, SimulationRun, Intervention, Report
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

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
]


def _new_id(prefix: str = "") -> str:
    short = str(uuid.uuid4()).replace("-", "")[:12]
    return f"{prefix}{short}" if prefix else short


# ---------------------------------------------------------------------------
# Input / Ingestion
# ---------------------------------------------------------------------------


class SeedMaterial(BaseModel):
    """Raw input material provided by the user to seed the world."""

    id: str = Field(default_factory=lambda: _new_id("seed_"))
    kind: Literal["text", "document", "summary", "structured"] = "text"
    title: str = ""
    content: str
    source: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


class ExtractedFact(BaseModel):
    """
    Auditable intermediate unit produced by the LLM extraction pipeline.
    Tracks which seed material each world element came from.
    """

    id: str = Field(default_factory=lambda: _new_id("fact_"))
    fact_type: Literal[
        "entity", "relation", "event", "constraint", "goal", "stance"
    ]
    content: str
    confidence: float = 1.0
    source_material_id: str
    source_span: Optional[str] = None


# ---------------------------------------------------------------------------
# World Graph Elements
# ---------------------------------------------------------------------------


class Entity(BaseModel):
    """A node in the world graph: person, org, group, media, etc."""

    id: str = Field(default_factory=lambda: _new_id("ent_"))
    name: str
    entity_type: Literal[
        "person", "organization", "group", "media", "location", "concept", "other"
    ] = "other"
    aliases: List[str] = Field(default_factory=list)
    description: str = ""
    attributes: Dict[str, Any] = Field(default_factory=dict)


class Relation(BaseModel):
    """A directed edge in the world graph between two entities."""

    id: str = Field(default_factory=lambda: _new_id("rel_"))
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    strength: float = 0.5  # [0, 1]
    polarity: Literal["positive", "neutral", "negative"] = "neutral"
    description: str = ""
    mutable: bool = True  # can be changed by simulation
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Persona(BaseModel):
    """
    A rich persona for a world entity that can be used to drive a WorldSimAgent.
    """

    entity_id: str
    identity_summary: str
    goals: List[str] = Field(default_factory=list)
    fears: List[str] = Field(default_factory=list)
    preferences: List[str] = Field(default_factory=list)
    stance_map: Dict[str, Any] = Field(default_factory=dict)
    behavior_style: str = ""
    speech_style: str = ""
    memory_seeds: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dynamic State
# ---------------------------------------------------------------------------


class AgentState(BaseModel):
    """Runtime state of an active agent in the simulation."""

    entity_id: str
    current_goal: Optional[str] = None
    beliefs: Dict[str, Any] = Field(default_factory=dict)
    emotions: Dict[str, float] = Field(default_factory=dict)
    resources: Dict[str, Any] = Field(default_factory=dict)
    alliances: List[str] = Field(default_factory=list)  # entity_ids
    recent_memories: List[str] = Field(default_factory=list)
    status: str = "active"  # active / inactive / eliminated


class WorldEvent(BaseModel):
    """An event that occurs in the simulation timeline."""

    id: str = Field(default_factory=lambda: _new_id("evt_"))
    tick: int
    event_type: str
    title: str
    description: str
    participants: List[str] = Field(default_factory=list)  # entity_ids
    payload: Dict[str, Any] = Field(default_factory=dict)
    parent_event_id: Optional[str] = None
    source_entity_id: Optional[str] = None
    source_module: Optional[str] = None
    trigger_reason: str = ""
    created_by: Literal["seed", "agent", "system", "intervention"] = "system"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GlobalVariable(BaseModel):
    """A scalar global variable tracked across the simulation."""

    name: str
    value: Any
    description: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# World State
# ---------------------------------------------------------------------------


class WorldState(BaseModel):
    """Complete snapshot of the virtual world at a given point in time."""

    world_id: str
    name: str
    entities: List[Entity] = Field(default_factory=list)
    relations: List[Relation] = Field(default_factory=list)
    actor_entity_ids: List[str] = Field(default_factory=list)
    personas: List[Persona] = Field(default_factory=list)
    agent_states: List[AgentState] = Field(default_factory=list)
    global_variables: List[GlobalVariable] = Field(default_factory=list)
    timeline: List[WorldEvent] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    build_summary: str = ""
    current_tick: int = 0
    snapshot_version: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


class SimulationRun(BaseModel):
    """Metadata for a single simulation run."""

    run_id: str = Field(default_factory=lambda: _new_id("run_"))
    world_id: str
    start_tick: int = 0
    end_tick: Optional[int] = None
    steps_requested: int = 0
    steps_executed: int = 0
    tick_seconds: int = 300
    mode: Literal["sequential", "batch"] = "sequential"
    status: Literal["running", "completed", "failed", "stopped"] = "running"
    new_event_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Intervention
# ---------------------------------------------------------------------------


class Intervention(BaseModel):
    """An external intervention injected into the simulation."""

    intervention_id: str = Field(default_factory=lambda: _new_id("int_"))
    world_id: str
    intervention_type: str  # policy_shock, opinion_shift, resource_change, etc.
    payload: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    applied_at_tick: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class Report(BaseModel):
    """A generated report for a world simulation."""

    report_id: str = Field(default_factory=lambda: _new_id("rep_"))
    world_id: str
    report_type: str  # summary / prediction / analysis / retrospective
    focus: str = ""
    content: str
    sources: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
