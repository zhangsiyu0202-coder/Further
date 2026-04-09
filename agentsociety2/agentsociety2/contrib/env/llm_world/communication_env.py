"""
CommunicationEnv: Provides agents with messaging tools (private, group, broadcast).

职责：
- 发私信、群聊、广播
- 回复消息
- 查询收件箱

参考 SimpleSocialSpace 的收发思路，但作为独立模块重建。
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentsociety2.env.base import EnvBase, tool
from agentsociety2.world.models import WorldEvent

if TYPE_CHECKING:
    from agentsociety2.world.world_state import WorldStateManager

__all__ = ["CommunicationEnv"]


class _Message:
    """Internal message record."""

    def __init__(
        self,
        msg_id: str,
        sender_id: str,
        recipients: List[str],  # empty = broadcast
        content: str,
        msg_type: str,
        tick: int,
        reply_to: Optional[str] = None,
    ):
        self.msg_id = msg_id
        self.sender_id = sender_id
        self.recipients = recipients
        self.content = content
        self.msg_type = msg_type  # private / group / broadcast
        self.tick = tick
        self.reply_to = reply_to
        self.timestamp = datetime.utcnow().isoformat()


class CommunicationEnv(EnvBase):
    """
    Communication environment module for virtual world agents.

    Provides private messaging, group chat, and broadcast capabilities.
    """

    def __init__(self, world_manager: "WorldStateManager"):
        super().__init__()
        self._world = world_manager
        self._messages: List[_Message] = []
        # inbox[entity_id] → list of message IDs
        self._inbox: Dict[str, List[str]] = defaultdict(list)
        self._msg_index: Dict[str, _Message] = {}
        # msg_id → WorldEvent.id (for causality linking in replies)
        self._msg_event_map: Dict[str, str] = {}

    @property
    def description(self) -> str:
        return (
            "CommunicationEnv: Messaging tools for agents — private messages, "
            "group chat, and broadcast."
        )

    async def step(self, tick: int, t: datetime) -> None:
        self.t = t
        self._current_tick = tick

    @property
    def _current_tick(self) -> int:
        return self._world.current_tick

    @_current_tick.setter
    def _current_tick(self, v: int) -> None:
        pass  # tick comes from world

    # ------------------------------------------------------------------
    # Read tools
    # ------------------------------------------------------------------

    @tool(readonly=True, kind="observe")
    def get_inbox(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all messages received by this agent, including broadcasts.

        Args:
            agent_id: The receiving entity ID (required).

        Returns:
            List of message dicts.
        """
        if not agent_id:
            return [{"error": "agent_id is required"}]

        result = []
        for msg in self._messages:
            # Include if direct recipient or broadcast
            if agent_id in msg.recipients or msg.msg_type == "broadcast":
                if msg.sender_id != agent_id:  # don't show own sent messages
                    result.append(self._msg_to_dict(msg))
        return result[-20:]  # last 20

    # ------------------------------------------------------------------
    # Write tools
    # ------------------------------------------------------------------

    @tool(readonly=False)
    def send_private_message(
        self,
        sender_id: str,
        recipient_id: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        Send a private message from one entity to another.

        Args:
            sender_id: Sender entity ID.
            recipient_id: Recipient entity ID.
            content: Message content.

        Returns:
            Message ID and success status.
        """
        msg = _Message(
            msg_id=str(uuid.uuid4())[:8],
            sender_id=sender_id,
            recipients=[recipient_id],
            content=content,
            msg_type="private",
            tick=self._world.current_tick,
        )
        self._deliver(msg)
        evt = WorldEvent(
            tick=self._world.current_tick,
            event_type="private_message",
            title=f"Private message from {sender_id}",
            description=content[:200],
            participants=[sender_id, recipient_id],
            source_entity_id=sender_id,
            source_module="communication",
            trigger_reason=f"{sender_id} initiated a direct message to {recipient_id}.",
            created_by="agent",
            payload={
                "message_id": msg.msg_id,
                "recipient_id": recipient_id,
                "message_type": "private",
            },
        )
        self._world.add_event(evt)
        self._msg_event_map[msg.msg_id] = evt.id
        return {"success": True, "msg_id": msg.msg_id}

    @tool(readonly=False)
    def send_group_message(
        self,
        sender_id: str,
        recipient_ids: List[str],
        content: str,
    ) -> Dict[str, Any]:
        """
        Send a message to a group of entities.

        Args:
            sender_id: Sender entity ID.
            recipient_ids: List of recipient entity IDs.
            content: Message content.

        Returns:
            Message ID and success status.
        """
        msg = _Message(
            msg_id=str(uuid.uuid4())[:8],
            sender_id=sender_id,
            recipients=recipient_ids,
            content=content,
            msg_type="group",
            tick=self._world.current_tick,
        )
        self._deliver(msg)
        evt = WorldEvent(
            tick=self._world.current_tick,
            event_type="group_message",
            title=f"Group message from {sender_id}",
            description=content[:200],
            participants=[sender_id, *recipient_ids],
            source_entity_id=sender_id,
            source_module="communication",
            trigger_reason=f"{sender_id} sent a group message to {len(recipient_ids)} recipients.",
            created_by="agent",
            payload={
                "message_id": msg.msg_id,
                "recipient_ids": recipient_ids,
                "message_type": "group",
            },
        )
        self._world.add_event(evt)
        self._msg_event_map[msg.msg_id] = evt.id
        return {"success": True, "msg_id": msg.msg_id}

    @tool(readonly=False)
    def broadcast(
        self,
        sender_id: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        Broadcast a message to all active entities in the world.

        Args:
            sender_id: Sender entity ID.
            content: Broadcast content.

        Returns:
            Message ID and recipient count.
        """
        active_ids = [a.entity_id for a in self._world.active_agent_states]
        msg = _Message(
            msg_id=str(uuid.uuid4())[:8],
            sender_id=sender_id,
            recipients=[],  # broadcast = no explicit recipients
            content=content,
            msg_type="broadcast",
            tick=self._world.current_tick,
        )
        self._deliver(msg)

        # Also record as a world event
        event = WorldEvent(
            tick=self._world.current_tick,
            event_type="broadcast",
            title=f"Broadcast by {sender_id}",
            description=content[:200],
            participants=[sender_id],
            source_entity_id=sender_id,
            source_module="communication",
            trigger_reason=f"{sender_id} broadcasted a message to all active agents.",
            created_by="agent",
            payload={"message_id": msg.msg_id, "message_type": "broadcast"},
        )
        self._world.add_event(event)
        self._msg_event_map[msg.msg_id] = event.id

        return {
            "success": True,
            "msg_id": msg.msg_id,
            "recipient_count": len(active_ids),
        }

    @tool(readonly=False)
    def reply_to_message(
        self,
        sender_id: str,
        original_msg_id: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        Reply to a specific message.

        Args:
            sender_id: Replying entity ID.
            original_msg_id: The message ID being replied to.
            content: Reply content.

        Returns:
            New message ID and success status.
        """
        original = self._msg_index.get(original_msg_id)
        if not original:
            return {"success": False, "error": f"Message '{original_msg_id}' not found"}

        recipient_id = original.sender_id
        msg = _Message(
            msg_id=str(uuid.uuid4())[:8],
            sender_id=sender_id,
            recipients=[recipient_id],
            content=content,
            msg_type="private",
            tick=self._world.current_tick,
            reply_to=original_msg_id,
        )
        self._deliver(msg)
        parent_world_event_id = self._msg_event_map.get(original_msg_id)
        self._world.add_event(
            WorldEvent(
                tick=self._world.current_tick,
                event_type="message_reply",
                title=f"Reply from {sender_id}",
                description=content[:200],
                participants=[sender_id, recipient_id],
                parent_event_id=parent_world_event_id,
                source_entity_id=sender_id,
                source_module="communication",
                trigger_reason=f"{sender_id} replied to message {original_msg_id}.",
                created_by="agent",
                payload={
                    "message_id": msg.msg_id,
                    "reply_to": original_msg_id,
                    "message_type": "private_reply",
                },
            )
        )
        return {"success": True, "msg_id": msg.msg_id}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _deliver(self, msg: _Message) -> None:
        self._messages.append(msg)
        self._msg_index[msg.msg_id] = msg
        for rid in msg.recipients:
            self._inbox[rid].append(msg.msg_id)

    def _msg_to_dict(self, msg: _Message) -> Dict[str, Any]:
        name_map = {e.id: e.name for e in self._world.entities}
        return {
            "msg_id": msg.msg_id,
            "tick": msg.tick,
            "sender_id": msg.sender_id,
            "sender_name": name_map.get(msg.sender_id, msg.sender_id),
            "type": msg.msg_type,
            "content": msg.content,
            "reply_to": msg.reply_to,
        }
