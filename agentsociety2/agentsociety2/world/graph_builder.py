"""
GraphBuilder: Assemble extracted world elements into a coherent WorldState.

职责：
- 把抽取结果 (ExtractionResult) 装配成初始 WorldState
- 调用 LLM 做实体去重/合并和关系补全
- 生成 AgentState for each persona entity
"""

from __future__ import annotations

from typing import Dict, List, Optional

from agentsociety2.config import get_llm_router_and_model, extract_json
from agentsociety2.logger import get_logger
from agentsociety2.world.extraction import ExtractionResult
from agentsociety2.world.models import (
    AgentState,
    Entity,
    GlobalVariable,
    Persona,
    Relation,
    WorldEvent,
    WorldState,
)
from agentsociety2.world.prompts import GRAPH_ASSEMBLY_PROMPT

__all__ = ["GraphBuilder"]


class GraphBuilder:
    """
    Assemble a coherent WorldState from extraction results and generated personas.
    """

    def __init__(self, allow_inferred_entities: bool = True):
        self.allow_inferred_entities = allow_inferred_entities
        self._llm_router, self._model_name = get_llm_router_and_model("default")
        self._logger = get_logger()

    async def build(
        self,
        world_id: str,
        world_name: str,
        extraction: ExtractionResult,
        actor_entity_ids: Optional[List[str]],
        personas: List[Persona],
        assumptions: Optional[List[str]] = None,
    ) -> WorldState:
        """
        Build the initial WorldState from extraction results and personas.

        Args:
            world_id: Unique world identifier.
            world_name: Display name for the world.
            extraction: Result from WorldExtractor.
            personas: List of generated Persona objects.
            assumptions: Optional explicit assumptions about the world.

        Returns:
            Fully assembled WorldState.
        """
        entities = list(extraction.entities)
        relations = list(extraction.relations)
        events = list(extraction.events)
        global_variables = list(extraction.global_variables)

        # Optionally run LLM graph-cleanup pass (merge duplicates, add implied relations)
        if self.allow_inferred_entities and (entities or relations):
            entities, relations = await self._run_graph_cleanup(entities, relations)

        # Build AgentState for every entity that has a persona
        persona_entity_ids = {p.entity_id for p in personas}
        agent_states: List[AgentState] = []
        for p in personas:
            entity = next((e for e in entities if e.id == p.entity_id), None)
            initial_goal = p.goals[0] if p.goals else None
            agent_states.append(
                AgentState(
                    entity_id=p.entity_id,
                    current_goal=initial_goal,
                    recent_memories=list(p.memory_seeds),
                    status="active",
                )
            )

        world = WorldState(
            world_id=world_id,
            name=world_name,
            entities=entities,
            relations=relations,
            actor_entity_ids=list(actor_entity_ids or []),
            personas=personas,
            agent_states=agent_states,
            global_variables=global_variables,
            timeline=events,
            assumptions=assumptions or [],
            build_summary=extraction.build_summary,
            current_tick=0,
            snapshot_version=0,
        )

        self._logger.info(
            f"GraphBuilder: built world '{world_name}' — "
            f"{len(entities)} entities, {len(relations)} relations, "
            f"{len(actor_entity_ids or [])} actors, {len(personas)} personas, {len(events)} seed events"
        )

        return world

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_graph_cleanup(
        self,
        entities: List[Entity],
        relations: List[Relation],
    ) -> tuple[List[Entity], List[Relation]]:
        """Ask LLM to identify duplicates and suggest implied relations."""
        entity_summary = "\n".join(
            f"- [{e.id}] {e.name} ({e.entity_type}): {e.description[:80]}"
            for e in entities[:100]
        )
        relation_summary = "\n".join(
            f"- {r.source_entity_id} → {r.target_entity_id}: {r.relation_type}"
            for r in relations[:200]
        )

        prompt = GRAPH_ASSEMBLY_PROMPT.format(
            entities_summary=entity_summary,
            relations_summary=relation_summary,
        )

        try:
            response = await self._llm_router.acompletion(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.choices[0].message.content or ""
            parsed = extract_json(raw)
            if not parsed:
                return entities, relations

            # Apply entity merges
            merges: Dict[str, str] = {}
            for m in parsed.get("entity_merges", []):
                keep_name = m.get("keep", "").lower()
                remove_name = m.get("merge", "").lower()
                keep_id = next(
                    (e.id for e in entities if e.name.lower() == keep_name), None
                )
                remove_id = next(
                    (e.id for e in entities if e.name.lower() == remove_name), None
                )
                if keep_id and remove_id and keep_id != remove_id:
                    merges[remove_id] = keep_id

            # Remove merged entities
            entities = [e for e in entities if e.id not in merges]

            # Remap relation IDs
            for r in relations:
                if r.source_entity_id in merges:
                    r.source_entity_id = merges[r.source_entity_id]
                if r.target_entity_id in merges:
                    r.target_entity_id = merges[r.target_entity_id]

            # Add additional inferred relations
            entity_name_to_id = {e.name.lower(): e.id for e in entities}
            for raw_rel in parsed.get("additional_relations", [])[:5]:
                src_name = raw_rel.get("source_entity_name", "").lower()
                tgt_name = raw_rel.get("target_entity_name", "").lower()
                src_id = entity_name_to_id.get(src_name)
                tgt_id = entity_name_to_id.get(tgt_name)
                if src_id and tgt_id:
                    new_rel = Relation(
                        source_entity_id=src_id,
                        target_entity_id=tgt_id,
                        relation_type=raw_rel.get("relation_type", "related"),
                        strength=float(raw_rel.get("strength", 0.5)),
                        polarity=raw_rel.get("polarity", "neutral"),
                        description=raw_rel.get("description", "(inferred)"),
                    )
                    relations.append(new_rel)

        except Exception as e:
            self._logger.warning(f"GraphBuilder: graph cleanup failed: {e}")

        return entities, relations
