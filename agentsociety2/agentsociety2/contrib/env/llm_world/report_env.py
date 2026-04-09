"""
ReportEnv: Provides report agents with read-only analysis tools.

职责：
- 读取 world snapshot
- 读取 event timeline
- 读取关键关系变化
- 生成结构化报告输入
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentsociety2.env.base import EnvBase, tool

if TYPE_CHECKING:
    from agentsociety2.world.world_state import WorldStateManager

__all__ = ["ReportEnv"]


class ReportEnv(EnvBase):
    """
    Report environment module — read-only tools for report agent analysis.

    Provides structured data access to the world state for generating reports.
    """

    def __init__(self, world_manager: "WorldStateManager"):
        super().__init__()
        self._world = world_manager

    @property
    def description(self) -> str:
        return (
            "ReportEnv: Read-only tools for accessing world snapshot data, "
            "event timelines, and relation changes for report generation."
        )

    async def step(self, tick: int, t: datetime) -> None:
        self.t = t

    @tool(readonly=True, kind="statistics")
    def get_full_snapshot_summary(self) -> Dict[str, Any]:
        """
        Get a comprehensive summary of the current world state for reporting.

        Returns:
            Dict with entities, relations, global_variables, timeline_count, current_tick.
        """
        return self._world.build_report_snapshot()

    @tool(readonly=True, kind="statistics")
    def get_full_timeline(self) -> List[Dict[str, Any]]:
        """
        Get the complete event timeline for analysis.

        Returns:
            All world events sorted by tick.
        """
        return [
            {
                "id": e.id,
                "tick": e.tick,
                "event_type": e.event_type,
                "title": e.title,
                "description": e.description,
                "participants": e.participants,
                "parent_event_id": e.parent_event_id,
                "source_entity_id": e.source_entity_id,
                "source_module": e.source_module,
                "trigger_reason": e.trigger_reason,
                "created_by": e.created_by,
                "created_at": e.created_at.isoformat(),
            }
            for e in sorted(self._world.timeline, key=lambda e: e.tick)
        ]

    @tool(readonly=True, kind="statistics")
    def get_relation_network(self) -> Dict[str, Any]:
        """
        Get the complete relation network for network analysis.

        Returns:
            Nodes (entities) and edges (relations) for graph analysis.
        """
        return self._world.build_relation_network()

    @tool(readonly=True, kind="statistics")
    def get_agent_states_summary(self) -> List[Dict[str, Any]]:
        """
        Get runtime states of all agents for reporting.

        Returns:
            List of agent state dicts.
        """
        return self._world.build_agent_states_summary()
