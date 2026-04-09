"""
Extraction: LLM-driven pipeline to extract world knowledge from seed materials.

职责：
- 调用 LLM 从 seed materials 中抽取实体、关系、事件、约束、全局变量
- 生成可审计的 ExtractedFact 列表
- 返回结构化抽取结果（entities, relations, events 等）
"""

from __future__ import annotations

import ast
import json
from typing import Any, Dict, List, Optional, Tuple

from agentsociety2.config import get_llm_router_and_model, extract_json
from agentsociety2.logger import get_logger
from agentsociety2.world.models import (
    Entity,
    ExtractedFact,
    GlobalVariable,
    Relation,
    SeedMaterial,
    WorldEvent,
)
from agentsociety2.world.prompts import (
    ACTIONABLE_ENTITY_SUPPLEMENT_SYSTEM_PROMPT,
    ACTIONABLE_ENTITY_SUPPLEMENT_USER_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT,
)
from agentsociety2.world.seed_ingest import SeedIngest

__all__ = ["ExtractionResult", "WorldExtractor"]


_ACTIONABLE_ENTITY_TYPES = {"person", "organization", "group", "media"}
_MIN_ACTIONABLE_ENTITIES = 6


class ExtractionResult:
    """Container for all extraction outputs."""

    def __init__(
        self,
        entities: List[Entity],
        relations: List[Relation],
        events: List[WorldEvent],
        global_variables: List[GlobalVariable],
        facts: List[ExtractedFact],
        build_summary: str = "",
        raw_llm_output: Optional[str] = None,
    ):
        self.entities = entities
        self.relations = relations
        self.events = events
        self.global_variables = global_variables
        self.facts = facts
        self.build_summary = build_summary
        self.raw_llm_output = raw_llm_output


