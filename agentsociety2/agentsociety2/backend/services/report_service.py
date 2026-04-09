"""
ReportService: Generate and retrieve reports for a world simulation.

职责：
- 调用 ReportAgent 生成报告
- 持久化报告
- 返回最新报告
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agentsociety2.backend.services.module_router_builder import ModuleRouterBuilder
from agentsociety2.contrib.env.llm_world import ReportEnv
from agentsociety2.env.router_world import WorldRouter
from agentsociety2.logger import get_logger
from agentsociety2.world import (
    Report,
    WorldRepository,
    WorldStateManager,
)

__all__ = ["ReportService"]

_logger = get_logger()


class ReportService:
    """世界仿真报告服务层。"""

    def __init__(self, repository: WorldRepository):
        self._repo = repository
        self._module_router_builder = ModuleRouterBuilder()

    async def generate_report(
        self,
        world_id: str,
        report_type: str = "summary",
        focus: str = "",
    ) -> Dict[str, Any]:
        """为指定世界生成报告。"""
        world_state = await self._repo.load_world_state(world_id)
        if world_state is None:
            return {"success": False, "error": f"未找到世界：{world_id}"}

        world_manager = WorldStateManager(world_state)
        user_modules = self._module_router_builder.build_user_env_modules(
            world_manager=world_manager,
            world_state=world_state,
        )
        report_modules = [
            module for module in user_modules if isinstance(module, ReportEnv)
        ]

        if not report_modules:
            return {"success": False, "error": "当前世界未启用 ReportEnv"}

        router = WorldRouter(env_modules=report_modules, router_role="operator")
        ctx = {
            "world_id": world_manager.world_id,
            "current_tick": world_manager.current_tick,
            "report_type": report_type,
            "focus": focus,
        }
        instruction = self._build_operator_report_instruction(
            report_type=report_type,
            focus=focus,
        )

        try:
            results, answer = await router.ask(
                ctx=ctx,
                instruction=instruction,
                readonly=True,
            )
        except Exception as e:
            return {"success": False, "error": f"operator router failed: {e}"}

        if results.get("status") not in {"success", "in_progress"}:
            return {
                "success": False,
                "error": results.get("error") or results.get("reason") or "operator router report failed",
            }

        report = Report(
            world_id=world_id,
            report_type=report_type,
            focus=focus,
            content=answer,
            sources=["report_env", "operator_router"],
        )

        await self._repo.save_report(report)

        return {
            "success": True,
            "report_id": report.report_id,
            "world_id": world_id,
            "report_type": report_type,
            "focus": report.focus,
            "content": report.content,
            "created_at": report.created_at.isoformat(),
        }

    def _build_operator_report_instruction(
        self,
        report_type: str,
        focus: str,
    ) -> str:
        """Build a constrained operator-side reporting instruction."""
        resolved_focus = focus or f"Overall {report_type} of the simulation"
        return (
            "Use the operator-side reporting tools to inspect the world and produce a concise report. "
            "You may call multiple read-only report tools, then summarize the findings. "
            f"Report type: {report_type}. "
            f"Focus: {resolved_focus}. "
            "Call set_status with success when the report is complete."
        )

    async def get_latest_report(self, world_id: str) -> Optional[Dict[str, Any]]:
        """获取指定世界最近一次生成的报告。"""
        report = await self._repo.get_latest_report(world_id)
        if not report:
            return None
        return {
            "report_id": report.report_id,
            "world_id": report.world_id,
            "report_type": report.report_type,
            "focus": report.focus,
            "content": report.content,
            "created_at": report.created_at.isoformat(),
        }
