"""GraphitiSpace — standalone Neo4j/Graphiti knowledge graph manager."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid5, NAMESPACE_URL

__all__ = ["GraphitiSpace"]

logger = logging.getLogger("agentsociety2.graph.graphiti_space")

_MAX_EPISODE_BODY = 3000
_MAX_SEARCH_QUERY = 300


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_episode_body(text: str) -> str:
    if len(text) <= _MAX_EPISODE_BODY:
        return text
    return text[:_MAX_EPISODE_BODY] + "\n[truncated]"


def _safe_query(text: str) -> str:
    return text[:_MAX_SEARCH_QUERY] if len(text) > _MAX_SEARCH_QUERY else text


def _normalize_filter_values(values: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = str(value or "").strip()
        marker = item.lower()
        if not item or marker in seen:
            continue
        seen.add(marker)
        normalized.append(item)
    return normalized


def _stable_uuid(group_id: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{group_id}:{value}"))


def _supports_graphiti_openai_clients(model: str, api_base: str | None = None) -> bool:
    normalized = (model or "").strip().lower()
    base = (api_base or "").strip().lower()
    if "api.deepseek.com" in base:
        return False
    if normalized.startswith("deepseek") or normalized.startswith("deepseek/"):
        return False
    return True


class GraphitiSpace:
    """
    Standalone Neo4j/Graphiti knowledge graph manager (no framework coupling).

    Provides:
    - Graphiti client lifecycle (init / close)
    - Episode ingestion
    - Ontology metadata application
    - Semantic memory search
    - Graph snapshot for frontend visualisation
    - Entity + relation query
    """

    def __init__(
        self,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "password",
        llm_model: str = "gpt-4o-mini",
        llm_api_key: str | None = None,
        llm_api_base: str | None = None,
        embedder_model: str = "text-embedding-3-small",
        embedder_api_key: str | None = None,
        embedder_api_base: str | None = None,
        group_id: str = "agentsociety2",
    ):
        self._neo4j_uri = neo4j_uri
        self._neo4j_user = neo4j_user
        self._neo4j_password = neo4j_password
        self._llm_model = llm_model
        self._llm_api_key = llm_api_key
        self._llm_api_base = llm_api_base
        self._embedder_model = embedder_model
        self._embedder_api_key = embedder_api_key or llm_api_key
        self._embedder_api_base = embedder_api_base or llm_api_base
        self._group_id = group_id
        self._graphiti: Any = None
        self._ready = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        try:
            self._graphiti = self._build_graphiti()
            await self._graphiti.build_indices_and_constraints()
            self._ready = True
            logger.info("GraphitiSpace ready (group=%s)", self._group_id)
        except Exception as exc:
            logger.error("GraphitiSpace init failed: %s — graph disabled", exc)
            self._ready = False

    async def close(self) -> None:
        if self._graphiti is not None:
            try:
                await self._graphiti.close()
            except Exception:
                pass
        self._ready = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_graphiti(self) -> Any:
        if not _supports_graphiti_openai_clients(self._llm_model, self._llm_api_base):
            raise RuntimeError(
                f"Graphiti OpenAI client incompatible with endpoint "
                f"(model={self._llm_model}, base={self._llm_api_base})"
            )
        from graphiti_core import Graphiti
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_client import OpenAIClient
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

        llm_kwargs: dict = {"model": self._llm_model}
        if self._llm_api_key:
            llm_kwargs["api_key"] = self._llm_api_key
        if self._llm_api_base:
            llm_kwargs["base_url"] = self._llm_api_base

        emb_kwargs: dict = {"embedding_model": self._embedder_model}
        if self._embedder_api_key:
            emb_kwargs["api_key"] = self._embedder_api_key
        if self._embedder_api_base:
            emb_kwargs["base_url"] = self._embedder_api_base

        return Graphiti(
            uri=self._neo4j_uri,
            user=self._neo4j_user,
            password=self._neo4j_password,
            llm_client=OpenAIClient(config=LLMConfig(**llm_kwargs)),
            embedder=OpenAIEmbedder(config=OpenAIEmbedderConfig(**emb_kwargs)),
            cross_encoder=OpenAIRerankerClient(config=LLMConfig(**llm_kwargs)),
        )

    async def _with_neo4j_session(self):
        from neo4j import AsyncGraphDatabase
        driver = AsyncGraphDatabase.driver(
            self._neo4j_uri, auth=(self._neo4j_user, self._neo4j_password)
        )
        try:
            async with driver.session() as session:
                yield session
        finally:
            await driver.close()

    # ------------------------------------------------------------------
    # Episode ingestion
    # ------------------------------------------------------------------

    async def add_episode(
        self,
        name: str,
        body: str,
        reference_time: datetime | None = None,
        source_description: str = "",
        group_id: str | None = None,
    ) -> None:
        if not self._ready:
            return
        ref_time = reference_time or _utc_now()
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        try:
            await self._graphiti.add_episode(
                name=name,
                episode_body=_safe_episode_body(body),
                reference_time=ref_time,
                source_description=source_description,
                group_id=group_id or self._group_id,
            )
        except OSError as exc:
            if exc.errno == 36:
                logger.debug("Episode ingest skipped: name too long (name=%s)", name)
            else:
                logger.warning("Episode ingest OSError (name=%s): %s", name, exc)
        except Exception as exc:
            logger.warning("Episode ingest failed (name=%s): %s", name, exc)

    # ------------------------------------------------------------------
    # Ontology metadata
    # ------------------------------------------------------------------

    async def apply_ontology_metadata(
        self,
        entities: list[dict],
        relations: list[dict],
    ) -> None:
        if not self._ready:
            return

        norm_entities = [
            {
                "name": str(e.get("name") or "").strip(),
                "entity_type": str(e.get("kind") or "").strip(),
                "summary": str(e.get("description") or "").strip(),
            }
            for e in entities
            if str(e.get("name") or "").strip() and str(e.get("kind") or "").strip()
        ]
        norm_relations = [
            {
                "source": str(r.get("source") or "").strip(),
                "target": str(r.get("target") or "").strip(),
                "relation_type": str(r.get("relation") or "").strip(),
                "relation_description": str(r.get("description") or r.get("relation") or "").strip(),
            }
            for r in relations
            if (
                str(r.get("source") or "").strip()
                and str(r.get("target") or "").strip()
                and str(r.get("relation") or "").strip()
            )
        ]

        if not norm_entities and not norm_relations:
            return

        try:
            async for session in self._with_neo4j_session():
                if norm_entities:
                    await session.run(
                        """
                        UNWIND $entities AS entity
                        MATCH (n:Entity)
                        WHERE n.group_id = $group_id
                          AND toLower(n.name) = toLower(entity.name)
                        SET n.entity_type   = entity.entity_type,
                            n.ontology_type = entity.entity_type,
                            n.summary = CASE
                                WHEN coalesce(n.summary, '') = '' AND entity.summary <> ''
                                THEN entity.summary
                                ELSE n.summary
                            END
                        """,
                        group_id=self._group_id,
                        entities=norm_entities,
                    )
                if norm_relations:
                    await session.run(
                        """
                        UNWIND $relations AS relation
                        MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
                        WHERE r.group_id = $group_id
                          AND toLower(a.name) = toLower(relation.source)
                          AND toLower(b.name) = toLower(relation.target)
                        SET r.relation_type         = relation.relation_type,
                            r.ontology_relation_type = relation.relation_type,
                            r.relation_description  = relation.relation_description
                        """,
                        group_id=self._group_id,
                        relations=norm_relations,
                    )
            logger.info(
                "Ontology metadata applied (%d entities, %d relations)",
                len(norm_entities), len(norm_relations),
            )
        except Exception as exc:
            logger.warning("apply_ontology_metadata failed: %s", exc)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def _lookup_relation_metadata(
        self,
        pairs: list[dict[str, str]],
    ) -> dict[tuple[str, str], dict[str, str]]:
        if not pairs:
            return {}
        try:
            async for session in self._with_neo4j_session():
                result = await session.run(
                    """
                    UNWIND $pairs AS pair
                    MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
                    WHERE r.group_id = $group_id
                      AND toLower(a.name) = toLower(pair.source)
                      AND toLower(b.name) = toLower(pair.target)
                    RETURN toLower(a.name) AS source_key,
                           toLower(b.name) AS target_key,
                           coalesce(a.entity_type, head(a.labels), '') AS source_type,
                           coalesce(b.entity_type, head(b.labels), '') AS target_type,
                           coalesce(r.relation_type, r.name, '') AS relation_type,
                           coalesce(r.relation_description, r.fact, r.name, '') AS relation_description
                    """,
                    group_id=self._group_id,
                    pairs=pairs,
                )
                meta: dict[tuple[str, str], dict[str, str]] = {}
                async for rec in result:
                    meta[(rec["source_key"], rec["target_key"])] = {
                        "source_type": rec["source_type"] or "",
                        "target_type": rec["target_type"] or "",
                        "relation_type": rec["relation_type"] or "",
                        "relation_description": rec["relation_description"] or "",
                    }
                return meta
        except Exception as exc:
            logger.debug("_lookup_relation_metadata failed: %s", exc)
        return {}

    async def search_memory(
        self,
        query: str,
        entity_types: list[str] | None = None,
        relation_types: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        if not self._ready or not query.strip():
            return []

        allowed_entity = {i.lower() for i in _normalize_filter_values(entity_types)}
        allowed_relation = {i.lower() for i in _normalize_filter_values(relation_types)}

        try:
            results = await self._graphiti.search(
                query=_safe_query(query),
                group_ids=[self._group_id],
                num_results=limit * 2,
            )
            raw: list[dict] = []
            for edge in results:
                raw.append(
                    {
                        "fact": str(getattr(edge, "fact", str(edge))),
                        "valid_at": str(getattr(edge, "valid_at", "")),
                        "source_node_name": str(getattr(edge, "source_node_name", "") or ""),
                        "target_node_name": str(getattr(edge, "target_node_name", "") or ""),
                        "source_node_type": str(getattr(edge, "source_node_entity_type", "") or ""),
                        "target_node_type": str(getattr(edge, "target_node_entity_type", "") or ""),
                        "relation_type": str(
                            getattr(edge, "relation_type", "")
                            or getattr(edge, "name", "")
                            or ""
                        ),
                    }
                )

            meta = await self._lookup_relation_metadata(
                [
                    {"source": item["source_node_name"], "target": item["target_node_name"]}
                    for item in raw
                    if item["source_node_name"] and item["target_node_name"]
                ]
            )

            out: list[dict] = []
            for item in raw:
                if len(out) >= limit:
                    break
                pair_key = (
                    item["source_node_name"].strip().lower(),
                    item["target_node_name"].strip().lower(),
                )
                m = meta.get(pair_key, {})
                src_type = m.get("source_type") or item["source_node_type"]
                tgt_type = m.get("target_type") or item["target_node_type"]
                rel_type = m.get("relation_type") or item["relation_type"]
                if allowed_relation and rel_type.lower() not in allowed_relation:
                    continue
                if allowed_entity:
                    if not (
                        (src_type and src_type.lower() in allowed_entity)
                        or (tgt_type and tgt_type.lower() in allowed_entity)
                    ):
                        continue
                out.append(
                    {
                        "fact": m.get("relation_description") or item["fact"],
                        "valid_at": item["valid_at"],
                        "source_node_name": item["source_node_name"],
                        "target_node_name": item["target_node_name"],
                        "source_node_type": src_type,
                        "target_node_type": tgt_type,
                        "relation_type": rel_type,
                    }
                )
            return out
        except Exception as exc:
            logger.debug("search_memory failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Graph snapshot (frontend visualisation)
    # ------------------------------------------------------------------

    async def get_graph_snapshot(
        self,
        entity_types: list[str] | None = None,
        relation_types: list[str] | None = None,
    ) -> dict[str, list]:
        entity_type_list = _normalize_filter_values(entity_types)
        relation_type_list = _normalize_filter_values(relation_types)

        try:
            async for session in self._with_neo4j_session():
                node_result = await session.run(
                    """
                    MATCH (n:Entity)
                    WHERE n.group_id = $group_id
                      AND (size($entity_types) = 0 OR
                           coalesce(n.entity_type, head(labels(n)), 'entity') IN $entity_types)
                    RETURN n.uuid AS id, n.name AS label,
                           coalesce(n.entity_type, head(labels(n)), 'entity') AS kind,
                           n.summary AS summary
                    LIMIT 200
                    """,
                    group_id=self._group_id,
                    entity_types=entity_type_list,
                )
                nodes = [
                    {
                        "id": rec["id"],
                        "label": rec["label"] or "?",
                        "kind": rec["kind"] or "entity",
                        "summary": rec["summary"] or "",
                    }
                    async for rec in node_result
                ]

                edge_result = await session.run(
                    """
                    MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
                    WHERE r.group_id = $group_id
                      AND (size($relation_types) = 0 OR
                           coalesce(r.relation_type, r.name, 'related_to') IN $relation_types)
                      AND (size($entity_types) = 0 OR
                           (coalesce(a.entity_type, head(labels(a)), 'entity') IN $entity_types
                            AND coalesce(b.entity_type, head(labels(b)), 'entity') IN $entity_types))
                    RETURN r.uuid AS id,
                           a.uuid AS source,
                           b.uuid AS target,
                           coalesce(r.fact, r.relation_description, r.name, 'related') AS relation,
                           coalesce(r.relation_type, r.name, 'related_to') AS relation_type,
                           r.created_at AS timestamp
                    LIMIT 400
                    """,
                    group_id=self._group_id,
                    entity_types=entity_type_list,
                    relation_types=relation_type_list,
                )
                edges = [
                    {
                        "id": rec["id"],
                        "source": rec["source"],
                        "target": rec["target"],
                        "relation": (rec["relation"] or "related")[:60],
                        "relation_type": rec["relation_type"] or "related_to",
                        "timestamp": str(rec["timestamp"] or ""),
                    }
                    async for rec in edge_result
                ]
            return {"nodes": nodes, "edges": edges}
        except Exception as exc:
            logger.warning("get_graph_snapshot failed: %s", exc)
            return {"nodes": [], "edges": []}

    async def replace_graph_from_extraction(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> dict[str, list]:
        entity_rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        id_map: dict[str, str] = {}
        for node in nodes:
            original_id = str(node.get("id") or "").strip()
            label = str(node.get("label") or node.get("name") or original_id or "?").strip()
            if not label:
                continue
            uuid = _stable_uuid(self._group_id, f"node:{original_id or label}")
            if uuid in seen_ids:
                continue
            seen_ids.add(uuid)
            if original_id:
                id_map[original_id] = uuid
            entity_rows.append(
                {
                    "uuid": uuid,
                    "name": label,
                    "summary": str(node.get("summary") or ""),
                    "entity_type": str(node.get("kind") or "entity"),
                    "group_id": self._group_id,
                }
            )

        edge_rows: list[dict[str, Any]] = []
        for index, edge in enumerate(edges):
            source_key = str(edge.get("source") or "").strip()
            target_key = str(edge.get("target") or "").strip()
            source_uuid = id_map.get(source_key)
            target_uuid = id_map.get(target_key)
            if not source_uuid or not target_uuid:
                continue
            edge_rows.append(
                {
                    "uuid": _stable_uuid(
                        self._group_id,
                        f"edge:{edge.get('id') or index}:{source_uuid}:{target_uuid}",
                    ),
                    "source_uuid": source_uuid,
                    "target_uuid": target_uuid,
                    "group_id": self._group_id,
                    "name": str(edge.get("relation_type") or edge.get("relation") or "related_to"),
                    "fact": str(edge.get("relation") or edge.get("relation_type") or "related"),
                    "relation_type": str(edge.get("relation_type") or edge.get("relation") or "related_to"),
                    "relation_description": str(edge.get("relation") or ""),
                    "created_at": _utc_now().isoformat(),
                }
            )

        try:
            async for session in self._with_neo4j_session():
                await session.run(
                    """
                    MATCH (n:Entity {group_id: $group_id})
                    DETACH DELETE n
                    """,
                    group_id=self._group_id,
                )
                if entity_rows:
                    await session.run(
                        """
                        UNWIND $rows AS row
                        CREATE (n:Entity)
                        SET n.uuid = row.uuid,
                            n.name = row.name,
                            n.summary = row.summary,
                            n.entity_type = row.entity_type,
                            n.group_id = row.group_id
                        """,
                        rows=entity_rows,
                    )
                if edge_rows:
                    await session.run(
                        """
                        UNWIND $rows AS row
                        MATCH (a:Entity {uuid: row.source_uuid, group_id: row.group_id})
                        MATCH (b:Entity {uuid: row.target_uuid, group_id: row.group_id})
                        CREATE (a)-[r:RELATES_TO]->(b)
                        SET r.uuid = row.uuid,
                            r.group_id = row.group_id,
                            r.name = row.name,
                            r.fact = row.fact,
                            r.relation_type = row.relation_type,
                            r.relation_description = row.relation_description,
                            r.created_at = row.created_at
                        """,
                        rows=edge_rows,
                    )
            logger.info(
                "Fallback Neo4j graph persisted (%d nodes, %d edges) for group=%s",
                len(entity_rows),
                len(edge_rows),
                self._group_id,
            )
        except Exception as exc:
            logger.warning("replace_graph_from_extraction failed: %s", exc)
            return {"nodes": [], "edges": []}

        return await self.get_graph_snapshot()

    # ------------------------------------------------------------------
    # Entity query (persona generation helper)
    # ------------------------------------------------------------------

    async def get_entities_with_relations(
        self,
        entity_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        type_filter = _normalize_filter_values(entity_types)
        try:
            async for session in self._with_neo4j_session():
                result = await session.run(
                    """
                    MATCH (n:Entity)
                    WHERE n.group_id = $group_id
                      AND (size($types) = 0 OR
                           coalesce(n.entity_type, head(labels(n)), 'entity') IN $types)
                    OPTIONAL MATCH (n)-[r:RELATES_TO]-(other:Entity)
                    WHERE r.group_id = $group_id
                    WITH n, collect({
                        target:   other.name,
                        relation: coalesce(r.relation_type, r.name, 'related'),
                        fact:     coalesce(r.fact, r.relation_description, '')
                    })[..10] AS rels
                    RETURN n.name AS name,
                           coalesce(n.entity_type, head(labels(n)), 'entity') AS kind,
                           coalesce(n.summary, '') AS summary,
                           rels
                    LIMIT $limit
                    """,
                    group_id=self._group_id,
                    types=type_filter,
                    limit=limit,
                )
                entities: list[dict] = []
                async for rec in result:
                    entities.append(
                        {
                            "name": rec["name"] or "",
                            "kind": rec["kind"] or "entity",
                            "summary": rec["summary"] or "",
                            "relations": [r for r in (rec["rels"] or []) if r.get("target")],
                        }
                    )
                return entities
        except Exception as exc:
            logger.warning("get_entities_with_relations failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "ready": self._ready,
            "neo4j_uri": self._neo4j_uri,
            "group_id": self._group_id,
        }
