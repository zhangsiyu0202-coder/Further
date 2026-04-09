"""
SimulationInitBuilder: Turn a simulation goal into structured world-init context.

职责：
- 在 world init 阶段消费 simulation_goal
- 生成系统级初始化配置，而不是覆盖 agent 个人目标
- 将配置写入 global variables / initial events / assumptions / build summary
"""

from __future__ import annotations

import json
from typing import Any, List

from agentsociety2.config import extract_json, get_llm_router_and_model
from agentsociety2.logger import get_logger
from agentsociety2.world.models import GlobalVariable, WorldEvent, WorldState
from agentsociety2.world.prompts import SIMULATION_INIT_PROMPT
from agentsociety2.world.seed_ingest import SeedIngest

__all__ = ["SimulationInitBuilder"]


class SimulationInitBuilder:
    """Generate structured initialization context from simulation_goal."""

    def __init__(self):
        self._llm_router, self._model_name = get_llm_router_and_model("default")
        self._logger = get_logger()
        self._ingest = SeedIngest()

    async def apply(
        self,
        world_state: WorldState,
        simulation_goal: str,
        seed_materials: List[Any],
    ) -> WorldState:
        goal = simulation_goal.strip()
        if not goal:
            return world_state

        parsed = await self._generate_plan(world_state, goal, seed_materials)
        return self._apply_plan(world_state, goal, parsed)

    async def _generate_plan(
        self,
        world_state: WorldState,
        simulation_goal: str,
        seed_materials: List[Any],
    ) -> dict[str, Any]:
        seed_text = self._ingest.to_text_block(self._ingest.ingest(seed_materials))[:4000]
        entities_summary = "\n".join(
            f"- {entity.name} ({entity.entity_type}): {entity.description[:120]}"
            for entity in world_state.entities[:30]
        ) or "(none)"
        relations_summary = "\n".join(
            f"- {relation.source_entity_id} -> {relation.target_entity_id}: {relation.relation_type} ({relation.polarity})"
            for relation in world_state.relations[:40]
        ) or "(none)"
        world_summary = world_state.build_summary or "(no build summary)"

        prompt = SIMULATION_INIT_PROMPT.format(
            simulation_goal=simulation_goal,
            seed_materials_text=seed_text,
            world_summary=world_summary[:2000],
            entities_summary=entities_summary,
            relations_summary=relations_summary,
        )

        try:
            response = await self._llm_router.acompletion(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.choices[0].message.content or ""
            json_text = extract_json(raw)
            if json_text:
                parsed = json.loads(json_text)
                if isinstance(parsed, dict):
                    return parsed
        except Exception as exc:
            self._logger.warning("SimulationInitBuilder: LLM generation failed: %s", exc)

        return {}

    def _apply_plan(
        self,
        world_state: WorldState,
        simulation_goal: str,
        parsed: dict[str, Any],
    ) -> WorldState:
        name_map = {entity.name.lower(): entity.id for entity in world_state.entities}

        init_globals: List[GlobalVariable] = [
            GlobalVariable(
                name="simulation_goal",
                value=simulation_goal,
                description="System-level simulation goal used during world initialization.",
            )
        ]

        narrative_direction = str(parsed.get("narrative_direction") or "").strip()
        if narrative_direction:
            init_globals.append(
                GlobalVariable(
                    name="narrative_direction",
                    value=narrative_direction,
                    description="World-level narrative direction inferred from simulation goal.",
                )
            )

        time_config = parsed.get("time_config")
        if isinstance(time_config, dict):
            init_globals.append(
                GlobalVariable(
                    name="time_config",
                    value=time_config,
                    description="Simulation time configuration generated during world initialization.",
                )
            )

        event_config = parsed.get("event_config")
        if isinstance(event_config, dict):
            init_globals.append(
                GlobalVariable(
                    name="event_config",
                    value=event_config,
                    description="Simulation event configuration generated during world initialization.",
                )
            )

        agent_priorities = parsed.get("agent_priorities")
        if isinstance(agent_priorities, list):
            init_globals.append(
                GlobalVariable(
                    name="agent_priorities",
                    value=agent_priorities,
                    description="Entity-level attention priorities and activity biases for simulation runtime.",
                )
            )

        agent_activity_config = parsed.get("agent_activity_config")
        if isinstance(agent_activity_config, list):
            init_globals.append(
                GlobalVariable(
                    name="agent_activity_config",
                    value=agent_activity_config,
                    description="Entity-level runtime scheduling configuration for simulation activity.",
                )
            )

        extra_globals = parsed.get("global_variables", [])
        for raw in extra_globals:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            init_globals.append(
                GlobalVariable(
                    name=name,
                    value=raw.get("value"),
                    description=str(raw.get("description") or ""),
                )
            )

        merged_globals = {gv.name: gv for gv in world_state.global_variables}
        for gv in init_globals:
            merged_globals[gv.name] = gv
        world_state.global_variables = list(merged_globals.values())

        init_events: List[WorldEvent] = []
        init_events.append(
            WorldEvent(
                tick=0,
                event_type="simulation_context",
                title="Simulation goal initialized",
                description=simulation_goal,
                source_module="simulation_init",
                trigger_reason="Simulation init builder seeded the world with the requested goal.",
                created_by="system",
            )
        )

        if narrative_direction:
            init_events.append(
                WorldEvent(
                    tick=0,
                    event_type="narrative_setup",
                    title="Narrative direction established",
                    description=narrative_direction,
                    source_module="simulation_init",
                    trigger_reason="Narrative direction inferred from simulation_goal during world init.",
                    created_by="system",
                )
            )

        for raw in parsed.get("initial_events", []):
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            description = str(raw.get("description") or "").strip()
            if not title or not description:
                continue
            participant_ids = []
            for name in raw.get("participants", []) or []:
                entity_id = name_map.get(str(name).strip().lower())
                if entity_id:
                    participant_ids.append(entity_id)
            init_events.append(
                WorldEvent(
                    tick=0,
                    event_type=str(raw.get("event_type") or "simulation_seed"),
                    title=title,
                    description=description,
                    participants=participant_ids,
                    parent_event_id=init_events[0].id,
                    source_module="simulation_init",
                    trigger_reason="Structured initialization event generated from simulation_goal and seed materials.",
                    created_by="system",
                )
            )

        world_state.timeline.extend(init_events)

        assumptions = list(world_state.assumptions)
        assumptions.append(f"simulation_goal: {simulation_goal}")
        for raw in parsed.get("assumptions", []):
            text = str(raw).strip()
            if text and text not in assumptions:
                assumptions.append(text)
        world_state.assumptions = assumptions

        summary = str(parsed.get("summary") or "").strip()
        if summary:
            if world_state.build_summary:
                world_state.build_summary = (
                    f"{world_state.build_summary}\n\nSimulation Initialization:\n{summary}"
                )
            else:
                world_state.build_summary = summary

        if isinstance(agent_priorities, list):
            entity_map = {entity.name.lower(): entity for entity in world_state.entities}
            for raw in agent_priorities:
                if not isinstance(raw, dict):
                    continue
                entity_name = str(raw.get("entity_name") or "").strip().lower()
                if not entity_name:
                    continue
                entity = entity_map.get(entity_name)
                if not entity:
                    continue
                entity.attributes["simulation_priority_topics"] = [
                    str(topic).strip()
                    for topic in (raw.get("priority_topics") or [])
                    if str(topic).strip()
                ]
                entity.attributes["simulation_priority_targets"] = [
                    str(target).strip()
                    for target in (raw.get("priority_targets") or [])
                    if str(target).strip()
                ]
                activity_bias = str(raw.get("activity_bias") or "").strip()
                if activity_bias:
                    entity.attributes["simulation_activity_bias"] = activity_bias

        if isinstance(agent_activity_config, list):
            entity_map = {entity.name.lower(): entity for entity in world_state.entities}
            for raw in agent_activity_config:
                if not isinstance(raw, dict):
                    continue
                entity_name = str(raw.get("entity_name") or "").strip().lower()
                if not entity_name:
                    continue
                entity = entity_map.get(entity_name)
                if not entity:
                    continue

                activity_level = str(raw.get("activity_level") or "").strip().lower()
                if activity_level in {"low", "medium", "high"}:
                    entity.attributes["simulation_activity_level"] = activity_level

                active_hours = []
                for hour in raw.get("active_hours", []) or []:
                    if isinstance(hour, int) and 0 <= hour <= 23:
                        active_hours.append(hour)
                if active_hours:
                    entity.attributes["simulation_active_hours"] = sorted(set(active_hours))

                response_delay_ticks = raw.get("response_delay_ticks")
                if isinstance(response_delay_ticks, int) and response_delay_ticks >= 0:
                    entity.attributes["simulation_response_delay_ticks"] = response_delay_ticks

        return world_state
