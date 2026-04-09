"""交互路由：世界对话、智能体对话与干预注入。"""

from __future__ import annotations

from fastapi import APIRouter

from agentsociety2.backend.models import (
    ChatAgentRequest,
    ChatAgentResponse,
    ChatWorldRequest,
    ChatWorldResponse,
    InterventionRequest,
    InterventionResponse,
    TimelineInterventionRequest,
    TimelineInterventionResponse,
)
from agentsociety2.backend.services.interaction_service import InteractionService

router = APIRouter(prefix="/api/v1/worlds", tags=["interactions"])


def _get_service() -> InteractionService:
    from agentsociety2.backend.app import get_interaction_service
    return get_interaction_service()


@router.post("/{world_id}/chat", response_model=ChatWorldResponse)
async def chat_with_world(world_id: str, req: ChatWorldRequest) -> ChatWorldResponse:
    """以观察者视角与虚拟世界对话。"""
    service = _get_service()
    result = await service.chat_with_world(world_id=world_id, message=req.message)
    return ChatWorldResponse(**result)


@router.post("/{world_id}/agents/{agent_id}/chat", response_model=ChatAgentResponse)
async def chat_with_agent(
    world_id: str, agent_id: str, req: ChatAgentRequest
) -> ChatAgentResponse:
    """与虚拟世界中的指定智能体对话。"""
    service = _get_service()
    result = await service.chat_with_agent(
        world_id=world_id, agent_id=agent_id, message=req.message
    )
    return ChatAgentResponse(**result)


@router.post("/{world_id}/interventions", response_model=InterventionResponse)
async def apply_intervention(
    world_id: str, req: InterventionRequest
) -> InterventionResponse:
    """向仿真中注入外部干预。"""
    service = _get_service()
    result = await service.apply_intervention(
        world_id=world_id,
        intervention_type=req.intervention_type,
        payload=req.payload,
        reason=req.reason,
    )
    return InterventionResponse(**result)


@router.post(
    "/{world_id}/timeline/interventions",
    response_model=TimelineInterventionResponse,
)
async def branch_from_timeline_intervention(
    world_id: str,
    req: TimelineInterventionRequest,
) -> TimelineInterventionResponse:
    """在历史时间链节点上插入自然语言干预，并从该节点派生新的推演分支。"""
    service = _get_service()
    result = await service.branch_from_timeline_intervention(
        world_id=world_id,
        anchor_tick=req.anchor_tick,
        command=req.command,
        continuation_steps=req.continuation_steps,
        tick_seconds=req.tick_seconds,
        branch_name=req.branch_name,
    )
    return TimelineInterventionResponse(**result)
