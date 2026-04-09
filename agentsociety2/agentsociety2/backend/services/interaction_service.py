"""
InteractionService: Handle chat and intervention requests for a world.

职责：
- 和世界对话（类型 A）
- 和单个 Agent 对话（类型 B）
- 注入干预（类型 C）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from agentsociety2.agent.world_sim_agent import WorldSimAgent
from agentsociety2.backend.services.graph_service import GraphService
from agentsociety2.contrib.env.llm_world import InterventionEnv
from agentsociety2.backend.services.module_router_builder import ModuleRouterBuilder
from agentsociety2.env.router_world import WorldRouter
from agentsociety2.logger import get_logger
from agentsociety2.world import (
    Intervention,
    WorldInteraction,
    WorldRepository,
    WorldStateManager,
)

__all__ = ["InteractionService"]

_logger = get_logger()


class InteractionService:
    """世界/智能体对话与干预注入服务层。"""

    def __init__(self, repository: WorldRepository):
        self._repo = repository
        self._module_router_builder = ModuleRouterBuilder()

    async def chat_with_world(
        self, world_id: str, message: str
    ) -> Dict[str, Any]:
        """回答关于世界状态的问题。"""
        world_manager, agents = await self._load_world_and_agents(world_id)
        if world_manager is None:
            return {"success": False, "error": f"未找到世界：{world_id}"}

        interaction = WorldInteraction(world_manager=world_manager, agents=agents)
        result = await interaction.chat_with_world(message)
        return {"success": True, **result}

    async def chat_with_agent(
        self, world_id: str, agent_id: str, message: str
    ) -> Dict[str, Any]:
        """向指定智能体发送问题。"""
        world_manager, agents = await self._load_world_and_agents(world_id)
        if world_manager is None:
            return {"success": False, "error": f"未找到世界：{world_id}"}

        interaction = WorldInteraction(world_manager=world_manager, agents=agents)
        result = await interaction.chat_with_agent(agent_id, message)
        return {"success": result.get("success", False), **result}

    async def apply_intervention(
        self,
        world_id: str,
        intervention_type: str,
        payload: Dict[str, Any],
        reason: str = "",
    ) -> Dict[str, Any]:
        """向世界注入外部干预。"""
        world_state = await self._repo.load_world_state(world_id)
        if world_state is None:
            return {"success": False, "error": f"未找到世界：{world_id}"}

        world_manager = WorldStateManager(world_state)
        intervention = Intervention(
            world_id=world_id,
            intervention_type=intervention_type,
            payload=payload,
            reason=reason,
        )
        user_modules = self._module_router_builder.build_user_env_modules(
            world_manager=world_manager,
            world_state=world_state,
        )
        intervention_modules = [
            module for module in user_modules if isinstance(module, InterventionEnv)
        ]

        if intervention_modules:
            result = await self._apply_intervention_via_operator_router(
                world_manager=world_manager,
                intervention=intervention,
                env_modules=intervention_modules,
            )
            if not result.get("success"):
                result = self._apply_intervention_via_env(
                    intervention_env=intervention_modules[0],
                    intervention=intervention,
                    world_manager=world_manager,
                )
        else:
            interaction = WorldInteraction(world_manager=world_manager)
            result = await interaction.apply_intervention(intervention)

        # Persist updated state and intervention
        if result.get("success"):
            intervention.applied_at_tick = world_manager.current_tick
            intervention_id = result.get("intervention_id")
            if intervention_id:
                intervention.intervention_id = intervention_id
            snapshot = world_manager.snapshot()
            await self._repo.save_world_state(snapshot)
            await self._repo.save_snapshot(snapshot)
            await self._repo.save_events(world_id=world_id, events=snapshot.timeline)
            await self._repo.save_intervention(intervention)

        return result

    async def branch_from_timeline_intervention(
        self,
        world_id: str,
        anchor_tick: int,
        command: str,
        continuation_steps: int = 5,
        tick_seconds: Optional[int] = None,
        branch_name: str = "",
    ) -> Dict[str, Any]:
        """Fork a historical snapshot, apply a natural-language intervention, and continue simulation."""
        source_state = await self._repo.load_world_state(world_id, tick=anchor_tick)
        if source_state is None:
            return {
                "success": False,
                "error": (
                    f"未找到 {world_id} 在 tick {anchor_tick} 或更早的历史快照。"
                    " 请先重新运行推演以生成逐 tick 快照。"
                ),
            }
        if source_state.current_tick != anchor_tick:
            return {
                "success": False,
                "error": (
                    f"当前只找到了 tick {source_state.current_tick} 的快照，"
                    f"无法精确在 tick {anchor_tick} 上派生分支。请先生成逐 tick 快照后再试。"
                ),
            }

        branched_world_id = f"{world_id}_branch_{uuid.uuid4().hex[:8]}"
        branched_name = branch_name.strip() or f"{source_state.name} · Branch T{anchor_tick}"
        source_state.world_id = branched_world_id
        source_state.name = branched_name
        source_state.snapshot_version = 0
        source_state.created_at = datetime.utcnow()
        source_state.updated_at = source_state.created_at

        world_manager = WorldStateManager(source_state)
        world_manager.set_global_variable(
            "branch_origin",
            {
                "source_world_id": world_id,
                "anchor_tick": anchor_tick,
                "created_at": source_state.created_at.isoformat(),
                "command": command,
            },
            description="Metadata describing the branch origin for timeline intervention replay.",
        )

        initial_snapshot = world_manager.snapshot()
        await self._repo.save_world_state(initial_snapshot)
        await self._repo.save_snapshot(initial_snapshot)
        await self._repo.save_events(world_id=branched_world_id, events=initial_snapshot.timeline)

        intervention_result = await self._apply_natural_language_intervention(
            world_manager=world_manager,
            command=command,
            source_world_id=world_id,
            anchor_tick=anchor_tick,
        )
        if not intervention_result.get("success"):
            return intervention_result

        intervention_id = intervention_result.get("intervention_id")
        intervention = Intervention(
            intervention_id=intervention_id or f"int_{uuid.uuid4().hex[:12]}",
            world_id=branched_world_id,
            intervention_type="timeline_branch_command",
            payload={
                "command": command,
                "source_world_id": world_id,
                "anchor_tick": anchor_tick,
            },
            reason=f"Timeline branch command at tick {anchor_tick}",
            applied_at_tick=world_manager.current_tick,
        )

        post_intervention_snapshot = world_manager.snapshot()
        await self._repo.save_world_state(post_intervention_snapshot)
        await self._repo.save_snapshot(post_intervention_snapshot)
        await self._repo.save_events(world_id=branched_world_id, events=post_intervention_snapshot.timeline)
        await self._repo.save_intervention(intervention)

        updated_snapshot = post_intervention_snapshot.model_dump(mode="json")
        if continuation_steps > 0:
            from agentsociety2.backend.services.simulation_service import SimulationService

            sim_service = SimulationService(self._repo)
            sim_result = await sim_service.simulate(
                world_id=branched_world_id,
                steps=continuation_steps,
                tick_seconds=tick_seconds,
                stop_when_stable=False,
            )
            if not sim_result.get("success"):
                return sim_result
            updated_snapshot = sim_result.get("updated_snapshot")

        current_state = await self._repo.load_world_state(branched_world_id)
        graph_task_id = None
        if current_state is not None:
            try:
                graph_task_id = await GraphService.start_build(
                    world_id=branched_world_id,
                    fact_seed_text=GraphService.build_fact_seed_text(current_state),
                )
            except Exception as exc:
                _logger.warning(
                    "分支世界 %s 自动启动图谱构建失败: %s",
                    branched_world_id,
                    exc,
                )

        timeline = [
            event.model_dump(mode="json")
            for event in await self._repo.get_events(branched_world_id, limit=500)
        ]

        return {
            "success": True,
            "world_id": branched_world_id,
            "source_world_id": world_id,
            "source_tick": anchor_tick,
            "intervention_id": intervention.intervention_id,
            "graph_task_id": graph_task_id,
            "graph_status": "pending" if graph_task_id else None,
            "updated_snapshot": updated_snapshot,
            "timeline": timeline,
        }
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _apply_natural_language_intervention(
        self,
        world_manager: WorldStateManager,
        command: str,
        source_world_id: str,
        anchor_tick: int,
    ) -> Dict[str, Any]:
        user_modules = self._module_router_builder.build_user_env_modules(
            world_manager=world_manager,
            world_state=world_manager.snapshot(),
        )
        intervention_modules = [
            module for module in user_modules if isinstance(module, InterventionEnv)
        ]
        if not intervention_modules:
            return {"success": False, "error": "当前世界未启用 InterventionEnv。"}

        router = WorldRouter(env_modules=intervention_modules, router_role="operator")
        ctx = {
            "world_id": world_manager.world_id,
            "source_world_id": source_world_id,
            "anchor_tick": anchor_tick,
            "current_tick": world_manager.current_tick,
            "world_summary": world_manager.build_report_snapshot(),
        }
        instruction = (
            "Interpret the operator's natural-language command as a single timeline intervention "
            "to be injected at the current branch point. "
            "Use intervention tools only. Do not generate reports. "
            "Apply the best matching intervention and then call set_status with success.\n\n"
            f"command={command}"
        )

        try:
            results, _answer = await router.ask(ctx=ctx, instruction=instruction, readonly=False)
        except Exception as e:
            return {"success": False, "error": f"operator router failed: {e}"}

        if results.get("status") not in {"success", "in_progress"}:
            return {
                "success": False,
                "error": results.get("error") or results.get("reason") or "timeline intervention failed",
            }

        return {
            "success": True,
            "intervention_id": self._extract_result_field(results, "intervention_id"),
            "tick": self._extract_result_field(results, "tick") or world_manager.current_tick,
        }

    async def _apply_intervention_via_operator_router(
        self,
        world_manager: WorldStateManager,
        intervention: Intervention,
        env_modules: List[InterventionEnv],
    ) -> Dict[str, Any]:
        """Execute operator-side intervention selection via WorldRouter."""
        router = WorldRouter(env_modules=env_modules, router_role="operator")
        ctx = {
            "world_id": world_manager.world_id,
            "current_tick": world_manager.current_tick,
            "intervention_type": intervention.intervention_type,
            "payload": intervention.payload,
            "reason": intervention.reason,
        }
        instruction = self._build_operator_intervention_instruction(intervention)

        try:
            results, _answer = await router.ask(ctx=ctx, instruction=instruction, readonly=False)
        except Exception as e:
            return {"success": False, "error": f"operator router failed: {e}"}

        if results.get("status") not in {"success", "in_progress"}:
            return {
                "success": False,
                "error": results.get("error") or results.get("reason") or "operator router intervention failed",
            }

        intervention_id = self._extract_result_field(results, "intervention_id") or intervention.intervention_id
        tick = self._extract_result_field(results, "tick")
        if tick is None:
            tick = world_manager.current_tick

        return {
            "success": True,
            "intervention_id": intervention_id,
            "tick": tick,
        }

    async def _load_world_and_agents(self, world_id: str):
        """加载世界状态并重建智能体。"""
        world_state = await self._repo.load_world_state(world_id)
        if world_state is None:
            return None, []

        world_manager = WorldStateManager(world_state)
        entity_map = {e.id: e for e in world_state.entities}

        agents: List[WorldSimAgent] = []
        for i, persona in enumerate(world_state.personas):
            entity = entity_map.get(persona.entity_id)
            profile = {
                "entity_id": persona.entity_id,
                "name": entity.name if entity else f"Agent_{i}",
                "entity_kind": entity.entity_type if entity else "person",
                "identity_summary": persona.identity_summary,
                "goals": persona.goals,
                "fears": persona.fears,
                "preferences": persona.preferences,
                "stance_map": persona.stance_map,
                "behavior_style": persona.behavior_style,
                "speech_style": persona.speech_style,
                "memory_seeds": persona.memory_seeds,
            }
            agents.append(WorldSimAgent(id=i, profile=profile, name=profile["name"]))

        return world_manager, agents

    def _apply_intervention_via_env(
        self,
        intervention_env: InterventionEnv,
        intervention: Intervention,
        world_manager: WorldStateManager,
    ) -> Dict[str, Any]:
        """Use operator-side InterventionEnv when the request maps to an explicit tool."""
        intervention_type = intervention.intervention_type
        payload = intervention.payload
        reason = intervention.reason
        if intervention_type == "policy_shock":
            return intervention_env.inject_policy_shock(
                policy_name=str(payload.get("policy_name", "")),
                description=str(payload.get("description", "")),
                severity=float(payload.get("severity", 0.5)),
                affected_entity_ids=payload.get("affected_entities") or payload.get("affected_entity_ids"),
                reason=reason,
            )
        if intervention_type == "opinion_shift":
            return intervention_env.inject_opinion_shift(
                topic=str(payload.get("topic", "")),
                shift_direction=str(payload.get("direction") or payload.get("shift_direction") or ""),
                magnitude=float(payload.get("magnitude", 0.3)),
                affected_entity_ids=payload.get("affected_entities") or payload.get("affected_entity_ids"),
                reason=reason,
            )
        if intervention_type == "resource_change":
            return intervention_env.inject_resource_change(
                entity_id=str(payload.get("entity_id", "")),
                resource_type=str(payload.get("resource_type", "")),
                delta=float(payload.get("delta", 0.0)),
                reason=reason,
            )
        if intervention_type == "attitude_change":
            return intervention_env.inject_attitude_change(
                entity_id=str(payload.get("entity_id", "")),
                target_entity_id=str(payload.get("target_entity_id", "")),
                new_polarity=str(payload.get("new_polarity", "")),
                reason=reason,
            )
        if intervention_type == "global_variable_change":
            variable_name = str(payload.get("variable_name") or payload.get("name") or "")
            value = payload.get("value")
            if variable_name:
                env_result = intervention_env.set_global_variable(
                    variable_name=variable_name,
                    value=value,
                    description=str(payload.get("description", "")),
                )
                return {
                    "success": bool(env_result.get("success")),
                    "intervention_id": intervention.intervention_id,
                    "tick": world_manager.current_tick,
                }

        world_manager.apply_intervention(intervention)
        return {
            "success": True,
            "intervention_id": intervention.intervention_id,
            "tick": world_manager.current_tick,
        }

    def _build_operator_intervention_instruction(self, intervention: Intervention) -> str:
        """Build a constrained natural-language instruction for operator routing."""
        payload_json = json.dumps(intervention.payload, ensure_ascii=False, default=str)
        return (
            "Use exactly one operator intervention tool to apply the requested world change. "
            "Do not generate reports or perform unrelated analysis. "
            "Match the intervention type and payload exactly.\n\n"
            f"intervention_type={intervention.intervention_type}\n"
            f"payload={payload_json}\n"
            f"reason={intervention.reason or '(none)'}\n\n"
            "After applying the intervention, call set_status with success."
        )

    def _extract_result_field(self, results: Dict[str, Any], field_name: str) -> Any:
        """Extract a common field from nested router tool results."""
        for key, value in results.items():
            if key in {"status", "error", "reason"}:
                continue
            if isinstance(value, dict) and field_name in value:
                return value.get(field_name)
        return None

