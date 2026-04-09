"""
ReportAgent: Generate structured reports from world simulation data.

职责：
- 从 world snapshot + timeline + 关系变化中生成报告
- 支持 prediction / summary / analysis / retrospective 报告类型
- 输出结构化报告内容
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentsociety2.config import get_llm_router_and_model, extract_json
from agentsociety2.logger import get_logger
from agentsociety2.world.models import Report, WorldEvent
from agentsociety2.world.prompts import REPORT_GENERATION_PROMPT

if TYPE_CHECKING:
    from agentsociety2.world.world_state import WorldStateManager

__all__ = ["ReportAgent"]


class ReportAgent:
    """
    Generates analysis, prediction, and summary reports from world simulation data.
    
    Not a WorldSimAgent subclass — a dedicated report generator service.
    """

    def __init__(
        self,
        world_manager: "WorldStateManager",
        report_env: Any | None = None,
    ):
        self._world = world_manager
        self._report_env = report_env
        self._llm_router, self._model_name = get_llm_router_and_model("default")
        self._logger = get_logger()

    async def generate(
        self,
        report_type: str = "summary",
        focus: str = "",
    ) -> Report:
        """
        Generate a report for the current world state.

        Args:
            report_type: Type of report — summary / prediction / analysis / retrospective
            focus: Optional focus question or area.

        Returns:
            Report object with content.
        """
        if self._report_env is not None:
            snapshot_payload = self._report_env.get_full_snapshot_summary()
            snapshot_summary = json.dumps(
                snapshot_payload, ensure_ascii=False, default=str
            )
            timeline_payload = self._report_env.get_full_timeline()[-30:]
            timeline_summary = "\n".join(
                f"[tick {e['tick']}] [{e['event_type']}] {e['title']}: {str(e['description'])[:120]}"
                for e in timeline_payload
            )
            relation_payload = self._report_env.get_relation_network()
            relation_changes_summary = self._build_relation_changes_summary(
                relation_payload.get("edges", [])
            )
        else:
            snapshot_summary = self._world.to_summary_text(max_events=20)
            timeline_events = self._world.get_recent_events(limit=30)
            timeline_summary = "\n".join(
                f"[tick {e.tick}] [{e.event_type}] {e.title}: {e.description[:120]}"
                for e in timeline_events
            )
            relation_changes_summary = self._build_relation_changes_summary(
                self._world.relations
            )

        prompt = REPORT_GENERATION_PROMPT.format(
            world_snapshot_summary=snapshot_summary[:3000],
            timeline_summary=timeline_summary or "(no events)",
            relation_changes_summary=relation_changes_summary or "(no relation changes tracked)",
            report_type=report_type,
            focus=focus or f"Overall {report_type} of the simulation",
        )

        content = ""
        try:
            response = await self._llm_router.acompletion(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.choices[0].message.content or ""

            # Try to extract structured JSON; fall back to raw text
            parsed = extract_json(raw)
            if parsed and isinstance(parsed, dict):
                content = parsed.get("full_report") or raw
            else:
                content = raw

        except Exception as e:
            self._logger.error(f"ReportAgent.generate failed: {e}")
            content = f"[Report generation failed: {e}]"

        report = Report(
            world_id=self._world.world_id,
            report_type=report_type,
            focus=focus,
            content=content,
            sources=["timeline", "relations", "snapshot"],
        )

        self._logger.info(
            f"ReportAgent: generated '{report_type}' report for world '{self._world.world_id}'"
        )
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_relation_changes_summary(self, relations: List[Any]) -> str:
        """Summarize recent relation states for the report."""
        lines = []
        for r in relations[:30]:
            polarity = getattr(r, "polarity", None)
            if polarity is None and isinstance(r, dict):
                polarity = r.get("polarity")
            polarity_emoji = {"positive": "+", "neutral": "~", "negative": "-"}.get(
                polarity, "~"
            )
            source = getattr(r, "source_entity_id", None)
            if source is None and isinstance(r, dict):
                source = r.get("source") or r.get("source_entity_id")
            target = getattr(r, "target_entity_id", None)
            if target is None and isinstance(r, dict):
                target = r.get("target") or r.get("target_entity_id")
            relation_type = getattr(r, "relation_type", None)
            if relation_type is None and isinstance(r, dict):
                relation_type = r.get("relation_type")
            strength = getattr(r, "strength", None)
            if strength is None and isinstance(r, dict):
                strength = r.get("strength")
            lines.append(
                f"  [{polarity_emoji}] {source} → {target}: "
                f"{relation_type} (strength={float(strength or 0.0):.2f})"
            )
        return "\n".join(lines)
