"""
ObservationEnv: Provides agents with semantic observation tools.

职责：
- 对 Agent 暴露当前已知事件、相关人物/组织、近期消息、全局状态摘要
- 基于 WorldStateManager 提供只读观察工具
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentsociety2.env.base import EnvBase, tool

if TYPE_CHECKING:
    from agentsociety2.world.world_state import WorldStateManager

__all__ = ["ObservationEnv"]


class ObservationEnv(EnvBase):
    """
    Semantic observation environment module for virtual world agents.

    Provides read-only tools for agents to observe the current world state:
    - recent events affecting them
    - related entities
    - current global variables
    - world snapshot summary
    """

    def __init__(self, world_manager: "WorldStateManager"):
        super().__init__()
        self._world = world_manager

    @property
    def description(self) -> str:
        return (
            "ObservationEnv: Provides read-only observation tools for agents to perceive "
            "the current virtual world state, including events, relations, and global variables."
        )

    async def step(self, tick: int, t: datetime) -> None:
        self.t = t

    @tool(readonly=True, kind="observe")
    def get_recent_events(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get recent world events. Optionally filtered by participant entity_id.

        Args:
            agent_id: If provided, filter events that include this entity as a participant.

        Returns:
            List of recent event dicts (tick, event_type, title, description, participants).
        """
        events = self._world.get_recent_events(limit=20)
        if agent_id:
            events = [e for e in events if agent_id in e.participants]
        return [
            {
                "id": e.id,
                "tick": e.tick,
                "event_type": e.event_type,
                "title": e.title,
                "description": e.description,
                "participants": e.participants,
            }
            for e in events
        ]

    @tool(readonly=True, kind="observe")
    def get_world_summary(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get a summary of the current world state.

        Args:
            agent_id: Optional — if provided, include agent-specific context.

        Returns:
            Dict with entity count, relation count, current tick, global variables, build_summary.
        """
        return self._world.build_world_summary(agent_id=agent_id)

    @tool(readonly=True, kind="observe")
    def get_entity_info(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get information about a specific entity (or self if agent_id provided).

        Args:
            agent_id: Entity ID to look up.

        Returns:
            Entity dict with name, type, description, attributes.
        """
        if not agent_id:
            return {"error": "agent_id is required"}
        entity = self._world.get_entity(agent_id)
        if not entity:
            return {"error": f"Entity '{agent_id}' not found"}
        return {
            "id": entity.id,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "description": entity.description,
            "attributes": entity.attributes,
        }
