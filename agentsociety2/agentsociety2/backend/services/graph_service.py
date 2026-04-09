"""图谱构建服务，负责异步任务跟踪与图谱查询。"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Any

from agentsociety2.graph import GraphBuilder, GraphInfo, GraphitiSpace
from agentsociety2.graph.chunker import ChunkerConfig, ChunkingStrategy
from agentsociety2.world.models import WorldState

__all__ = ["GraphService"]

logger = logging.getLogger("agentsociety2.backend.graph_service")


def _gs_from_env(group_id: str) -> GraphitiSpace:
    """根据当前环境变量构建 GraphitiSpace。"""
    return GraphitiSpace(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        llm_api_key=os.getenv("LLM_API_KEY") or None,
        llm_api_base=os.getenv("LLM_API_BASE") or None,
        embedder_model=os.getenv("EMBEDDER_MODEL", "text-embedding-3-small"),
        embedder_api_key=os.getenv("EMBEDDER_API_KEY") or None,
        embedder_api_base=os.getenv("EMBEDDER_API_BASE") or None,
        group_id=group_id,
    )


# ---------------------------------------------------------------------------
# In-memory task store (simple; replace with DB if persistence is needed)
# ---------------------------------------------------------------------------

_tasks: dict[str, dict[str, Any]] = {}


def _task_update(task_id: str, **kwargs: Any) -> None:
    if task_id in _tasks:
        current_status = _tasks[task_id].get("status")
        next_status = kwargs.get("status")
        if current_status in {"completed", "failed"} and next_status == "processing":
            kwargs = {k: v for k, v in kwargs.items() if k not in {"status", "progress", "message"}}
        _tasks[task_id].update(kwargs)


class GraphService:
    """图谱服务层：负责构建与查询知识图谱。"""

    @staticmethod
    def build_fact_seed_text(world_state: WorldState) -> str:
        """Build a fact-only graph source from the authoritative world state."""
        entity_name_map = {entity.id: entity.name for entity in world_state.entities}
        entity_lines = [
            f"ENTITY | {entity.name} | {entity.entity_type} | {entity.description or '暂无描述'}"
            for entity in world_state.entities[:120]
        ]
        relation_lines = [
            (
                f"RELATION | {entity_name_map.get(relation.source_entity_id, relation.source_entity_id)}"
                f" | {relation.relation_type} | "
                f"{entity_name_map.get(relation.target_entity_id, relation.target_entity_id)}"
                f" | {relation.description or '无描述'}"
            )
            for relation in world_state.relations[:200]
        ]
        event_lines = [
            f"EVENT | tick={event.tick} | {event.title} | {event.description}"
            for event in world_state.timeline[-80:]
        ]

        return "\n\n".join(
            [
                f"WORLD | {world_state.name}",
                "ENTITIES\n" + ("\n".join(entity_lines) if entity_lines else "ENTITY | (none) | other | 暂无"),
                "RELATIONS\n" + (
                    "\n".join(relation_lines)
                    if relation_lines
                    else "RELATION | (none) | related_to | (none) | 暂无"
                ),
                "EVENTS\n" + ("\n".join(event_lines) if event_lines else "EVENT | none"),
            ]
        )

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    @staticmethod
    async def start_build(
        world_id: str,
        fact_seed_text: str,
        chunking_strategy: str = "by_title",
        max_chunk_size: int = 1000,
    ) -> str:
        """启动后台图谱构建任务，并立即返回 task_id。"""
        task_id = str(uuid.uuid4())
        _tasks[task_id] = {
            "task_id": task_id,
            "world_id": world_id,
            "status": "pending",
            "progress": 0,
            "message": "已加入队列",
            "result": None,
            "error": None,
            "created_at": datetime.utcnow().isoformat(),
        }
        asyncio.ensure_future(
            GraphService._run_build(
                task_id=task_id,
                world_id=world_id,
                fact_seed_text=fact_seed_text,
                chunking_strategy=chunking_strategy,
                max_chunk_size=max_chunk_size,
            )
        )
        return task_id

    @staticmethod
    async def _run_build(
        task_id: str,
        world_id: str,
        fact_seed_text: str,
        chunking_strategy: str,
        max_chunk_size: int,
    ) -> None:
        _task_update(task_id, status="processing", progress=5, message="正在初始化图谱构建器")

        gs = _gs_from_env(world_id)
        try:
            await gs.init()
        except Exception as exc:
            logger.warning("Graphiti 初始化失败，将退回为仅抽取模式：%s", exc)
            gs._ready = False

        try:
            strategy = ChunkingStrategy(chunking_strategy) if chunking_strategy in (
                "basic", "by_title", "simple"
            ) else ChunkingStrategy.BY_TITLE

            builder = GraphBuilder(
                graphiti_space=gs,
                model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
                api_key=os.getenv("LLM_API_KEY") or None,
                api_base=os.getenv("LLM_API_BASE") or None,
                group_id=world_id,
                chunker_config=ChunkerConfig(strategy=strategy, max_characters=max_chunk_size),
            )

            async def _progress(pct: int, msg: str) -> None:
                _task_update(task_id, status="processing", progress=pct, message=msg)

            info: GraphInfo = await builder.build_async(
                seed_text=fact_seed_text,
                graph_id=world_id,
                chunk_size=max_chunk_size,
                progress_cb=lambda pct, msg: asyncio.ensure_future(_progress(pct, msg)),
            )

            _task_update(
                task_id,
                status="completed",
                progress=100,
                message=f"图谱构建完成：{info.node_count} 个节点，{info.edge_count} 条边",
                result=info.to_dict(),
            )
        except Exception as exc:
            logger.exception("世界 %s 的图谱构建失败", world_id)
            _task_update(
                task_id,
                status="failed",
                message=f"图谱构建失败：{exc}",
                error=str(exc),
            )
        finally:
            await gs.close()

    # ------------------------------------------------------------------
    # Task status
    # ------------------------------------------------------------------

    @staticmethod
    def get_task(task_id: str) -> dict[str, Any] | None:
        return _tasks.get(task_id)

    @staticmethod
    def list_tasks(world_id: str | None = None) -> list[dict[str, Any]]:
        tasks = list(_tasks.values())
        if world_id:
            tasks = [t for t in tasks if t.get("world_id") == world_id]
        return sorted(tasks, key=lambda t: t.get("created_at", ""), reverse=True)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @staticmethod
    async def get_snapshot(
        world_id: str,
        entity_types: list[str] | None = None,
        relation_types: list[str] | None = None,
    ) -> dict[str, Any]:
        gs = _gs_from_env(world_id)
        try:
            snapshot = await gs.get_graph_snapshot(
                entity_types=entity_types,
                relation_types=relation_types,
            )
            if snapshot.get("nodes") or snapshot.get("edges"):
                return snapshot

            # Fallback: if Neo4j has not materialized queryable nodes yet, surface the
            # latest successful task result so the frontend can still render the graph.
            for task in GraphService.list_tasks(world_id=world_id):
                result = task.get("result")
                if not isinstance(result, dict):
                    continue
                nodes = result.get("nodes")
                edges = result.get("edges")
                if isinstance(nodes, list) or isinstance(edges, list):
                    return {
                        "nodes": nodes if isinstance(nodes, list) else [],
                        "edges": edges if isinstance(edges, list) else [],
                    }
            return {"nodes": [], "edges": []}
        except Exception as exc:
            logger.warning("get_snapshot failed: %s", exc)
            return {"nodes": [], "edges": []}
        finally:
            await gs.close()

    @staticmethod
    async def search_memory(
        world_id: str,
        query: str,
        entity_types: list[str] | None = None,
        relation_types: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        gs = _gs_from_env(world_id)
        try:
            await gs.init()
            return await gs.search_memory(
                query=query,
                entity_types=entity_types,
                relation_types=relation_types,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("search_memory failed: %s", exc)
            return []
        finally:
            await gs.close()

    @staticmethod
    async def get_entities(
        world_id: str,
        entity_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        gs = _gs_from_env(world_id)
        try:
            return await gs.get_entities_with_relations(
                entity_types=entity_types,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("get_entities failed: %s", exc)
            return []
        finally:
            await gs.close()
