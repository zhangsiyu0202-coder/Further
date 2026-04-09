"""
SimulationService: Drive multi-agent simulations for a given world.

职责：
- 从持久化恢复 WorldState
- 组装 WorldSimAgent + WorldRouter + llm_world env modules
- 调用 SimulationEngine 推进仿真
- 持久化运行结果
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from agentsociety2.agent.world_sim_agent import WorldSimAgent
from agentsociety2.contrib.env.social_media import SocialMediaSpace
from agentsociety2.env.router_world import WorldRouter
from agentsociety2.logger import get_logger
from agentsociety2.backend.services.module_router_builder import ModuleRouterBuilder
from agentsociety2.world import (
    SimulationEngine,
    WorldRepository,
    WorldStateManager,
)

__all__ = ["SimulationService"]

_logger = get_logger()


class SimulationService:
    """世界仿真服务层。"""

    def __init__(self, repository: WorldRepository):
        self._repo = repository
        self._module_router_builder = ModuleRouterBuilder()
        self._world_locks: Dict[str, asyncio.Lock] = {}

    def _get_world_lock(self, world_id: str) -> asyncio.Lock:
        """Return (creating if necessary) the per-world mutex."""
        if world_id not in self._world_locks:
            self._world_locks[world_id] = asyncio.Lock()
        return self._world_locks[world_id]

    async def simulate(
        self,
        world_id: str,
        steps: int = 5,
        tick_seconds: Optional[int] = None,
        stop_when_stable: bool = False,
    ) -> Dict[str, Any]:
        """
        Load a world and run a simulation for a given number of steps.

        Returns:
            {run_id, world_id, executed_steps, new_event_count, updated_snapshot}
        """
        async with self._get_world_lock(world_id):
            world_state = await self._repo.load_world_state(world_id)
            if world_state is None:
                return {"success": False, "error": f"未找到世界：{world_id}"}

            world_manager, agents, router = await self._assemble_simulation(world_state)
            resolved_tick_seconds = self._resolve_tick_seconds(world_state, tick_seconds)

            engine = SimulationEngine(
                world_manager=world_manager,
                agents=agents,
                router=router,
            )

            async def persist_intermediate_snapshot(_tick: int) -> None:
                snapshot = world_manager.snapshot()
                await self._repo.save_world_state(snapshot)
                await self._repo.save_snapshot(snapshot)

            run = await engine.run(
                steps=steps,
                tick_seconds=resolved_tick_seconds,
                stop_when_stable=stop_when_stable,
                after_step=persist_intermediate_snapshot,
            )

            # Persist updated state
            snapshot = world_manager.snapshot()
            await self._repo.save_world_state(snapshot)
            await self._repo.save_snapshot(snapshot)
            await self._repo.save_events(world_id=world_id, events=snapshot.timeline, run_id=run.run_id)
            await self._repo.save_run(run)

        return {
            "success": True,
            "run_id": run.run_id,
            "world_id": world_id,
            "executed_steps": run.steps_executed,
            "new_event_count": run.new_event_count,
            "updated_snapshot": snapshot.model_dump(mode="json"),
        }

    async def step_once(self, world_id: str, tick_seconds: Optional[int] = None) -> Dict[str, Any]:
        """将世界推进一个时间步。"""
        async with self._get_world_lock(world_id):
            world_state = await self._repo.load_world_state(world_id)
            if world_state is None:
                return {"success": False, "error": f"未找到世界：{world_id}"}

            world_manager, agents, router = await self._assemble_simulation(world_state)
            resolved_tick_seconds = self._resolve_tick_seconds(world_state, tick_seconds)
            engine = SimulationEngine(
                world_manager=world_manager,
                agents=agents,
                router=router,
            )

            step_result = await engine.step(tick_seconds=resolved_tick_seconds)

            snapshot = world_manager.snapshot()
            await self._repo.save_world_state(snapshot)
            await self._repo.save_snapshot(snapshot)
            await self._repo.save_events(world_id=world_id, events=snapshot.timeline)

        return {"success": True, "world_id": world_id, **step_result}

    async def get_timeline(
        self,
        world_id: str,
        limit: int = 50,
        after_tick: int = -1,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """从仓储中读取事件时间线。"""
        events = await self._repo.get_events(
            world_id=world_id,
            limit=limit,
            after_tick=after_tick,
            event_type=event_type,
        )
        return [e.model_dump(mode="json") for e in events]

    async def get_agents(self, world_id: str) -> Optional[List[Dict[str, Any]]]:
        """Return the current simulation agent view for a world."""
        world_state = await self._repo.load_world_state(world_id)
        if world_state is None:
            return None

        entity_map = {entity.id: entity for entity in world_state.entities}
        return [
            {
                "id": index,
                "name": entity_map.get(persona.entity_id).name if entity_map.get(persona.entity_id) else f"Agent_{index}",
                "profile": {
                    "entity_id": persona.entity_id,
                    "entity_kind": (
                        entity_map.get(persona.entity_id).entity_type
                        if entity_map.get(persona.entity_id)
                        else "person"
                    ),
                    "identity_summary": persona.identity_summary,
                    "goals": persona.goals,
                    "behavior_style": persona.behavior_style,
                    "speech_style": persona.speech_style,
                },
            }
            for index, persona in enumerate(world_state.personas)
        ]

    async def get_status(self, world_id: str) -> Optional[Dict[str, Any]]:
        """Return authoritative simulation status for a world."""
        world_state = await self._repo.load_world_state(world_id)
        if world_state is None:
            return None

        time_config = {}
        for global_var in world_state.global_variables:
            if global_var.name == "time_config" and isinstance(global_var.value, dict):
                time_config = global_var.value
                break

        latest_run = await self._repo.get_latest_run(world_id)

        return {
            "world_id": world_id,
            "initialized": bool(world_state.personas),
            "current_tick": world_state.current_tick,
            "agent_count": len(world_state.personas),
            "tick_seconds": time_config.get("tick_seconds"),
            "time_horizon_days": time_config.get("horizon_days"),
            "recommended_steps": time_config.get("recommended_steps"),
            "latest_run_id": latest_run.run_id if latest_run else None,
            "latest_run_status": latest_run.status if latest_run else None,
            "latest_run_steps": latest_run.steps_executed if latest_run else 0,
            "latest_run_new_event_count": latest_run.new_event_count if latest_run else 0,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _assemble_simulation(self, world_state):
        """根据 WorldState 组装 WorldStateManager、智能体和路由。"""
        world_manager = WorldStateManager(world_state)

        # Build agents from personas
        agents: List[WorldSimAgent] = []
        persona_map = {p.entity_id: p for p in world_state.personas}
        entity_map = {e.id: e for e in world_state.entities}

        for i, persona in enumerate(world_state.personas):
            entity = entity_map.get(persona.entity_id)
            entity_attributes = entity.attributes if entity else {}
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
                "simulation_priority_topics": entity_attributes.get("simulation_priority_topics", []),
                "simulation_priority_targets": entity_attributes.get("simulation_priority_targets", []),
                "simulation_activity_bias": entity_attributes.get("simulation_activity_bias", ""),
                "simulation_activity_level": entity_attributes.get("simulation_activity_level", "medium"),
                "simulation_active_hours": entity_attributes.get("simulation_active_hours", []),
                "simulation_response_delay_ticks": entity_attributes.get("simulation_response_delay_ticks", 0),
            }
            agent = WorldSimAgent(
                id=i,
                profile=profile,
                name=profile["name"],
            )
            agents.append(agent)

        env_modules = self._module_router_builder.build_agent_env_modules(
            world_manager=world_manager,
            world_state=world_state,
        )

        for module in env_modules:
            if isinstance(module, SocialMediaSpace):
                await module.init(datetime.utcnow())

        router = WorldRouter(env_modules=env_modules, router_role="agent")

        return world_manager, agents, router

    def _resolve_tick_seconds(self, world_state, tick_seconds: Optional[int]) -> int:
        if tick_seconds and tick_seconds > 0:
            return tick_seconds

        for g in world_state.global_variables:
            if g.name != "time_config" or not isinstance(g.value, dict):
                continue
            resolved = g.value.get("tick_seconds")
            if isinstance(resolved, int) and resolved > 0:
                return resolved

        return 300
