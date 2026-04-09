"""世界仿真后端接口的 Pydantic 请求与响应模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

__all__ = [
    "BuildWorldRequest",
    "BuildWorldResponse",
    "BuildWorldTaskResponse",
    "TaskStatusResponse",
    "SimulateRequest",
    "SimulateResponse",
    "StepResponse",
    "InterventionRequest",
    "InterventionResponse",
    "TimelineInterventionRequest",
    "TimelineInterventionResponse",
    "ChatWorldRequest",
    "ChatWorldResponse",
    "ChatAgentRequest",
    "ChatAgentResponse",
    "ReportRequest",
    "ReportResponse",
    "SeedMaterialIn",
]


class SeedMaterialIn(BaseModel):
    """用于构建世界的输入种子材料。"""
    id: Optional[str] = None
    kind: Literal["text", "document", "summary", "structured"] = "text"
    title: str = ""
    content: str
    source: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# World Building
# ---------------------------------------------------------------------------

class BuildWorldRequest(BaseModel):
    name: str = "未命名世界"
    seed_materials: List[SeedMaterialIn]
    world_goal: str = ""
    simulation_goal: str = ""
    constraints: List[str] = Field(default_factory=list)


class BuildWorldResponse(BaseModel):
    success: bool
    world_id: Optional[str] = None
    build_summary: Optional[str] = None
    entity_count: Optional[int] = None
    relation_count: Optional[int] = None
    agent_count: Optional[int] = None
    snapshot: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BuildWorldTaskResponse(BaseModel):
    success: bool
    task_id: Optional[str] = None
    status: Optional[str] = None
    world_id: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class TaskStatusResponse(BaseModel):
    success: bool
    task_id: str
    world_id: Optional[str] = None
    type: str
    status: str
    progress: int
    message: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

class SimulateRequest(BaseModel):
    steps: int = 5
    tick_seconds: Optional[int] = None
    stop_when_stable: bool = False


class SimulateResponse(BaseModel):
    success: bool
    run_id: Optional[str] = None
    world_id: Optional[str] = None
    executed_steps: Optional[int] = None
    new_event_count: Optional[int] = None
    updated_snapshot: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class StepResponse(BaseModel):
    success: bool
    world_id: Optional[str] = None
    tick: Optional[int] = None
    new_events: Optional[int] = None
    active_agents: Optional[int] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Intervention
# ---------------------------------------------------------------------------

class InterventionRequest(BaseModel):
    intervention_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class InterventionResponse(BaseModel):
    success: bool
    intervention_id: Optional[str] = None
    tick: Optional[int] = None
    error: Optional[str] = None


class TimelineInterventionRequest(BaseModel):
    anchor_tick: int = Field(ge=0)
    command: str = Field(min_length=1)
    continuation_steps: int = Field(default=5, ge=0, le=200)
    tick_seconds: Optional[int] = Field(default=None, ge=1)
    branch_name: str = ""


class TimelineInterventionResponse(BaseModel):
    success: bool
    world_id: Optional[str] = None
    source_world_id: Optional[str] = None
    source_tick: Optional[int] = None
    intervention_id: Optional[str] = None
    graph_task_id: Optional[str] = None
    graph_status: Optional[str] = None
    updated_snapshot: Optional[Dict[str, Any]] = None
    timeline: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatWorldRequest(BaseModel):
    message: str


class ChatWorldResponse(BaseModel):
    success: bool
    answer: Optional[str] = None
    sources: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class ChatAgentRequest(BaseModel):
    message: str


class ChatAgentResponse(BaseModel):
    success: bool
    agent_id: Optional[str] = None
    answer: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class ReportRequest(BaseModel):
    report_type: Literal["summary", "prediction", "analysis", "retrospective"] = "summary"
    focus: str = ""


class ReportResponse(BaseModel):
    success: bool
    report_id: Optional[str] = None
    world_id: Optional[str] = None
    report_type: Optional[str] = None
    focus: Optional[str] = None
    content: Optional[str] = None
    created_at: Optional[str] = None
    error: Optional[str] = None
