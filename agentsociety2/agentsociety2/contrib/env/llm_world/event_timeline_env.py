"""
EventTimelineEnv: Provides agents with tools to create, query, and respond to world events.

职责：
- 创建事件
- 响应事件
- 获取事件时间线
- 写入阶段结果

参考 EventSpace 思路，但适配通用世界语义。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentsociety2.env.base import EnvBase, tool
from agentsociety2.world.models import WorldEvent

if TYPE_CHECKING:
    from agentsociety2.world.world_state import WorldStateManager

__all__ = ["EventTimelineEnv"]


class EventTimelineEnv(EnvBase):
    """
    Event timeline environment module.

    Allows agents to read the world event timeline and create new events.
    """

    def __init__(self, world_manager: "WorldStateManager"):
        super().__init__()
        self._world = world_manager

    @property
    def description(self) -> str:
        return (
            "EventTimelineEnv: Tools for accessing and contributing to the world event timeline. "
            "Agents can query recent events and record new ones."
        )

    async def step(self, tick: int, t: datetime) -> None:
        self.t = t

    # ------------------------------------------------------------------
    # Read tools
    # ------------------------------------------------------------------

    @tool(readonly=True, kind="observe")
    def get_timeline(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get the recent world event timeline.

        Args:
            agent_id: If provided, also include events where this agent participated.

        Returns:
            List of recent event dicts, newest last.
        """
        events = self._world.get_recent_events(limit=30)
        return [
            {
                "id": e.id,
                "tick": e.tick,
                "event_type": e.event_type,
                "title": e.title,
                "description": e.description,
                "participants": e.participants,
                "created_by": e.created_by,
            }
            for e in events
        ]

    @tool(readonly=True, kind="observe")
    def get_events_by_type(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get timeline events grouped by event_type.

        Args:
            agent_id: Unused (kept for API consistency).

        Returns:
            Dict mapping event_type → list of event titles.
        """
        type_map: Dict[str, List[str]] = {}
        for e in self._world.get_recent_events(limit=50):
            type_map.setdefault(e.event_type, []).append(e.title)
        return [{"event_type": k, "events": v} for k, v in type_map.items()]

    # ------------------------------------------------------------------
    # Write tools
    # ------------------------------------------------------------------

    @tool(readonly=False)
    def create_event(
        self,
        creator_entity_id: str,
        event_type: str,
        title: str,
        description: str,
        participant_ids: Optional[List[str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create and record a new world event.

        Args:
            creator_entity_id: The entity creating this event.
            event_type: Type of event (e.g., 'negotiation', 'conflict', 'announcement').
            title: Short title for the event.
            description: Full description of what happened.
            participant_ids: Other entities involved.
            payload: Optional extra data.

        Returns:
            New event ID and tick.
        """
        participants = participant_ids or []
        if creator_entity_id not in participants:
            participants = [creator_entity_id] + participants

        event = WorldEvent(
            tick=self._world.current_tick,
            event_type=event_type,
            title=title,
            description=description,
            participants=participants,
            payload=payload or {},
            created_by="agent",
        )
        self._world.add_event(event)
        return {"success": True, "event_id": event.id, "tick": event.tick}

    @tool(readonly=False)
    def respond_to_event(
        self,
        responder_entity_id: str,
        original_event_id: str,
        response_content: str,
    ) -> Dict[str, Any]:
        """
        Record a response to an existing event.

        Args:
            responder_entity_id: The entity responding.
            original_event_id: ID of the event being responded to.
            response_content: Description of the response action.

        Returns:
            New response event ID.
        """
        original = next(
            (e for e in self._world.timeline if e.id == original_event_id), None
        )
        title_ref = original.title if original else original_event_id

        event = WorldEvent(
            tick=self._world.current_tick,
            event_type="response",
            title=f"Response to: {title_ref}",
            description=response_content,
            participants=[responder_entity_id],
            payload={"responding_to": original_event_id},
            created_by="agent",
        )
        self._world.add_event(event)
        return {"success": True, "event_id": event.id}

    @tool(readonly=False)
    def record_outcome(
        self,
        entity_id: str,
        outcome_type: str,
        description: str,
        affected_entities: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Write a phase/step outcome to the timeline.

        Args:
            entity_id: The reporting entity.
            outcome_type: Type of outcome (e.g., 'victory', 'failure', 'compromise').
            description: What happened.
            affected_entities: Entities affected by this outcome.

        Returns:
            Event ID.
        """
        participants = affected_entities or []
        if entity_id not in participants:
            participants = [entity_id] + participants

        event = WorldEvent(
            tick=self._world.current_tick,
            event_type=f"outcome:{outcome_type}",
            title=f"Outcome: {outcome_type}",
            description=description,
            participants=participants,
            created_by="agent",
        )
        self._world.add_event(event)
        return {"success": True, "event_id": event.id}
