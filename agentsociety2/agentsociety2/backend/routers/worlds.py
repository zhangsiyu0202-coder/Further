"""世界路由：构建、查询元数据与快照。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from agentsociety2.backend.models import (
    BuildWorldRequest,
    BuildWorldResponse,
    BuildWorldTaskResponse,
    TaskStatusResponse,
)
from agentsociety2.backend.services.world_builder_service import WorldBuilderService

router = APIRouter(prefix="/api/v1/worlds", tags=["worlds"])


def _get_service() -> WorldBuilderService:
    from agentsociety2.backend.app import get_world_builder_service
    return get_world_builder_service()


@router.post("/build", response_model=BuildWorldTaskResponse)
async def build_world(req: BuildWorldRequest) -> BuildWorldTaskResponse:
    """根据种子材料异步构建新的虚拟世界。"""
    service = _get_service()
    seed_dicts = [m.model_dump() for m in req.seed_materials]
    try:
        result = await service.start_build_task(
            seed_materials=seed_dicts,
            world_name=req.name,
            world_goal=req.world_goal,
            simulation_goal=req.simulation_goal,
            constraints=req.constraints or None,
        )
        return BuildWorldTaskResponse(success=True, **result)
    except Exception as e:
        return BuildWorldTaskResponse(success=False, error=str(e))


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_build_task_status(task_id: str) -> TaskStatusResponse:
    """查询世界构建任务状态。"""
    service = _get_service()
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"未找到任务：{task_id}")
    return TaskStatusResponse(
        success=True,
        task_id=task["task_id"],
        world_id=task.get("world_id"),
        type=task.get("type") or "world_build",
        status=task.get("status") or "pending",
        progress=int(task.get("progress") or 0),
        message=task.get("message") or "",
        result=task.get("result"),
        error=task.get("error"),
    )


@router.get("", response_model=List[Dict[str, Any]])
async def list_worlds() -> List[Dict[str, Any]]:
    """列出所有已创建的世界。"""
    service = _get_service()
    return await service.list_worlds()


@router.get("/{world_id}", response_model=Dict[str, Any])
async def get_world(world_id: str) -> Dict[str, Any]:
    """获取世界元数据。"""
    service = _get_service()
    meta = await service.get_world(world_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"未找到世界：{world_id}")
    return meta


@router.get("/{world_id}/status", response_model=Dict[str, Any])
async def get_world_status(world_id: str) -> Dict[str, Any]:
    """获取世界与图谱的聚合状态。"""
    service = _get_service()
    status = await service.get_status(world_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"未找到世界：{world_id}")
    return status


@router.get("/{world_id}/snapshot", response_model=Dict[str, Any])
async def get_snapshot(
    world_id: str,
    snapshot_version: Optional[int] = Query(default=None, ge=0),
    tick: Optional[int] = Query(default=None, ge=0),
) -> Dict[str, Any]:
    """获取完整世界快照，包括实体、关系、人格等信息。"""
    service = _get_service()
    snapshot = await service.get_snapshot(
        world_id,
        snapshot_version=snapshot_version,
        tick=tick,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"未找到该世界的快照：{world_id}")
    return snapshot
