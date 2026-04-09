"""
WorldStateManager: Manage the live world graph, global state, and event timeline.

职责：
- 管理 WorldState 的内存表示
- 提供增删改查方法（entities, relations, events, global variables）
- 生成快照 (snapshot)
- 推进 tick
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Dict, List, Optional

from agentsociety2.logger import get_logger
from agentsociety2.world.models import (
    AgentState,
    Entity,
    GlobalVariable,
    Intervention,
    Persona,
    Relation,
    WorldEvent,
    WorldState,
)

__all__ = ["WorldStateManager"]


class WorldStateManager:
    """
    In-memory manager for a single WorldState.
    Provides mutation methods and snapshot generation.
    """

    def __init__(self, world_state: WorldState):
        self._state = world_state
        self._logger = get_logger()

        # Build fast lookup indices
        self._entity_index: Dict[str, Entity] = {
            e.id: e for e in self._state.entities
        }
        self._relation_index: Dict[str, Relation] = {
            r.id: r for r in self._state.relations
        }
        self._persona_index: Dict[str, Persona] = {
            p.entity_id: p for p in self._state.personas
        }
        self._agent_state_index: Dict[str, AgentState] = {
            a.entity_id: a for a in self._state.agent_states
        }
        self._global_var_index: Dict[str, GlobalVariable] = {
            g.name: g for g in self._state.global_variables
        }

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def world_id(self) -> str:
        return self._state.world_id

    @property
    def current_tick(self) -> int:
        return self._state.current_tick

    @property
    def entities(self) -> List[Entity]:
        return list(self._entity_index.values())

    @property
    def relations(self) -> List[Relation]:
        return list(self._relation_index.values())

    @property
    def personas(self) -> List[Persona]:
        return list(self._persona_index.values())

    @property
    def actor_entity_ids(self) -> List[str]:
        return list(self._state.actor_entity_ids)

    @property
    def agent_states(self) -> List[AgentState]:
        return list(self._agent_state_index.values())

    @property
    def active_agent_states(self) -> List[AgentState]:
        return [a for a in self._agent_state_index.values() if a.status == "active"]

    @property
    def timeline(self) -> List[WorldEvent]:
        return list(self._state.timeline)

    # ------------------------------------------------------------------
    # Tick management
    # ------------------------------------------------------------------

    def advance_tick(self) -> int:
        self._state.current_tick += 1
        self._state.updated_at = datetime.utcnow()
        return self._state.current_tick

    # ------------------------------------------------------------------
    # Entity operations
    # ------------------------------------------------------------------

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self._entity_index.get(entity_id)

    def add_entity(self, entity: Entity) -> None:
        self._entity_index[entity.id] = entity
        self._state.entities = list(self._entity_index.values())

    def update_entity_attribute(self, entity_id: str, key: str, value: Any) -> bool:
        entity = self._entity_index.get(entity_id)
        if not entity:
            return False
        entity.attributes[key] = value
        return True

    # ------------------------------------------------------------------
    # Relation operations
    # ------------------------------------------------------------------

    def get_relation(self, relation_id: str) -> Optional[Relation]:
        return self._relation_index.get(relation_id)

    def get_relations_for_entity(self, entity_id: str) -> List[Relation]:
        return [
            r
            for r in self._relation_index.values()
            if r.source_entity_id == entity_id or r.target_entity_id == entity_id
        ]

    def add_relation(self, relation: Relation) -> None:
        self._relation_index[relation.id] = relation
        self._state.relations = list(self._relation_index.values())

    def update_relation_strength(
        self, source_id: str, target_id: str, delta: float
    ) -> bool:
        for r in self._relation_index.values():
            if r.source_entity_id == source_id and r.target_entity_id == target_id and r.mutable:
                r.strength = max(0.0, min(1.0, r.strength + delta))
                r.updated_at = datetime.utcnow()
                return True
        return False

    def update_relation_polarity(
        self, source_id: str, target_id: str, polarity: str
    ) -> bool:
        for r in self._relation_index.values():
            if r.source_entity_id == source_id and r.target_entity_id == target_id and r.mutable:
                r.polarity = polarity  # type: ignore
                r.updated_at = datetime.utcnow()
                return True
        return False

    # ------------------------------------------------------------------
    # Event operations
    # ------------------------------------------------------------------

    def add_event(self, event: WorldEvent) -> None:
        self._state.timeline.append(event)

    def get_recent_events(
        self, limit: int = 20, after_tick: int = -1, event_type: Optional[str] = None
    ) -> List[WorldEvent]:
        events = self._state.timeline
        if after_tick >= 0:
            events = [e for e in events if e.tick > after_tick]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]

    # ------------------------------------------------------------------
    # Agent state operations
    # ------------------------------------------------------------------

    def get_agent_state(self, entity_id: str) -> Optional[AgentState]:
        return self._agent_state_index.get(entity_id)

    def update_agent_state(self, state: AgentState) -> None:
        self._agent_state_index[state.entity_id] = state
        self._state.agent_states = list(self._agent_state_index.values())

    def add_agent_memory(self, entity_id: str, memory: str) -> None:
        state = self._agent_state_index.get(entity_id)
        if state:
            state.recent_memories.append(memory)
            if len(state.recent_memories) > 50:
                state.recent_memories = state.recent_memories[-50:]

    # ------------------------------------------------------------------
    # Global variable operations
    # ------------------------------------------------------------------

    def get_global_variable(self, name: str) -> Optional[GlobalVariable]:
        return self._global_var_index.get(name)

    def set_global_variable(self, name: str, value: Any, description: str = "") -> None:
        if name in self._global_var_index:
            gv = self._global_var_index[name]
            gv.value = value
            gv.updated_at = datetime.utcnow()
        else:
            gv = GlobalVariable(name=name, value=value, description=description)
            self._global_var_index[name] = gv
        self._state.global_variables = list(self._global_var_index.values())

    # ------------------------------------------------------------------
    # Intervention application
    # ------------------------------------------------------------------

    def apply_intervention(self, intervention: Intervention) -> None:
        """Apply an external intervention to the world state."""
        intervention.applied_at_tick = self._state.current_tick
        payload = intervention.payload
        itype = intervention.intervention_type

        if itype == "global_variable_change":
            for k, v in payload.items():
                self.set_global_variable(k, v)
        elif itype == "relation_strength_change":
            src_id = payload.get("source_entity_id", "")
            tgt_id = payload.get("target_entity_id", "")
            delta = float(payload.get("delta", 0.0))
            self.update_relation_strength(src_id, tgt_id, delta)
        elif itype == "relation_polarity_change":
            src_id = payload.get("source_entity_id", "")
            tgt_id = payload.get("target_entity_id", "")
            polarity = payload.get("polarity", "neutral")
            self.update_relation_polarity(src_id, tgt_id, polarity)

        # Record intervention as an event
        event = WorldEvent(
            tick=self._state.current_tick,
            event_type="intervention",
            title=f"Intervention: {itype}",
            description=intervention.reason or str(payload),
            source_module="intervention",
            trigger_reason=intervention.reason or f"External intervention of type {itype}",
            created_by="intervention",
            payload=payload,
        )
        self.add_event(event)
        self._logger.info(
            f"WorldStateManager: applied intervention '{itype}' at tick {self._state.current_tick}"
        )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> WorldState:
        """Return a deep copy of the current world state."""
        self._state.snapshot_version += 1
        self._state.updated_at = datetime.utcnow()
        return copy.deepcopy(self._state)

    def build_world_summary(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Return a structured summary for agent-facing world observation."""
        global_variables = {
            g.name: g.value
            for g in self._global_var_index.values()
        }
        result: Dict[str, Any] = {
            "world_id": self.world_id,
            "world_name": self._state.name,
            "current_tick": self.current_tick,
            "entity_count": len(self.entities),
            "relation_count": len(self.relations),
            "active_agents": len(self.active_agent_states),
            "global_variables": global_variables,
            "build_summary": self._state.build_summary,
        }
        if agent_id:
            agent_state = self.get_agent_state(agent_id)
            if agent_state:
                result["my_status"] = agent_state.status
                result["my_goal"] = agent_state.current_goal
                result["my_resources"] = agent_state.resources
                result["my_alliances"] = agent_state.alliances
        return result

    def build_report_snapshot(
        self,
        entity_limit: int = 50,
        relation_limit: int = 100,
    ) -> Dict[str, Any]:
        """Return a structured summary for operator-side reporting."""
        entities = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.entity_type,
                "description": e.description[:100],
            }
            for e in self.entities[:entity_limit]
        ]
        relations = [
            {
                "source": r.source_entity_id,
                "target": r.target_entity_id,
                "type": r.relation_type,
                "strength": r.strength,
                "polarity": r.polarity,
            }
            for r in self.relations[:relation_limit]
        ]
        global_vars = {
            g.name: {"value": g.value, "description": g.description}
            for g in self._global_var_index.values()
        }
        return {
            "world_id": self.world_id,
            "world_name": self._state.name,
            "current_tick": self.current_tick,
            "entity_count": len(self.entities),
            "relation_count": len(self.relations),
            "timeline_event_count": len(self.timeline),
            "active_agents": len(self.active_agent_states),
            "entities": entities,
            "relations": relations,
            "global_variables": global_vars,
            "build_summary": self._state.build_summary,
            "assumptions": self._state.assumptions,
        }

    def build_relation_network(self) -> Dict[str, Any]:
        """Return the current full relation network."""
        name_map = {e.id: e.name for e in self.entities}
        nodes = [
            {"id": e.id, "name": e.name, "type": e.entity_type}
            for e in self.entities
        ]
        edges = [
            {
                "source": r.source_entity_id,
                "source_name": name_map.get(r.source_entity_id, r.source_entity_id),
                "target": r.target_entity_id,
                "target_name": name_map.get(r.target_entity_id, r.target_entity_id),
                "relation_type": r.relation_type,
                "strength": r.strength,
                "polarity": r.polarity,
            }
            for r in self.relations
        ]
        return {"nodes": nodes, "edges": edges}

    def build_agent_states_summary(self) -> List[Dict[str, Any]]:
        """Return summarized runtime state for all agents."""
        name_map = {e.id: e.name for e in self.entities}
        return [
            {
                "entity_id": a.entity_id,
                "name": name_map.get(a.entity_id, a.entity_id),
                "status": a.status,
                "current_goal": a.current_goal,
                "beliefs": a.beliefs,
                "emotions": a.emotions,
                "alliances": a.alliances,
                "recent_memories_count": len(a.recent_memories),
            }
            for a in self.agent_states
        ]

    def to_summary_text(self, max_events: int = 10) -> str:
        """Return a concise text summary of the world state (for LLM prompts)."""
        entity_lines = "\n".join(
            f"  - {e.name} ({e.entity_type}): {e.description[:80]}"
            for e in list(self._entity_index.values())[:30]
        )
        relation_lines = "\n".join(
            f"  - {r.source_entity_id} → {r.target_entity_id}: {r.relation_type} ({r.polarity}, strength={r.strength:.2f})"
            for r in list(self._relation_index.values())[:30]
        )
        recent_events = self.get_recent_events(limit=max_events)
        event_lines = "\n".join(
            f"  [tick {e.tick}] {e.title}: {e.description[:80]}"
            for e in recent_events
        )
        global_var_lines = "\n".join(
            f"  - {g.name} = {g.value} ({g.description})"
            for g in list(self._global_var_index.values())[:20]
        )
        narrative_direction = self.get_global_variable("narrative_direction")
        event_config = self.get_global_variable("event_config")
        hot_topics = []
        if event_config and isinstance(event_config.value, dict):
            hot_topics = list(event_config.value.get("hot_topics") or [])
        return (
            f"=== World: {self._state.name} (tick={self._state.current_tick}) ===\n\n"
            f"Narrative Direction: {narrative_direction.value if narrative_direction else '(none)'}\n"
            f"Hot Topics: {', '.join(hot_topics) if hot_topics else '(none)'}\n\n"
            f"Entities ({len(self._entity_index)}):\n{entity_lines or '  (none)'}\n\n"
            f"Relations ({len(self._relation_index)}):\n{relation_lines or '  (none)'}\n\n"
            f"Recent Events:\n{event_lines or '  (none)'}\n\n"
            f"Global Variables:\n{global_var_lines or '  (none)'}\n\n"
            f"Build Summary: {self._state.build_summary}"
        )
