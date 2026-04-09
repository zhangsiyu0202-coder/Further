"""
RelationGraphEnv: Provides agents with tools to query and update the world relation graph.

职责：
- 查询与自身相关的关系
- 更新关系强度
- 建立/断开联盟
- 记录支持/反对/敌意/依赖
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentsociety2.env.base import EnvBase, tool
from agentsociety2.world.models import Relation, WorldEvent

if TYPE_CHECKING:
    from agentsociety2.world.world_state import WorldStateManager

__all__ = ["RelationGraphEnv"]


class RelationGraphEnv(EnvBase):
    """
    Relation graph environment module.

    Lets agents query and modify their relationships with other world entities.
    """

    def __init__(self, world_manager: "WorldStateManager"):
        super().__init__()
        self._world = world_manager

    @property
    def description(self) -> str:
        return (
            "RelationGraphEnv: Tools for querying and updating relationship states "
            "between entities in the virtual world."
        )

    async def step(self, tick: int, t: datetime) -> None:
        self.t = t

    # ------------------------------------------------------------------
    # Read-only tools
    # ------------------------------------------------------------------

    @tool(readonly=True, kind="observe")
    def get_my_relations(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all relations involving this agent entity.

        Args:
            agent_id: The entity ID of the agent (required).

        Returns:
            List of relation dicts (id, source, target, type, strength, polarity).
        """
        if not agent_id:
            return [{"error": "agent_id is required"}]
        relations = self._world.get_relations_for_entity(agent_id)
        name_map = {e.id: e.name for e in self._world.entities}
        return [
            {
                "id": r.id,
                "source_entity_id": r.source_entity_id,
                "source_name": name_map.get(r.source_entity_id, r.source_entity_id),
                "target_entity_id": r.target_entity_id,
                "target_name": name_map.get(r.target_entity_id, r.target_entity_id),
                "relation_type": r.relation_type,
                "strength": r.strength,
                "polarity": r.polarity,
                "description": r.description,
            }
            for r in relations
        ]

    @tool(readonly=True, kind="observe")
    def get_all_relations(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all relations in the world (global view, read-only).

        Args:
            agent_id: Unused; present for API consistency.

        Returns:
            List of all relation dicts.
        """
        name_map = {e.id: e.name for e in self._world.entities}
        return [
            {
                "id": r.id,
                "source_name": name_map.get(r.source_entity_id, r.source_entity_id),
                "target_name": name_map.get(r.target_entity_id, r.target_entity_id),
                "relation_type": r.relation_type,
                "strength": r.strength,
                "polarity": r.polarity,
            }
            for r in self._world.relations
        ]

    # ------------------------------------------------------------------
    # Write tools
    # ------------------------------------------------------------------

    @tool(readonly=False)
    def update_relation_strength(
        self,
        source_entity_id: str,
        target_entity_id: str,
        delta: float,
    ) -> Dict[str, Any]:
        """
        Change the strength of a relation between two entities.

        Args:
            source_entity_id: Source entity ID.
            target_entity_id: Target entity ID.
            delta: Amount to add (positive) or subtract (negative) from current strength.
                   Clamped to [0.0, 1.0].

        Returns:
            Success status and new strength value.
        """
        success = self._world.update_relation_strength(
            source_entity_id, target_entity_id, delta
        )
        if success:
            relations = self._world.get_relations_for_entity(source_entity_id)
            new_strength = next(
                (
                    r.strength
                    for r in relations
                    if r.target_entity_id == target_entity_id
                ),
                None,
            )
            self._world.add_event(
                WorldEvent(
                    tick=self._world.current_tick,
                    event_type="relation_strength_change",
                    title=f"Relation strength updated: {source_entity_id} -> {target_entity_id}",
                    description=f"Strength delta {delta}, new strength {new_strength}.",
                    participants=[source_entity_id, target_entity_id],
                    source_entity_id=source_entity_id,
                    source_module="relation_graph",
                    trigger_reason=(
                        f"{source_entity_id} changed relation strength toward {target_entity_id} by {delta}."
                    ),
                    created_by="agent",
                    payload={"delta": delta, "new_strength": new_strength},
                )
            )
            return {"success": True, "new_strength": new_strength}
        return {"success": False, "reason": "Relation not found or not mutable"}

    @tool(readonly=False)
    def update_relation_polarity(
        self,
        source_entity_id: str,
        target_entity_id: str,
        polarity: str,
    ) -> Dict[str, Any]:
        """
        Change the polarity of a relation (positive / neutral / negative).

        Args:
            source_entity_id: Source entity ID.
            target_entity_id: Target entity ID.
            polarity: New polarity — must be 'positive', 'neutral', or 'negative'.

        Returns:
            Success status.
        """
        if polarity not in ("positive", "neutral", "negative"):
            return {"success": False, "reason": "polarity must be positive, neutral, or negative"}
        success = self._world.update_relation_polarity(
            source_entity_id, target_entity_id, polarity
        )
        if success:
            self._world.add_event(
                WorldEvent(
                    tick=self._world.current_tick,
                    event_type="relation_polarity_change",
                    title=f"Relation polarity updated: {source_entity_id} -> {target_entity_id}",
                    description=f"Polarity changed to {polarity}.",
                    participants=[source_entity_id, target_entity_id],
                    source_entity_id=source_entity_id,
                    source_module="relation_graph",
                    trigger_reason=(
                        f"{source_entity_id} changed relation polarity toward {target_entity_id} to {polarity}."
                    ),
                    created_by="agent",
                    payload={"polarity": polarity},
                )
            )
        return {"success": success}

    @tool(readonly=False)
    def add_new_relation(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        strength: float = 0.5,
        polarity: str = "neutral",
        description: str = "",
    ) -> Dict[str, Any]:
        """
        Add a new relation between two entities.

        Args:
            source_entity_id: Source entity ID.
            target_entity_id: Target entity ID.
            relation_type: Type of relation (e.g., 'ally', 'rival', 'supports').
            strength: Strength [0.0, 1.0].
            polarity: 'positive', 'neutral', or 'negative'.
            description: Optional description.

        Returns:
            The new relation ID or error.
        """
        rel = Relation(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
            strength=max(0.0, min(1.0, strength)),
            polarity=polarity,  # type: ignore
            description=description,
        )
        self._world.add_relation(rel)
        self._world.add_event(
            WorldEvent(
                tick=self._world.current_tick,
                event_type="relation_added",
                title=f"Relation added: {source_entity_id} -> {target_entity_id}",
                description=description or f"New relation '{relation_type}' created.",
                participants=[source_entity_id, target_entity_id],
                source_entity_id=source_entity_id,
                source_module="relation_graph",
                trigger_reason=(
                    f"{source_entity_id} created a new {relation_type} relation toward {target_entity_id}."
                ),
                created_by="agent",
                payload={
                    "relation_id": rel.id,
                    "relation_type": relation_type,
                    "strength": rel.strength,
                    "polarity": rel.polarity,
                },
            )
        )
        return {"success": True, "relation_id": rel.id}