class WorldExtractor:
    """
    Runs the LLM extraction pipeline over seed materials.

    Produces structured world elements (Entity, Relation, etc.) and
    auditable ExtractedFact records.
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._llm_router, self._model_name = get_llm_router_and_model("default")
        self._logger = get_logger()
        self._ingest = SeedIngest()

    async def extract(
        self,
        seed_materials: List[SeedMaterial],
        world_goal: str = "",
        constraints: Optional[List[str]] = None,
    ) -> ExtractionResult:
        """
        Run extraction over the provided seed materials.

        Args:
            seed_materials: List of ingested SeedMaterial objects.
            world_goal: Optional high-level goal for the world.
            constraints: Optional list of world constraints.

        Returns:
            ExtractionResult with all extracted world elements.
        """
        seed_text = self._ingest.to_text_block(seed_materials)
        constraints_text = (
            "\n".join(f"- {c}" for c in constraints) if constraints else "(none)"
        )

        prompt = EXTRACTION_USER_PROMPT.format(
            seed_materials_text=seed_text,
            world_goal=world_goal or "(not specified)",
            constraints=constraints_text,
        )

        raw_output: Optional[str] = None
        parsed: Optional[Dict[str, Any]] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self._llm_router.acompletion(
                    model=self._model_name,
                    messages=[
                        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                )
                raw_output = response.choices[0].message.content or ""
                json_text = extract_json(raw_output)
                parsed = self._parse_extraction_json(json_text)
                if parsed:
                    break
                self._logger.warning(
                    f"WorldExtractor: attempt {attempt} failed to parse JSON"
                )
            except Exception as e:
                self._logger.error(f"WorldExtractor: LLM call failed (attempt {attempt}): {e}")

        if not parsed:
            self._logger.error("WorldExtractor: All extraction attempts failed; returning empty result")
            return ExtractionResult([], [], [], [], [], raw_llm_output=raw_output)

        result = self._build_result(parsed, seed_materials, raw_output or "")

        if self._count_actionable_entities(result.entities) < _MIN_ACTIONABLE_ENTITIES:
            await self._supplement_actionable_entities(
                result=result,
                seed_text=seed_text,
                world_goal=world_goal or "(not specified)",
            )

        return result

    def _parse_extraction_json(self, json_text: Optional[str]) -> Optional[Dict[str, Any]]:
        if not json_text:
            return None
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(json_text)
            except (ValueError, SyntaxError):
                return None
        return parsed if isinstance(parsed, dict) else None

    # ------------------------------------------------------------------
    # Internal parsers
    # ------------------------------------------------------------------

    def _build_result(
        self,
        parsed: Dict[str, Any],
        seed_materials: List[SeedMaterial],
        raw_output: str,
    ) -> ExtractionResult:
        primary_seed_id = seed_materials[0].id if seed_materials else "unknown"
        facts: List[ExtractedFact] = []

        # --- Entities ---
        entities: List[Entity] = []
        entity_name_to_id: Dict[str, str] = {}
        for raw in parsed.get("entities", []):
            ent = Entity(
                name=raw.get("name", "unknown"),
                entity_type=self._normalize_entity_type(
                    raw.get("entity_type", "other"),
                    raw.get("name", "unknown"),
                    raw.get("description", ""),
                ),
                aliases=raw.get("aliases", []),
                description=raw.get("description", ""),
                attributes=raw.get("attributes", {}),
            )
            entities.append(ent)
            entity_name_to_id[ent.name.lower()] = ent.id
            # Record fact
            facts.append(
                ExtractedFact(
                    fact_type="entity",
                    content=f"{ent.name}: {ent.description}",
                    source_material_id=primary_seed_id,
                )
            )

        # --- Relations ---
        relations: List[Relation] = []
        for raw in parsed.get("relations", []):
            src_name = raw.get("source_entity_name", "")
            tgt_name = raw.get("target_entity_name", "")
            src_id = entity_name_to_id.get(src_name.lower())
            tgt_id = entity_name_to_id.get(tgt_name.lower())
            if not src_id or not tgt_id:
                # Create stub entities for unresolved names
                if src_name and not src_id:
                    e = Entity(
                        name=src_name,
                        entity_type=self._normalize_entity_type("other", src_name, ""),
                    )
                    entities.append(e)
                    entity_name_to_id[src_name.lower()] = e.id
                    src_id = e.id
                if tgt_name and not tgt_id:
                    e = Entity(
                        name=tgt_name,
                        entity_type=self._normalize_entity_type("other", tgt_name, ""),
                    )
                    entities.append(e)
                    entity_name_to_id[tgt_name.lower()] = e.id
                    tgt_id = e.id
                if not src_id or not tgt_id:
                    continue
            rel = Relation(
                source_entity_id=src_id,
                target_entity_id=tgt_id,
                relation_type=raw.get("relation_type", "related"),
                strength=float(raw.get("strength", 0.5)),
                polarity=raw.get("polarity", "neutral"),
                description=raw.get("description", ""),
            )
            relations.append(rel)
            facts.append(
                ExtractedFact(
                    fact_type="relation",
                    content=f"{src_name} → {tgt_name}: {rel.relation_type}",
                    source_material_id=primary_seed_id,
                )
            )

        # --- Events ---
        events: List[WorldEvent] = []
        for raw in parsed.get("events", []):
            participant_names: List[str] = raw.get("participants", [])
            participant_ids = [
                entity_name_to_id.get(n.lower(), n) for n in participant_names
            ]
            evt = WorldEvent(
                tick=0,
                event_type=raw.get("event_type", "general"),
                title=raw.get("title", "Unnamed Event"),
                description=raw.get("description", ""),
                participants=participant_ids,
                created_by="seed",
            )
            events.append(evt)
            facts.append(
                ExtractedFact(
                    fact_type="event",
                    content=evt.title,
                    source_material_id=primary_seed_id,
                )
            )

        # --- Global Variables ---
        global_variables: List[GlobalVariable] = []
        for raw in parsed.get("global_variables", []):
            gv = GlobalVariable(
                name=raw.get("name", "unknown"),
                value=raw.get("value", None),
                description=raw.get("description", ""),
            )
            global_variables.append(gv)

        build_summary = parsed.get("build_summary", "")

        return ExtractionResult(
            entities=entities,
            relations=relations,
            events=events,
            global_variables=global_variables,
            facts=facts,
            build_summary=build_summary,
            raw_llm_output=raw_output,
        )

    def _normalize_entity_type(self, raw_type: str, name: str, description: str) -> str:
        normalized = str(raw_type or "other").strip().lower()
        if normalized not in {"person", "organization", "group", "media", "location", "concept", "other"}:
            normalized = "other"
        return normalized

    def _count_actionable_entities(self, entities: List[Entity]) -> int:
        return sum(1 for entity in entities if entity.entity_type in _ACTIONABLE_ENTITY_TYPES)

    async def _supplement_actionable_entities(
        self,
        result: ExtractionResult,
        seed_text: str,
        world_goal: str,
    ) -> None:
        entity_lines = [
            f"- {entity.name} ({entity.entity_type}): {entity.description[:120]}"
            for entity in result.entities[:80]
        ]
        entity_summary = "\n".join(entity_lines) if entity_lines else "(none)"

        entity_name_map = {entity.id: entity.name for entity in result.entities}
        relation_lines = [
            (
                f"- {entity_name_map.get(relation.source_entity_id, relation.source_entity_id)}"
                f" -> {entity_name_map.get(relation.target_entity_id, relation.target_entity_id)}:"
                f" {relation.relation_type} ({relation.description[:80]})"
            )
            for relation in result.relations[:120]
        ]
        relation_summary = "\n".join(relation_lines) if relation_lines else "(none)"

        prompt = ACTIONABLE_ENTITY_SUPPLEMENT_USER_PROMPT.format(
            seed_materials_text=seed_text,
            world_goal=world_goal,
            entities_summary=entity_summary,
            relations_summary=relation_summary,
        )

        try:
            response = await self._llm_router.acompletion(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": ACTIONABLE_ENTITY_SUPPLEMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = response.choices[0].message.content or ""
            parsed = self._parse_extraction_json(extract_json(raw))
            if not parsed:
                return
            self._merge_actionable_supplement(result, parsed)
        except Exception as exc:
            self._logger.warning("WorldExtractor: actor supplement failed: %s", exc)

    def _merge_actionable_supplement(
        self,
        result: ExtractionResult,
        parsed: Dict[str, Any],
    ) -> None:
        name_to_entity = {entity.name.strip().lower(): entity for entity in result.entities}
        alias_to_name = {
            alias.strip().lower(): entity.name.strip().lower()
            for entity in result.entities
            for alias in entity.aliases
            if alias.strip()
        }

        def _resolve_entity(name: str) -> Optional[Entity]:
            key = name.strip().lower()
            if not key:
                return None
            entity = name_to_entity.get(key)
            if entity is not None:
                return entity
            canonical = alias_to_name.get(key)
            return name_to_entity.get(canonical) if canonical else None

        for raw in parsed.get("entities", []):
            name = str(raw.get("name") or "").strip()
            if not name or _resolve_entity(name) is not None:
                continue
            entity_type = self._normalize_entity_type(
                raw.get("entity_type", "other"),
                name,
                raw.get("description", ""),
            )
            if entity_type not in _ACTIONABLE_ENTITY_TYPES:
                continue
            entity = Entity(
                name=name,
                entity_type=entity_type,
                aliases=raw.get("aliases", []),
                description=raw.get("description", ""),
                attributes=raw.get("attributes", {}),
            )
            result.entities.append(entity)
            name_to_entity[name.lower()] = entity
            for alias in entity.aliases:
                alias_key = str(alias).strip().lower()
                if alias_key:
                    alias_to_name[alias_key] = name.lower()

        existing_relation_keys = {
            (relation.source_entity_id, relation.target_entity_id, relation.relation_type.strip().lower())
            for relation in result.relations
        }

        for raw in parsed.get("relations", []):
            src_name = str(raw.get("source_entity_name") or "").strip()
            tgt_name = str(raw.get("target_entity_name") or "").strip()
            relation_type = str(raw.get("relation_type") or "related").strip()
            src_entity = _resolve_entity(src_name)
            tgt_entity = _resolve_entity(tgt_name)
            if src_entity is None or tgt_entity is None:
                continue
            key = (src_entity.id, tgt_entity.id, relation_type.lower())
            if key in existing_relation_keys:
                continue
            result.relations.append(
                Relation(
                    source_entity_id=src_entity.id,
                    target_entity_id=tgt_entity.id,
                    relation_type=relation_type,
                    strength=float(raw.get("strength", 0.5)),
                    polarity=raw.get("polarity", "neutral"),
                    description=str(raw.get("description") or ""),
                )
            )
            existing_relation_keys.add(key)
