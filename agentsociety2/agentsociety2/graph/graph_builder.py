"""GraphBuilder — seed text → LLM entity extraction → Graphiti/Neo4j.

Chunking is delegated to UnstructuredChunker (unstructured.io, with
simple character-sliding fallback).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .chunker import ChunkerConfig, ChunkingStrategy, UnstructuredChunker

__all__ = ["GraphBuilder", "GraphInfo"]

logger = logging.getLogger("agentsociety2.graph.graph_builder")


# ------------------------------------------------------------------
# LLM prompts
# ------------------------------------------------------------------

_EXTRACT_SYSTEM = """\
You are a knowledge graph extraction assistant.
You must follow the provided ontology strictly:
- Entity `kind` must come from the allowed entity types
- Relation `relation` must come from the allowed relation types
- Prefer the ontology types over inventing new labels
- If something does not fit perfectly, map it to the closest allowed type
Return ONLY valid JSON with this exact schema:
{
  "entities": [
    {"id": "e1", "name": "<name>", "kind": "<allowed_entity_type>", "description": "<brief>"}
  ],
  "relations": [
    {
      "source": "<entity_name>",
      "target": "<entity_name>",
      "relation": "<allowed_relation_type>",
      "description": "<short natural language paraphrase>",
      "confidence": 0.9
    }
  ]
}
Extract at most 30 entities and 50 relations. Be concise.\
"""

_ONTOLOGY_SYSTEM = """\
You are an ontology design assistant.
Given a text, generate a compact domain ontology for knowledge graph extraction.
Use 4-8 entity types and 4-8 relation types only.
Prefer broad, stable, reusable types over narrow ones.
Return ONLY valid JSON:
{
  "entity_types": [
    {
      "name": "Organization",
      "description": "A company, institution, team, or other organized actor",
      "examples": ["Acme Corp"]
    }
  ],
  "relation_types": [
    {
      "name": "influences",
      "description": "A source factor changes or shapes a target",
      "source_types": ["Concept", "Organization"],
      "target_types": ["Concept", "Event"],
      "examples": ["market demand influences expansion pace"]
    }
  ]
}\
"""

_DEFAULT_ONTOLOGY: dict = {
    "entity_types": [
        {"name": "Organization", "description": "A company, institution, team, or organized actor", "examples": ["company", "brand", "government"]},
        {"name": "Person", "description": "An individual person or role-based human actor", "examples": ["manager", "customer", "founder"]},
        {"name": "Group", "description": "A collective social actor, community, audience, or cohort", "examples": ["residents", "workers", "supporters"]},
        {"name": "Location", "description": "A place, market, city, region, or other location", "examples": ["city", "country", "market"]},
        {"name": "Event", "description": "A scenario, action, milestone, or time-bound development", "examples": ["expansion", "launch", "disruption"]},
        {"name": "Concept", "description": "An abstract factor, metric, strategy, risk, or topic", "examples": ["demand", "efficiency", "competition"]},
    ],
    "relation_types": [
        {"name": "influences", "description": "A source factor shapes the target", "source_types": ["Concept", "Event", "Organization", "Person", "Group"], "target_types": ["Concept", "Event", "Organization", "Person", "Group"], "examples": ["demand influences expansion"]},
        {"name": "depends_on", "description": "A target relies on a source factor or prerequisite", "source_types": ["Concept", "Organization", "Location", "Group"], "target_types": ["Concept", "Event", "Organization", "Group"], "examples": ["expansion depends_on supply chain"]},
        {"name": "part_of", "description": "A source belongs to or is part of a larger target", "source_types": ["Concept", "Event", "Location"], "target_types": ["Organization", "Event", "Location", "Concept"], "examples": ["marketing is part_of strategy"]},
        {"name": "occurs_in", "description": "An event or organization is associated with a location", "source_types": ["Event", "Organization", "Group"], "target_types": ["Location"], "examples": ["launch occurs_in city"]},
        {"name": "causes", "description": "A source directly causes a target outcome", "source_types": ["Concept", "Event", "Organization", "Group"], "target_types": ["Concept", "Event", "Group"], "examples": ["competition causes slowdown"]},
        {"name": "related_to", "description": "Fallback relation when another allowed type is not reliable", "source_types": ["Organization", "Person", "Group", "Location", "Event", "Concept"], "target_types": ["Organization", "Person", "Group", "Location", "Event", "Concept"], "examples": ["brand related_to expansion"]},
    ],
}


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------

@dataclass
class GraphInfo:
    graph_id: str
    node_count: int = 0
    edge_count: int = 0
    entity_types: list[str] = field(default_factory=list)
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
            "nodes": self.nodes,
            "edges": self.edges,
            "error": self.error,
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _normalize_type_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in (value or "").strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned.lower()


def _dedupe_by_name(items: list[dict], key: str = "name") -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        name = str(item.get(key) or "").strip()
        marker = name.lower()
        if not name or marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def _build_fact_episode(entities: list[dict], relations: list[dict]) -> str:
    entity_lines = [
        f"ENTITY | {e.get('name', '')} | {e.get('kind', 'entity')} | {e.get('description', '')}"
        for e in entities
        if str(e.get("name") or "").strip()
    ]
    relation_lines = [
        (
            f"RELATION | {r.get('source', '')} | {r.get('relation', 'related_to')} | "
            f"{r.get('target', '')} | {r.get('description', '')}"
        )
        for r in relations
        if str(r.get("source") or "").strip() and str(r.get("target") or "").strip()
    ]
    lines = entity_lines + relation_lines
    if not lines:
        return "ENTITY | (empty) | Concept | no extracted entities"
    return "\n".join(lines)


# ------------------------------------------------------------------
# GraphBuilder
# ------------------------------------------------------------------

class GraphBuilder:
    """
    Build a Graphiti knowledge graph from seed text.

    Pipeline:
      1. Chunk seed text via UnstructuredChunker (by_title strategy)
      2. LLM generates domain ontology from first chunk
      3. LLM extracts entities + relations per chunk
      4. Ingest episodes into Graphiti → Neo4j
      5. Apply ontology metadata
      6. Return GraphInfo
    """

    def __init__(
        self,
        graphiti_space=None,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        api_base: str | None = None,
        group_id: str = "agentsociety2",
        chunker_config: ChunkerConfig | None = None,
    ):
        self._graphiti_space = graphiti_space
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._group_id = group_id
        self._chunker_config = chunker_config or ChunkerConfig(
            strategy=ChunkingStrategy.BY_TITLE,
            max_characters=1000,
            new_after_n_chars=800,
            overlap=100,
        )

    # ------------------------------------------------------------------
    # Ontology
    # ------------------------------------------------------------------

    def _normalize_ontology(self, raw: dict | None) -> dict:
        if not isinstance(raw, dict):
            raw = json.loads(json.dumps(_DEFAULT_ONTOLOGY))

        entity_types: list[dict] = []
        for item in raw.get("entity_types") or []:
            if isinstance(item, str):
                entity_types.append({"name": item.strip() or "Concept", "description": "", "examples": []})
            elif isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    entity_types.append({
                        "name": name,
                        "description": str(item.get("description") or "").strip(),
                        "examples": [str(x) for x in (item.get("examples") or [])[:3]],
                    })
        entity_types = _dedupe_by_name(entity_types)[:8]
        if not entity_types:
            entity_types = json.loads(json.dumps(_DEFAULT_ONTOLOGY["entity_types"]))
        else:
            existing_markers = {_normalize_type_name(item["name"]) for item in entity_types}
            actor_defaults = [
                item
                for item in _DEFAULT_ONTOLOGY["entity_types"]
                if item["name"] in {"Person", "Organization", "Group"}
            ]
            for item in actor_defaults:
                marker = _normalize_type_name(item["name"])
                if marker in existing_markers:
                    continue
                entity_types.append(json.loads(json.dumps(item)))
                existing_markers.add(marker)
            entity_types = _dedupe_by_name(entity_types)[:8]

        entity_names = {i["name"] for i in entity_types}

        relation_types: list[dict] = []
        for item in raw.get("relation_types") or []:
            if isinstance(item, str):
                relation_types.append({
                    "name": item.strip() or "related_to",
                    "description": "",
                    "source_types": sorted(entity_names),
                    "target_types": sorted(entity_names),
                    "examples": [],
                })
            elif isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                src = [str(x) for x in (item.get("source_types") or []) if str(x) in entity_names]
                tgt = [str(x) for x in (item.get("target_types") or []) if str(x) in entity_names]
                relation_types.append({
                    "name": name,
                    "description": str(item.get("description") or "").strip(),
                    "source_types": src or sorted(entity_names),
                    "target_types": tgt or sorted(entity_names),
                    "examples": [str(x) for x in (item.get("examples") or [])[:3]],
                })
        relation_types = _dedupe_by_name(relation_types)[:8]
        if not relation_types:
            relation_types = json.loads(json.dumps(_DEFAULT_ONTOLOGY["relation_types"]))

        return {"entity_types": entity_types, "relation_types": relation_types}

    def _ontology_prompt(self, ontology: dict) -> str:
        entity_lines = [
            f"- {i['name']}: {i.get('description') or 'No description'}"
            for i in ontology["entity_types"]
        ]
        relation_lines = [
            f"- {i['name']}: {i.get('description') or 'No description'} "
            f"(source_types={i.get('source_types')}, target_types={i.get('target_types')})"
            for i in ontology["relation_types"]
        ]
        return (
            "Allowed entity types:\n" + "\n".join(entity_lines)
            + "\n\nAllowed relation types:\n" + "\n".join(relation_lines)
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_extraction(
        self,
        entities: list[dict],
        relations: list[dict],
        ontology: dict,
    ) -> tuple[list[dict], list[dict]]:
        entity_types = ontology["entity_types"]
        relation_types = ontology["relation_types"]
        entity_name_by_norm = {_normalize_type_name(i["name"]): i["name"] for i in entity_types}
        relation_by_norm = {_normalize_type_name(i["name"]): i for i in relation_types}
        fallback_entity = "Concept" if "Concept" in entity_name_by_norm.values() else entity_types[0]["name"]
        fallback_relation = relation_by_norm.get("related_to") or relation_types[0]

        validated_entities: list[dict] = []
        entity_lookup: dict[str, dict] = {}
        for idx, entity in enumerate(entities):
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("name") or "").strip()
            if not name:
                continue
            raw_kind = str(entity.get("kind") or fallback_entity).strip()
            kind = entity_name_by_norm.get(_normalize_type_name(raw_kind), fallback_entity)
            normalized = {
                "id": str(entity.get("id") or f"e{idx + 1}"),
                "name": name,
                "kind": kind,
                "description": str(entity.get("description") or "").strip(),
            }
            validated_entities.append(normalized)
            entity_lookup[name.lower()] = normalized
        validated_entities = _dedupe_by_name(validated_entities)

        validated_relations: list[dict] = []
        seen_relations: set[tuple[str, str, str]] = set()
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            src_name = str(relation.get("source") or "").strip()
            tgt_name = str(relation.get("target") or "").strip()
            if not src_name or not tgt_name:
                continue
            src = entity_lookup.get(src_name.lower())
            tgt = entity_lookup.get(tgt_name.lower())
            if not src or not tgt or src["name"] == tgt["name"]:
                continue
            raw_rel = str(relation.get("relation") or fallback_relation["name"]).strip()
            rel_schema = relation_by_norm.get(_normalize_type_name(raw_rel), fallback_relation)
            if (
                src["kind"] not in rel_schema["source_types"]
                or tgt["kind"] not in rel_schema["target_types"]
            ):
                rel_schema = fallback_relation
            key = (src["name"].lower(), tgt["name"].lower(), rel_schema["name"].lower())
            if key in seen_relations:
                continue
            seen_relations.add(key)
            validated_relations.append({
                "source": src["name"],
                "target": tgt["name"],
                "relation": rel_schema["name"],
                "description": str(relation.get("description") or raw_rel).strip(),
                "confidence": float(relation.get("confidence", 0.6) or 0.6),
            })

        return validated_entities, validated_relations

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _normalize_litellm_model(self) -> str:
        model = (self._model or "").strip()
        base = (self._api_base or "").strip().lower()
        if not model or "/" in model:
            return model
        if "api.deepseek.com" in base or model.startswith("deepseek-"):
            return f"deepseek/{model}"
        return model

    async def _call_llm(self, messages: list[dict]) -> str | None:
        try:
            import litellm
            kwargs: dict[str, Any] = {
                "model": self._normalize_litellm_model(),
                "messages": messages,
                "temperature": 0.1,
            }
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._api_base:
                kwargs["api_base"] = self._api_base
            response = await litellm.acompletion(**kwargs)
            return response.choices[0].message.content
        except Exception as exc:
            logger.warning("GraphBuilder LLM call failed: %s", exc)
            return None

    def _parse_json(self, raw: str | None) -> dict | None:
        if not raw:
            return None
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(raw)
        except Exception:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(raw[start:end + 1])
                except Exception:
                    pass
        return None

    async def generate_ontology(self, text: str) -> dict:
        raw = await self._call_llm([
            {"role": "system", "content": _ONTOLOGY_SYSTEM},
            {"role": "user", "content": text[:2000]},
        ])
        return self._normalize_ontology(self._parse_json(raw))

    async def extract_triples(
        self, text_chunk: str, ontology: dict
    ) -> tuple[list[dict], list[dict]]:
        raw = await self._call_llm([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"{self._ontology_prompt(ontology)}\n\n"
                    f"Extract entities and relations from:\n\n{text_chunk}"
                ),
            },
        ])
        result = self._parse_json(raw)
        if isinstance(result, dict):
            return self._validate_extraction(
                result.get("entities") or [],
                result.get("relations") or [],
                ontology,
            )
        return [], []

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    async def build_async(
        self,
        seed_text: str,
        graph_id: str,
        chunk_size: int = 1000,
        progress_cb: Callable[[int, str], None] | None = None,
    ) -> GraphInfo:
        """
        Full async pipeline: seed_text → chunks → ontology → triples → Graphiti.

        Args:
            seed_text:   Raw text to process.
            graph_id:    Unique graph identifier (used as Graphiti group_id).
            chunk_size:  max_characters hint passed to UnstructuredChunker.
            progress_cb: Optional callback(percent: int, message: str).
        """

        def _cb(pct: int, msg: str) -> None:
            if progress_cb:
                try:
                    progress_cb(pct, msg)
                except Exception:
                    pass
            logger.info("[GraphBuilder %s] %d%% — %s", graph_id, pct, msg)

        _cb(0, "Starting graph build")

        # 1. Chunk text with UnstructuredChunker
        _cb(5, "Chunking seed text")
        cfg = ChunkerConfig(
            strategy=self._chunker_config.strategy,
            max_characters=chunk_size,
            new_after_n_chars=int(chunk_size * 0.8),
            overlap=self._chunker_config.overlap,
            overlap_all=self._chunker_config.overlap_all,
            combine_text_under_n_chars=self._chunker_config.combine_text_under_n_chars,
        )
        chunker = UnstructuredChunker(cfg)
        chunk_objs = chunker.chunk_text(seed_text)
        chunks = [c.text for c in chunk_objs]
        if not chunks:
            chunks = [seed_text]
        _cb(10, f"Text split into {len(chunks)} chunk(s) via {cfg.strategy.value} strategy")

        # 2. Generate ontology from first chunk
        _cb(15, "Generating ontology")
        ontology = await self.generate_ontology(chunks[0])
        _cb(20, f"Ontology: {[i['name'] for i in ontology.get('entity_types', [])]}")

        # 3. Extract triples per chunk
        all_entities: list[dict] = []
        all_relations: list[dict] = []
        total = len(chunks)
        for idx, chunk in enumerate(chunks):
            entities, relations = await self.extract_triples(chunk, ontology)
            all_entities.extend(entities)
            all_relations.extend(relations)
            pct = 20 + int((idx + 1) / total * 40)
            _cb(pct, f"Chunk {idx + 1}/{total}: +{len(entities)} entities, +{len(relations)} relations")

        _cb(60, f"Extraction done: {len(all_entities)} entities, {len(all_relations)} relations")

        # 4. Build node/edge lists for GraphInfo
        entity_types = list({e.get("kind", "entity") for e in all_entities if e.get("kind")})
        node_lookup: dict[str, dict] = {}
        for idx, entity in enumerate(all_entities):
            name = (entity.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key not in node_lookup:
                node_lookup[key] = {
                    "id": str(entity.get("id") or f"entity_{idx}"),
                    "label": name,
                    "kind": entity.get("kind", "entity"),
                    "summary": entity.get("description", ""),
                }

        edges: list[dict] = []
        for idx, relation in enumerate(all_relations):
            src_name = (relation.get("source") or "").strip()
            tgt_name = (relation.get("target") or "").strip()
            if not src_name or not tgt_name:
                continue
            src = node_lookup.get(src_name.lower())
            tgt = node_lookup.get(tgt_name.lower())
            if not src or not tgt:
                continue
            edges.append({
                "id": f"rel_{idx}",
                "source": src["id"],
                "target": tgt["id"],
                "relation": relation.get("description") or relation.get("relation", "related"),
                "relation_type": relation.get("relation", "related_to"),
                "value": max(float(relation.get("confidence", 0.5) or 0.5) * 2, 1),
            })

        info = GraphInfo(
            graph_id=graph_id,
            node_count=len(node_lookup),
            edge_count=len(edges),
            entity_types=entity_types,
            nodes=list(node_lookup.values()),
            edges=edges,
        )

        # 5. Ingest into Graphiti / persist readable snapshot
        if self._graphiti_space is not None and self._graphiti_space._ready:
            graphiti = self._graphiti_space._graphiti
            group_id = graph_id
            ingest_ok = False

            episode_text = _build_fact_episode(all_entities, all_relations)
            safe_body = episode_text[:3000] + "\n[truncated]" if len(episode_text) > 3000 else episode_text

            try:
                await graphiti.add_episode(
                    name=f"extraction_{graph_id}",
                    episode_body=safe_body,
                    reference_time=datetime.now(timezone.utc),
                    source_description="Structured entity and relation facts",
                    group_id=group_id,
                )
                ingest_ok = True
                _cb(80, "Entities and relations ingested into Neo4j")
            except OSError as exc:
                if exc.errno == 36:
                    _cb(80, "Warning: skipped ingest (episode body too long)")
                else:
                    _cb(80, f"Warning: ingest skipped ({exc})")
            except Exception as exc:
                _cb(80, f"Warning: ingest partial ({exc})")

            try:
                await self._graphiti_space.apply_ontology_metadata(
                    entities=all_entities,
                    relations=all_relations,
                )
                _cb(85, "Ontology metadata synced to Neo4j")
            except Exception as exc:
                _cb(85, f"Warning: ontology sync skipped ({exc})")
            snapshot = await self._graphiti_space.get_graph_snapshot()
            if not snapshot.get("nodes") and not snapshot.get("edges"):
                _cb(90, "Graphiti snapshot empty, persisting extracted graph directly")
                snapshot = await self._graphiti_space.replace_graph_from_extraction(
                    nodes=list(node_lookup.values()),
                    edges=edges,
                )
            elif not ingest_ok:
                _cb(90, "Graphiti ingest degraded but snapshot is readable")

            if snapshot.get("nodes") or snapshot.get("edges"):
                _cb(95, "Graph snapshot is readable")
                info.nodes = snapshot.get("nodes") or info.nodes
                info.edges = snapshot.get("edges") or info.edges
                info.node_count = len(info.nodes)
                info.edge_count = len(info.edges)
                info.entity_types = list(
                    {
                        str(node.get("kind") or "entity")
                        for node in info.nodes
                        if isinstance(node, dict)
                    }
                )
            else:
                raise RuntimeError("graph snapshot unavailable after persistence")
        else:
            _cb(80, "Graphiti not available — skipping Neo4j ingest")

        _cb(100, f"Done — {info.node_count} nodes, {info.edge_count} edges")
        return info
