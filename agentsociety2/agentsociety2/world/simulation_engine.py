"""
SimulationEngine: Advance the virtual world tick by tick.

职责：
- 迭代活动 Agent，驱动 observe → decide → act 循环
- 写入新事件到世界时间线
- 更新关系和全局变量
- 产生 SimulationRun 元数据
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING

from agentsociety2.logger import get_logger
from agentsociety2.world.models import (
    AgentState,
    SimulationRun,
    WorldEvent,
    WorldState,
)
from agentsociety2.world.world_state import WorldStateManager

if TYPE_CHECKING:
    from agentsociety2.agent.world_sim_agent import WorldSimAgent
    from agentsociety2.env.router_world import WorldRouter

__all__ = ["SimulationEngine"]


class SimulationEngine:
    """
    Drives multi-agent simulation over a WorldStateManager.

    Usage:
        engine = SimulationEngine(world_manager, agents, router)
        run = await engine.run(steps=10, tick_seconds=300)
    """

    def __init__(
        self,
        world_manager: WorldStateManager,
        agents: List["WorldSimAgent"],
        router: "WorldRouter",
    ):
        self._world = world_manager
        self._agents = agents
        self._router = router
        self._logger = get_logger()

        # Map entity_id → agent
        self._agent_map: Dict[str, "WorldSimAgent"] = {}
        for agent in agents:
            # WorldSimAgent profile may contain entity_id
            profile = agent._profile if isinstance(agent._profile, dict) else {}
            entity_id = profile.get("entity_id", str(agent.id))
            self._agent_map[entity_id] = agent
            agent.set_env(router)

    async def run(
        self,
        steps: int,
        tick_seconds: int = 300,
        run_id: Optional[str] = None,
        stop_when_stable: bool = False,
        after_step: Optional[Callable[[int], Optional[Awaitable[None]]]] = None,
    ) -> SimulationRun:
        """
        Run the simulation for a given number of steps.

        Args:
            steps: Number of ticks to advance.
            tick_seconds: Seconds per tick (virtual time).
            run_id: Optional run ID (auto-generated if not provided).
            stop_when_stable: If True, stop early when no new events are produced.

        Returns:
            SimulationRun metadata.
        """
        from agentsociety2.world.models import _new_id

        sim_run = SimulationRun(
            run_id=run_id or _new_id("run_"),
            world_id=self._world.world_id,
            start_tick=self._world.current_tick,
            steps_requested=steps,
            tick_seconds=tick_seconds,
        )

        self._logger.info(
            f"SimulationEngine: starting run '{sim_run.run_id}' "
            f"steps={steps}, tick_seconds={tick_seconds}"
        )

        base_t = datetime.utcnow()

        for step_idx in range(steps):
            tick = self._world.advance_tick()
            t = base_t + timedelta(seconds=tick * tick_seconds)

            events_before = len(self._world.timeline)
            await self._run_single_step(tick, t, tick_seconds)
            new_events = len(self._world.timeline) - events_before

            if after_step is not None:
                maybe_awaitable = after_step(tick)
                if maybe_awaitable is not None:
                    await maybe_awaitable

            sim_run.steps_executed += 1
            sim_run.new_event_count += new_events

            if stop_when_stable and new_events == 0 and step_idx > 0:
                self._logger.info(
                    f"SimulationEngine: stopping early at tick {tick} (no new events)"
                )
                break

        sim_run.end_tick = self._world.current_tick
        sim_run.status = "completed"
        sim_run.completed_at = datetime.utcnow()

        self._logger.info(
            f"SimulationEngine: run '{sim_run.run_id}' complete — "
            f"{sim_run.steps_executed} steps, {sim_run.new_event_count} new events"
        )
        return sim_run

    async def step(self, tick_seconds: int = 300) -> Dict[str, Any]:
        """
        Advance a single tick and return summary.
        """
        tick = self._world.advance_tick()
        t = datetime.utcnow()
        events_before = len(self._world.timeline)
        executed_agents = await self._run_single_step(tick, t, tick_seconds)
        new_events = len(self._world.timeline) - events_before
        return {
            "tick": tick,
            "new_events": new_events,
            "active_agents": executed_agents,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run_single_step(self, tick: int, t: datetime, tick_seconds: int) -> int:
        """Run one simulation tick over a scheduled subset of active agents."""
        active_states = self._world.active_agent_states
        system_event = self._inject_system_context_event(tick)
        scheduled_states = self._select_active_agents_for_tick(
            active_states=active_states,
            tick=tick,
            tick_seconds=tick_seconds,
        )

        for agent_state in scheduled_states:
            agent = self._agent_map.get(agent_state.entity_id)
            if not agent:
                continue
            try:
                result_summary = await agent.step(tick=tick, t=t)

                # Record the step result as a world event
                event = WorldEvent(
                    tick=tick,
                    event_type="agent_action",
                    title=f"{agent._name} acted",
                    description=result_summary[:300],
                    participants=[agent_state.entity_id],
                    parent_event_id=system_event.id if system_event else None,
                    source_entity_id=agent_state.entity_id,
                    source_module="simulation_engine",
                    trigger_reason=(
                        f"Agent responded to tick {tick} world state"
                        + (f" after '{system_event.title}'." if system_event else ".")
                    ),
                    created_by="agent",
                )
                self._world.add_event(event)

                # Update agent's recent_memories in WorldState
                self._world.add_agent_memory(
                    agent_state.entity_id,
                    f"[Tick {tick}] {result_summary[:100]}",
                )

            except Exception as e:
                self._logger.error(
                    f"SimulationEngine: agent '{agent._name}' failed at tick {tick}: {e}"
                )
        return len(scheduled_states)

    def _select_active_agents_for_tick(
        self,
        active_states: List[AgentState],
        tick: int,
        tick_seconds: int,
    ) -> List[AgentState]:
        if len(active_states) <= 1:
            return active_states

        current_hour = self._get_virtual_hour(tick, tick_seconds)
        time_config = self._get_time_config()
        eligible_states = [
            state
            for state in active_states
            if self._is_agent_active_this_hour(state.entity_id, current_hour)
            and self._satisfies_response_delay(state.entity_id, tick)
        ]
        if not eligible_states:
            eligible_states = active_states

        target_count = self._resolve_target_agent_count(
            eligible_count=len(eligible_states),
            current_hour=current_hour,
            time_config=time_config,
        )
        if target_count >= len(eligible_states):
            return eligible_states

        weighted_states = []
        for state in eligible_states:
            weight = self._resolve_agent_activity_weight(state.entity_id)
            if weight <= 0:
                continue
            weighted_states.append((state, weight))

        if not weighted_states:
            return eligible_states[:target_count]

        selected: List[AgentState] = []
        pool = list(weighted_states)
        while pool and len(selected) < target_count:
            total_weight = sum(weight for _, weight in pool)
            if total_weight <= 0:
                break
            threshold = random.uniform(0, total_weight)
            cumulative = 0.0
            chosen_idx = 0
            for idx, (_, weight) in enumerate(pool):
                cumulative += weight
                if cumulative >= threshold:
                    chosen_idx = idx
                    break
            chosen_state, _ = pool.pop(chosen_idx)
            selected.append(chosen_state)

        return selected or eligible_states[:target_count]

    def _get_virtual_hour(self, tick: int, tick_seconds: int) -> int:
        elapsed_seconds = max(0, tick * max(1, tick_seconds))
        return int((elapsed_seconds // 3600) % 24)

    def _get_time_config(self) -> Dict[str, Any]:
        time_config = self._world.get_global_variable("time_config")
        if time_config and isinstance(time_config.value, dict):
            return time_config.value
        return {}

    def _is_agent_active_this_hour(self, entity_id: str, current_hour: int) -> bool:
        entity = self._world.get_entity(entity_id)
        if not entity:
            return True
        active_hours = entity.attributes.get("simulation_active_hours")
        if not isinstance(active_hours, list) or not active_hours:
            return True
        normalized_hours = {
            hour for hour in active_hours if isinstance(hour, int) and 0 <= hour <= 23
        }
        if not normalized_hours:
            return True
        return current_hour in normalized_hours

    def _resolve_target_agent_count(
        self,
        eligible_count: int,
        current_hour: int,
        time_config: Dict[str, Any],
    ) -> int:
        if eligible_count <= 1:
            return eligible_count

        peak_hours = self._normalize_hour_list(time_config.get("peak_hours"))
        off_peak_hours = self._normalize_hour_list(time_config.get("off_peak_hours"))

        min_count = time_config.get("agents_per_tick_min")
        max_count = time_config.get("agents_per_tick_max")

        if not isinstance(min_count, int) or min_count <= 0:
            min_count = 1
        if not isinstance(max_count, int) or max_count <= 0:
            max_count = min(eligible_count, max(1, round(eligible_count * 0.6)))

        max_count = max(min_count, min(max_count, eligible_count))
        min_count = min(min_count, max_count)

        if current_hour in peak_hours:
            return max_count
        if current_hour in off_peak_hours:
            return min_count

        midpoint = round((min_count + max_count) / 2)
        return max(min_count, min(midpoint, eligible_count))

    def _normalize_hour_list(self, raw: Any) -> set[int]:
        if not isinstance(raw, list):
            return set()
        return {
            hour for hour in raw if isinstance(hour, int) and 0 <= hour <= 23
        }

    def _resolve_agent_activity_weight(self, entity_id: str) -> float:
        entity = self._world.get_entity(entity_id)
        if not entity:
            return 1.0
        activity_level = str(
            entity.attributes.get("simulation_activity_level", "medium")
        ).strip().lower()
        weights = {
            "low": 0.4,
            "medium": 1.0,
            "high": 1.8,
        }
        return weights.get(activity_level, 1.0)

    def _satisfies_response_delay(self, entity_id: str, current_tick: int) -> bool:
        entity = self._world.get_entity(entity_id)
        if not entity:
            return True

        response_delay_ticks = entity.attributes.get("simulation_response_delay_ticks", 0)
        if not isinstance(response_delay_ticks, int) or response_delay_ticks <= 0:
            return True

        recent_actions = [
            event
            for event in self._world.get_recent_events(limit=200, event_type="agent_action")
            if entity_id in event.participants
        ]
        if not recent_actions:
            return True

        last_tick = max(event.tick for event in recent_actions)
        return (current_tick - last_tick) > response_delay_ticks

    def _inject_system_context_event(self, tick: int) -> Optional[WorldEvent]:
        event_config = self._world.get_global_variable("event_config")
        if not event_config or not isinstance(event_config.value, dict):
            return None

        hot_topics = [str(topic).strip() for topic in event_config.value.get("hot_topics", []) if str(topic).strip()]
        if not hot_topics:
            return None

        topic = hot_topics[(tick - 1) % len(hot_topics)]
        narrative_direction = self._world.get_global_variable("narrative_direction")
        narrative_text = (
            str(narrative_direction.value).strip()
            if narrative_direction and narrative_direction.value is not None
            else ""
        )

        description = f"Current discussion focus: {topic}."
        if narrative_text:
            description = f"{description} Narrative direction: {narrative_text}"

        event = WorldEvent(
            tick=tick,
            event_type="system_topic",
            title=f"Topic pulse: {topic}",
            description=description,
            source_module="simulation_engine",
            trigger_reason="Scheduled topic pulse derived from event_config.hot_topics.",
            created_by="system",
        )
        self._world.add_event(event)
        return event
