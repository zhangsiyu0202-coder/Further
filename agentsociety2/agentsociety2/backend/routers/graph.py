"""图谱路由：构建、查询与搜索知识图谱。"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agentsociety2.backend.services.graph_service import GraphService

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class BuildGraphRequest(BaseModel):
    world_id: str
    chunking_strategy: str = Field(
        default="by_title",
        description="分块策略：basic | by_title | simple",
    )
    max_chunk_size: int = Field(default=1000, ge=200, le=8000)


class BuildGraphResponse(BaseModel):
    success: bool
    task_id: Optional[str] = None
    error: Optional[str] = None


class TaskStatusResponse(BaseModel):
    task_id: str
    world_id: str
    status: str
    progress: int
    message: str
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str


class GraphSnapshotResponse(BaseModel):
    nodes: List[dict]
    edges: List[dict]


class SearchRequest(BaseModel):
    query: str
    entity_types: Optional[List[str]] = None
    relation_types: Optional[List[str]] = None
    limit: int = Field(default=10, ge=1, le=50)


class SearchResponse(BaseModel):
    success: bool
    results: List[dict] = Field(default_factory=list)
    error: Optional[str] = None


class EntitiesResponse(BaseModel):
    success: bool
    entities: List[dict] = Field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/build", response_model=BuildGraphResponse)
async def build_graph(req: BuildGraphRequest):
    """从世界结构化事实启动后台知识图谱构建任务。"""
    try:
        from agentsociety2.backend.app import get_world_builder_service
        world_service = get_world_builder_service()
        if world_service is None:
            raise HTTPException(status_code=503, detail="世界服务尚未初始化")
        world_state = world_service._repo.load_world_state(req.world_id)
        if world_state is None:
            raise HTTPException(status_code=404, detail=f"未找到世界：{req.world_id}")

        task_id = await GraphService.start_build(
            world_id=req.world_id,
            fact_seed_text=GraphService.build_fact_seed_text(world_state),
            chunking_strategy=req.chunking_strategy,
            max_chunk_size=req.max_chunk_size,
        )
        return BuildGraphResponse(success=True, task_id=task_id)
    except HTTPException:
        raise
    except Exception as exc:
        return BuildGraphResponse(success=False, error=str(exc))


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """根据任务 ID 查询构图进度。"""
    task = GraphService.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"未找到任务：{task_id}")
    return TaskStatusResponse(**task)


@router.get("/tasks", response_model=List[TaskStatusResponse])
async def list_tasks(world_id: Optional[str] = Query(default=None)):
    """列出所有图谱构建任务，可按 world_id 过滤。"""
    tasks = GraphService.list_tasks(world_id=world_id)
    return [TaskStatusResponse(**t) for t in tasks]


@router.get("/{world_id}/snapshot", response_model=GraphSnapshotResponse)
async def get_graph_snapshot(
    world_id: str,
    entity_types: Optional[str] = Query(
        default=None,
        description="按逗号分隔的实体类型过滤，例如 person,organization",
    ),
    relation_types: Optional[str] = Query(
        default=None,
        description="按逗号分隔的关系类型过滤",
    ),
):
    """返回世界知识图谱的节点与边数据。"""
    et = [t.strip() for t in entity_types.split(",")] if entity_types else None
    rt = [t.strip() for t in relation_types.split(",")] if relation_types else None
    snapshot = await GraphService.get_snapshot(
        world_id=world_id,
        entity_types=et,
        relation_types=rt,
    )
    return GraphSnapshotResponse(**snapshot)


@router.post("/{world_id}/search", response_model=SearchResponse)
async def search_memory(world_id: str, req: SearchRequest):
    """通过 Graphiti 对世界知识图谱执行语义搜索。"""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")
    try:
        results = await GraphService.search_memory(
            world_id=world_id,
            query=req.query,
            entity_types=req.entity_types,
            relation_types=req.relation_types,
            limit=req.limit,
        )
        return SearchResponse(success=True, results=results)
    except Exception as exc:
        return SearchResponse(success=False, error=str(exc))


@router.get("/{world_id}/entities", response_model=EntitiesResponse)
async def get_entities(
    world_id: str,
    entity_types: Optional[str] = Query(
        default=None,
        description="按逗号分隔的实体类型过滤",
    ),
    limit: int = Query(default=20, ge=1, le=100),
):
    """列出世界知识图谱中的实体及其关联关系。"""
    et = [t.strip() for t in entity_types.split(",")] if entity_types else None
    try:
        entities = await GraphService.get_entities(
            world_id=world_id,
            entity_types=et,
            limit=limit,
        )
        return EntitiesResponse(success=True, entities=entities)
    except Exception as exc:
        return EntitiesResponse(success=False, error=str(exc))
