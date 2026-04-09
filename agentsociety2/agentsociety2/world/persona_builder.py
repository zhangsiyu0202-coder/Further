"""
PersonaBuilder: Generate rich agent personas from extracted world entities.

职责：
- 根据实体信息和 seed materials 生成 Persona
- 区分不同类型实体（个人、机构、群体、媒体等）
- 批量生成，并在实体无 LLM persona 时提供规则兜底
"""

from __future__ import annotations

import ast
import json
from typing import Dict, List, Optional

from agentsociety2.config import get_llm_router_and_model, extract_json
from agentsociety2.logger import get_logger
from agentsociety2.world.models import Entity, Persona, Relation
from agentsociety2.world.prompts import PERSONA_GENERATION_PROMPT

__all__ = ["PersonaBuilder"]


class PersonaBuilder:
    """Build Persona objects for world entities using LLM + rules."""

    def __init__(self, max_agents: int = 50):
        self.max_agents = max_agents
        self._llm_router, self._model_name = get_llm_router_and_model("default")
        self._logger = get_logger()

    async def build_all(
        self,
        entities: List[Entity],
        relations: List[Relation],
        world_context: str = "",
        target_entity_types: Optional[List[str]] = None,
        target_entity_ids: Optional[List[str]] = None,
    ) -> List[Persona]:
        """
        Generate personas for a list of entities.

        Args:
            entities: All world entities.
            relations: All world relations (used for world context).
            world_context: Text summary of the world for context.
            target_entity_types: If specified, only generate personas for these types.
                                  Default: person, organization, group, media

        Returns:
            List of generated Persona objects.
        """
        if target_entity_types is None:
            target_entity_types = ["person", "organization", "group", "media"]

        allowed_ids = {entity_id for entity_id in (target_entity_ids or []) if entity_id}
        candidates = [
            e
            for e in entities
            if e.entity_type in target_entity_types and (not allowed_ids or e.id in allowed_ids)
        ][: self.max_agents]

        if not candidates:
            self._logger.warning("PersonaBuilder: no eligible entities found")
            return []

        # Build relation summary for context
        rel_summary = self._build_relation_summary(candidates, relations)
        full_context = f"{world_context}\n\nKey Relations:\n{rel_summary}" if world_context else rel_summary

        personas: List[Persona] = []
        for entity in candidates:
            persona = await self._generate_persona(entity, full_context)
            personas.append(persona)

        self._logger.info(f"PersonaBuilder: generated {len(personas)} personas")
        return personas

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _generate_persona(self, entity: Entity, world_context: str) -> Persona:
        """Generate a single Persona via LLM with rule-based fallback."""
        prompt = PERSONA_GENERATION_PROMPT.format(
            entity_name=entity.name,
            entity_type=entity.entity_type,
            entity_description=entity.description or "(no description provided)",
            entity_attributes=str(entity.attributes) if entity.attributes else "(none)",
            world_context=world_context[:2000],  # trim to avoid huge prompts
        )

        try:
            response = await self._llm_router.acompletion(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.choices[0].message.content or ""
            parsed = self._parse_persona_json(extract_json(raw))
            if parsed:
                return self._from_parsed(entity.id, parsed)
        except Exception as e:
            self._logger.error(
                f"PersonaBuilder: LLM failed for entity '{entity.name}': {e}"
            )

        # Fallback: rule-based persona
        return self._rule_based_persona(entity)

    def _from_parsed(self, entity_id: str, parsed: dict) -> Persona:
        return Persona(
            entity_id=entity_id,
            identity_summary=parsed.get("identity_summary", ""),
            goals=parsed.get("goals", []),
            fears=parsed.get("fears", []),
            preferences=parsed.get("preferences", []),
            stance_map=parsed.get("stance_map", {}),
            behavior_style=parsed.get("behavior_style", ""),
            speech_style=parsed.get("speech_style", ""),
            memory_seeds=parsed.get("memory_seeds", []),
        )

    def _rule_based_persona(self, entity: Entity) -> Persona:
        """Minimal persona derived from entity attributes without LLM."""
        kind = entity.entity_type
        goals_by_kind: Dict[str, List[str]] = {
            "person": ["maintain relationships", "achieve personal goals", "survive and thrive"],
            "organization": ["grow influence", "protect assets", "achieve strategic objectives"],
            "group": ["advance collective interests", "recruit members", "gain recognition"],
            "media": ["reach wider audience", "report accurately", "maintain credibility"],
            "other": ["pursue objectives", "adapt to circumstances"],
        }
        return Persona(
            entity_id=entity.id,
            identity_summary=entity.description or f"{entity.name} is a {kind} in this world.",
            goals=goals_by_kind.get(kind, goals_by_kind["other"]),
            fears=["failure", "loss of influence"],
            preferences=[],
            stance_map={},
            behavior_style="neutral",
            speech_style="neutral",
            memory_seeds=[],
        )

    def _parse_persona_json(self, json_text: Optional[str]) -> Optional[dict]:
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

    def _build_relation_summary(
        self,
        entities: List[Entity],
        relations: List[Relation],
    ) -> str:
        """Build a brief text summary of relations among the given entities."""
        entity_ids = {e.id for e in entities}
        name_map = {e.id: e.name for e in entities}
        lines: List[str] = []
        for r in relations:
            if r.source_entity_id in entity_ids or r.target_entity_id in entity_ids:
                src = name_map.get(r.source_entity_id, r.source_entity_id)
                tgt = name_map.get(r.target_entity_id, r.target_entity_id)
                lines.append(f"- {src} → {tgt}: {r.relation_type} ({r.polarity})")
        return "\n".join(lines[:50]) if lines else "(no relations)"
