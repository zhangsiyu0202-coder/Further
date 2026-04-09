"""
WorldBuilderService：负责从种子材料编排世界构建流程。

职责：
- 接收 seed_materials + world_goal + constraints
- 运行 seed ingest → extraction → persona build → graph build → world state
- 持久化 world
- 返回 world_id + build summary + snapshot
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from agentsociety2.backend.services.graph_service import GraphService
from agentsociety2.logger import get_logger
from agentsociety2.world import (
    ActorSelector,
    Entity,
    ExtractionResult,
    GlobalVariable,
    GraphBuilder,
    Persona,
    PersonaBuilder,
    Relation,
    Report,
    SeedIngest,
    SeedMaterial,
    SimulationInitBuilder,
    SimulationRun,
    WorldEvent,
    WorldExtractor,
    WorldRepository,
    WorldState,
    WorldStateManager,
)

__all__ = ["WorldBuilderService"]

_logger = get_logger()
_tasks: dict[str, dict[str, Any]] = {}


def _task_update(task_id: str, **kwargs: Any) -> None:
    if task_id in _tasks:
        _tasks[task_id].update(kwargs)


class WorldBuilderService:
    """
    从种子材料构建虚拟世界的服务层。

    用法：
        service = WorldBuilderService(repository)
        result = await service.build_world(seed_materials, world_name, world_goal)
    """

    def __init__(self, repository: WorldRepository):
        self._repo = repository
        self._ingest = SeedIngest()
        self._extractor = WorldExtractor()
        self._actor_selector = ActorSelector()
        self._persona_builder = PersonaBuilder()
        self._graph_builder = GraphBuilder()
        self._simulation_init_builder = SimulationInitBuilder()

    async def start_build_task(
        self,
        seed_materials: List[Any],
        world_name: str = "未命名世界",
        world_goal: str = "",
        simulation_goal: str = "",
        constraints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        world_id = f"world_{str(uuid.uuid4()).replace('-', '')[:12]}"
        _tasks[task_id] = {
            "task_id": task_id,
            "world_id": world_id,
            "type": "world_build",
            "status": "pending",
            "progress": 0,
            "message": "已加入世界构建队列",
            "result": None,
            "error": None,
            "created_at": datetime.utcnow().isoformat(),
        }
        asyncio.create_task(
            self._run_build_task(
                task_id=task_id,
                world_id=world_id,
                seed_materials=seed_materials,
                world_name=world_name,
                world_goal=world_goal,
                simulation_goal=simulation_goal,
                constraints=constraints,
            )
        )
        return {
            "task_id": task_id,
            "world_id": world_id,
            "status": "pending",
            "message": "世界构建任务已提交",
        }

    async def _run_build_task(
        self,
        task_id: str,
        world_id: str,
        seed_materials: List[Any],
        world_name: str,
        world_goal: str,
        simulation_goal: str,
        constraints: Optional[List[str]],
    ) -> None:
        try:
            result = await self.build_world(
                seed_materials=seed_materials,
                world_name=world_name,
                world_goal=world_goal,
                simulation_goal=simulation_goal,
                constraints=constraints,
                world_id=world_id,
                progress_cb=lambda pct, msg: _task_update(
                    task_id,
                    status="processing",
                    progress=pct,
                    message=msg,
                ),
            )
            _task_update(
                task_id,
                status="completed",
                progress=100,
                message="世界构建完成",
                result=result,
            )
        except Exception as exc:
            _logger.exception("世界构建任务失败：%s", world_id)
            _task_update(
                task_id,
                status="failed",
                message=f"世界构建失败：{exc}",
                error=str(exc),
            )

    async def build_world(
        self,
        seed_materials: List[Any],  # list of SeedMaterial | dict | str
        world_name: str = "未命名世界",
        world_goal: str = "",
        simulation_goal: str = "",
        constraints: Optional[List[str]] = None,
        world_id: Optional[str] = None,
        progress_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        根据种子材料构建新的世界。

        返回：
            {
                world_id, build_summary, entity_count, relation_count,
                agent_count, snapshot
            }
        """
        wid = world_id or f"world_{str(uuid.uuid4()).replace('-', '')[:12]}"
        _logger.info(f"世界构建服务：开始构建世界 '{world_name}'（{wid}）")
        if progress_cb:
            progress_cb(5, "正在接收种子材料")

        # 1. Ingest
        materials = self._ingest.ingest(seed_materials)
        _logger.info(f"世界构建服务：已接收 {len(materials)} 份种子材料")
        if progress_cb:
            progress_cb(15, f"已接收 {len(materials)} 份种子材料")

        # 2. Extract
        extraction = await self._extractor.extract(
            seed_materials=materials,
            world_goal=world_goal,
            constraints=constraints,
        )
        _logger.info(
            f"世界构建服务：已抽取 {len(extraction.entities)} 个实体，"
            f"{len(extraction.relations)} 条关系"
        )
        if progress_cb:
            progress_cb(
                40,
                f"已抽取 {len(extraction.entities)} 个实体，{len(extraction.relations)} 条关系",
            )

        # 3. Select actor entities
        actor_entity_ids = self._actor_selector.select(
            entities=extraction.entities,
            relations=extraction.relations,
        )
        if progress_cb:
            progress_cb(50, f"已识别 {len(actor_entity_ids)} 个可行动主体")

        # 4. Build personas from actor entities only
        personas = await self._persona_builder.build_all(
            entities=extraction.entities,
            relations=extraction.relations,
            world_context=extraction.build_summary,
            target_entity_ids=actor_entity_ids,
        )
        if progress_cb:
            progress_cb(60, f"已生成人格画像，共 {len(personas)} 个智能体")

        # 5. Assemble world state
        world_state = await self._graph_builder.build(
            world_id=wid,
            world_name=world_name,
            extraction=extraction,
            actor_entity_ids=actor_entity_ids,
            personas=personas,
            assumptions=constraints,
        )
        if progress_cb:
            progress_cb(80, "世界结构已生成，正在初始化仿真环境")

        world_state = await self._simulation_init_builder.apply(
            world_state=world_state,
            simulation_goal=simulation_goal,
            seed_materials=materials,
        )

        capability_globals = {g.name: g for g in world_state.global_variables}
        if "capability_modules" not in capability_globals:
            world_state.global_variables.append(
                GlobalVariable(
                    name="capability_modules",
                    value={
                        "observation": True,
                        "relation": True,
                        "communication": True,
                        "timeline": True,
                        "social_propagation": True,
                        "global_information": False,
                    },
                    description="Runtime capability modules enabled for this world.",
                )
            )
        if "agent_tool_modules" not in capability_globals:
            world_state.global_variables.append(
                GlobalVariable(
                    name="agent_tool_modules",
                    value={
                        "observation": True,
                        "relation": True,
                        "communication": True,
                        "timeline": True,
                        "social_propagation": True,
                        "global_information": False,
                    },
                    description="Agent-side runtime tools enabled for this world.",
                )
            )
        if "user_tool_modules" not in capability_globals:
            world_state.global_variables.append(
                GlobalVariable(
                    name="user_tool_modules",
                    value={
                        "intervention": True,
                        "report": True,
                    },
                    description="User/operator-side tools enabled for this world.",
                )
            )

        # 6. Persist
        await self._repo.save_world_state(world_state)
        await self._repo.save_snapshot(world_state)
        if progress_cb:
            progress_cb(95, "正在持久化世界状态")

        graph_task_id = None
        try:
            graph_task_id = await GraphService.start_build(
                world_id=wid,
                fact_seed_text=GraphService.build_fact_seed_text(world_state),
            )
        except Exception as exc:
            _logger.warning("世界 %s 自动启动图谱构建失败：%s", wid, exc)

        return {
            "world_id": wid,
            "build_summary": world_state.build_summary,
            "entity_count": len(world_state.entities),
            "relation_count": len(world_state.relations),
            "actor_count": len(world_state.actor_entity_ids),
            "agent_count": len(world_state.personas),
            "graph_task_id": graph_task_id,
            "snapshot": world_state.model_dump(mode="json"),
        }

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return _tasks.get(task_id)

    async def get_world(self, world_id: str) -> Optional[Dict[str, Any]]:
        """获取世界元数据。"""
        meta = await self._repo.get_world_meta(world_id)
        return meta

    async def list_worlds(self) -> List[Dict[str, Any]]:
        """列出所有世界。"""
        return await self._repo.list_worlds()

    async def get_snapshot(
        self,
        world_id: str,
        snapshot_version: Optional[int] = None,
        tick: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取完整世界快照。"""
        world_state = await self._repo.load_world_state(
            world_id,
            snapshot_version=snapshot_version,
            tick=tick,
        )
        if world_state is None:
            return None
        return world_state.model_dump(mode="json")

    async def get_status(self, world_id: str) -> Optional[Dict[str, Any]]:
        """Return authoritative world and graph status for frontend orchestration."""
        meta = await self._repo.get_world_meta(world_id)
        world_state = await self._repo.load_world_state(world_id)
        if meta is None or world_state is None:
            return None

        latest_task = next(iter(GraphService.list_tasks(world_id=world_id)), None)
        node_count = 0
        edge_count = 0
        graph_status = "idle"
        graph_task_id = None
        graph_progress = 0
        graph_message = ""
        graph_error = None

        if latest_task:
            graph_task_id = latest_task.get("task_id")
            graph_status = latest_task.get("status") or "pending"
            graph_progress = int(latest_task.get("progress") or 0)
            graph_message = latest_task.get("message") or ""
            graph_error = latest_task.get("error")
            result = latest_task.get("result") or {}
            if isinstance(result, dict):
                nodes = result.get("nodes") if isinstance(result.get("nodes"), list) else []
                edges = result.get("edges") if isinstance(result.get("edges"), list) else []
                node_count = len(nodes)
                edge_count = len(edges)

        if not latest_task or graph_status == "completed":
            snapshot = await GraphService.get_snapshot(world_id=world_id)
            node_count = len(snapshot.get("nodes") or [])
            edge_count = len(snapshot.get("edges") or [])
            if node_count or edge_count:
                graph_status = "completed"

        if graph_status == "completed":
            world_status = "graph_ready"
        elif graph_status in {"processing", "pending"}:
            world_status = "graph_processing"
        elif meta.get("current_tick", 0) > 0:
            world_status = "world_ready"
        else:
            world_status = "world_ready"

        return {
            "world_id": world_id,
            "world_status": world_status,
            "current_tick": world_state.current_tick,
            "entity_count": len(world_state.entities),
            "relation_count": len(world_state.relations),
            "actor_count": len(world_state.actor_entity_ids),
            "agent_count": len(world_state.personas),
            "graph_status": graph_status,
            "graph_task_id": graph_task_id,
            "graph_progress": graph_progress,
            "graph_message": graph_message,
            "graph_node_count": node_count,
            "graph_edge_count": edge_count,
            "graph_error": graph_error,
        }
