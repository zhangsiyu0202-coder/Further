"""仿真路由：多步仿真、单步推进与时间线查询。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from agentsociety2.backend.models import (
    SimulateRequest,
    SimulateResponse,
    StepResponse,
)
from agentsociety2.backend.services.simulation_service import SimulationService

router = APIRouter(prefix="/api/v1/worlds", tags=["simulations"])


def _get_service() -> SimulationService:
    from agentsociety2.backend.app import get_simulation_service
    return get_simulation_service()


@router.post("/{world_id}/simulate", response_model=SimulateResponse)
async def simulate(world_id: str, req: SimulateRequest) -> SimulateResponse:
    """对指定世界执行多步仿真。"""
    service = _get_service()
    try:
        result = await service.simulate(
            world_id=world_id,
            steps=req.steps,
            tick_seconds=req.tick_seconds,
            stop_when_stable=req.stop_when_stable,
        )
        return SimulateResponse(**result)
    except Exception as e:
        return SimulateResponse(success=False, error=str(e))


@router.post("/{world_id}/step", response_model=StepResponse)
async def step(world_id: str, tick_seconds: Optional[int] = Query(default=None)) -> StepResponse:
    """将世界推进一个时间步，适合实时界面刷新。"""
    service = _get_service()
    try:
        result = await service.step_once(world_id=world_id, tick_seconds=tick_seconds)
        return StepResponse(**result)
    except Exception as e:
        return StepResponse(success=False, error=str(e))


@router.get("/{world_id}/timeline", response_model=List[Dict[str, Any]])
async def get_timeline(
    world_id: str,
    limit: int = Query(50, ge=1, le=500),
    after_tick: int = Query(-1),
    event_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """获取世界事件时间线。"""
    service = _get_service()
    return await service.get_timeline(
        world_id=world_id,
        limit=limit,
        after_tick=after_tick,
        event_type=event_type,
    )


@router.get("/{world_id}/agents", response_model=List[Dict[str, Any]])
async def get_agents(world_id: str) -> List[Dict[str, Any]]:
    """获取世界当前智能体视图。"""
    service = _get_service()
    agents = await service.get_agents(world_id)
    if agents is None:
        raise HTTPException(status_code=404, detail=f"未找到世界：{world_id}")
    return agents


@router.get("/{world_id}/simulation/status", response_model=Dict[str, Any])
async def get_simulation_status(world_id: str) -> Dict[str, Any]:
    """获取世界仿真的聚合状态。"""
    service = _get_service()
    status = await service.get_status(world_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"未找到世界：{world_id}")
    return status
