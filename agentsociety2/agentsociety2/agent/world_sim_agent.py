"""
WorldSimAgent: Default agent for LLM-driven virtual world simulation.

职责：
- 作为新系统的默认 Agent，取代 PersonAgent 成为虚拟世界仿真的主要实体
- 支持通用实体角色：个人、组织、群体、媒体、观察者
- 支持 persona、belief、goal、memory 驱动的决策
- 支持通过世界环境工具行动
- 支持接收外部用户问题并基于自身状态回答
- 可接入 WorldRouter
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING

from agentsociety2.agent.base import AgentBase, DIALOG_TYPE_REFLECTION
from agentsociety2.config import extract_json, get_llm_router_and_model
from agentsociety2.logger import get_logger

if TYPE_CHECKING:
    from agentsociety2.storage import ReplayWriter
    from agentsociety2.env.router_base import RouterBase

__all__ = ["WorldSimAgent"]

# Supported entity kinds
ENTITY_KIND = Literal["person", "organization", "group", "media", "observer", "other"]


class WorldSimAgent(AgentBase):
    """
    WorldSimAgent: Universal agent for virtual world simulation.

    Supports any kind of world entity (person, organization, group, media, observer).
    Driven by a structured Persona with beliefs, goals, and memory.
    Actions are performed via WorldRouter + llm_world environment tools.

    PersonAgent is kept as legacy; WorldSimAgent is the new default.
    """

    def __init__(
        self,
        id: int,
        profile: Dict[str, Any],
        name: Optional[str] = None,
        replay_writer: Optional["ReplayWriter"] = None,
    ):
        """
        Initialize WorldSimAgent.

        Args:
            id: Unique agent ID.
            profile: Agent profile dict. Expected keys:
                - name (str): Display name.
                - entity_kind (str): person / organization / group / media / observer / other.
                - identity_summary (str): Who this entity is.
                - goals (list[str]): What this entity wants to achieve.
                - fears (list[str], optional): What this entity wants to avoid.
                - preferences (list[str], optional): Behavioral tendencies.
                - stance_map (dict, optional): Stances toward topics/entities.
                - behavior_style (str, optional): How this entity acts.
                - speech_style (str, optional): How this entity communicates.
                - memory_seeds (list[str], optional): Initial memories.
            name: Override display name.
            replay_writer: Optional replay writer.
        """
        super().__init__(id=id, profile=profile, name=name, replay_writer=replay_writer)

        p = profile if isinstance(profile, dict) else {}

        self.entity_kind: str = p.get("entity_kind", "person")
        self.identity_summary: str = p.get("identity_summary", "")
        self.goals: List[str] = p.get("goals", [])
        self.fears: List[str] = p.get("fears", [])
        self.preferences: List[str] = p.get("preferences", [])
        self.stance_map: Dict[str, Any] = p.get("stance_map", {})
        self.behavior_style: str = p.get("behavior_style", "")
        self.speech_style: str = p.get("speech_style", "")
        self.simulation_priority_topics: List[str] = p.get("simulation_priority_topics", [])
        self.simulation_priority_targets: List[str] = p.get("simulation_priority_targets", [])
        self.simulation_activity_bias: str = p.get("simulation_activity_bias", "")
        self.simulation_activity_level: str = p.get("simulation_activity_level", "medium")
        self.simulation_active_hours: List[int] = p.get("simulation_active_hours", [])
        self.simulation_response_delay_ticks: int = p.get("simulation_response_delay_ticks", 0)

        # Dynamic state
        self.beliefs: Dict[str, Any] = {}
        self.current_goal: Optional[str] = self.goals[0] if self.goals else None
        self.emotions: Dict[str, float] = {}
        self.resources: Dict[str, Any] = {}
        self.alliances: List[int] = []  # agent IDs
        self.recent_memories: List[str] = list(p.get("memory_seeds", []))
        self.status: str = "active"

        # Short-term context for current step
        self._current_observation: str = ""
        self._current_tick: int = 0
        self._current_t: Optional[datetime] = None

        self._logger = get_logger()

    # ------------------------------------------------------------------
    # Core simulation interface
    # ------------------------------------------------------------------

    async def observe(self, tick: int, t: datetime) -> str:
        """
        Build observation for current simulation step.
        Called by SimulationEngine before decision-making.
        """
        self._current_tick = tick
        self._current_t = t
        observation = self._build_observation_context()

        world_summary = self._fetch_world_summary()
        if world_summary:
            observation = f"{observation}\n\n## World State\n{world_summary}"

        self._current_observation = observation
        return observation

    async def decide(self, observation: str) -> str:
        """
        Use LLM to form an intention and decide on an action.
        Returns a natural-language action instruction for the router.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = f"""## Current Observation

{observation}

## Task

Based on your persona, goals, and the current observation, decide what action to take right now.
Output a single, concrete action instruction that can be executed by your available tools.
Be specific. Choose the most important action aligned with your current goal: "{self.current_goal}"."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await self.acompletion(messages=messages, stream=False)
            decision = response.choices[0].message.content or ""
            self._logger.info(
                f"WorldSimAgent[{self._id}] decision: {decision[:200]!r}"
            )
            return decision.strip()
        except Exception as e:
            self._logger.error(f"WorldSimAgent[{self._id}] decide() failed: {e}")
            return "Observe surroundings and assess the current situation."

    async def step(self, tick: int, t: datetime) -> str:
        """
        Full agent step: observe → decide → act via router.

        Returns:
            Summary of what the agent did this step.
        """
        if self._env is None:
            self._logger.warning(
                f"WorldSimAgent[{self._id}]: No environment router set, skipping step."
            )
            return "No environment router available."

        observation = await self.observe(tick, t)
        instruction = await self.decide(observation)

        ctx = self._build_action_ctx(tick, t)
        ctx, answer = await self._env.ask(ctx, instruction, readonly=False)

        await self._post_step_reflection(tick, t, instruction, answer)

        return answer

    async def answer_user_question(self, question: str) -> str:
        """
        Answer an external user question based on this agent's identity and state.
        Used by POST /api/v1/worlds/{world_id}/agents/{agent_id}/chat.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = f"""An external observer is asking you a question. 
Answer from your own perspective, based on your identity, beliefs, and current state.

Question: {question}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await self.acompletion(messages=messages, stream=False)
            return response.choices[0].message.content or ""
        except Exception as e:
            self._logger.error(
                f"WorldSimAgent[{self._id}] answer_user_question() failed: {e}"
            )
            return f"[Agent {self._name} could not respond due to an error]"

    def add_memory(self, memory: str) -> None:
        """Add a memory entry (keep last 50)."""
        self.recent_memories.append(memory)
        if len(self.recent_memories) > 50:
            self.recent_memories = self.recent_memories[-50:]

    def update_belief(self, key: str, value: Any) -> None:
        """Update a belief."""
        self.beliefs[key] = value

    def update_stance(self, topic: str, stance: Any) -> None:
        """Update stance toward a topic or entity."""
        self.stance_map[topic] = stance

    def set_current_goal(self, goal: str) -> None:
        """Update the agent's active goal."""
        self.current_goal = goal

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the system prompt from this agent's persona."""
        goals_str = "\n".join(f"  - {g}" for g in self.goals) if self.goals else "  (none)"
        fears_str = "\n".join(f"  - {f}" for f in self.fears) if self.fears else "  (none)"
        stances_str = (
            "\n".join(f"  - {k}: {v}" for k, v in self.stance_map.items())
            if self.stance_map
            else "  (none)"
        )
        beliefs_str = (
            "\n".join(f"  - {k}: {v}" for k, v in self.beliefs.items())
            if self.beliefs
            else "  (none)"
        )
        memory_str = (
            "\n".join(f"  - {m}" for m in self.recent_memories[-10:])
            if self.recent_memories
            else "  (none)"
        )
        sim_topics_str = (
            "\n".join(f"  - {topic}" for topic in self.simulation_priority_topics)
            if self.simulation_priority_topics
            else "  (none)"
        )
        sim_targets_str = (
            "\n".join(f"  - {target}" for target in self.simulation_priority_targets)
            if self.simulation_priority_targets
            else "  (none)"
        )

        return f"""You are a simulated entity inside a virtual world simulation.

## Your Identity

- **Name**: {self._name}
- **Kind**: {self.entity_kind}
- **Summary**: {self.identity_summary}
- **Behavior style**: {self.behavior_style or 'neutral'}
- **Speech style**: {self.speech_style or 'neutral'}

## Your Goals
{goals_str}

## Your Fears
{fears_str}

## Your Stances
{stances_str}

## Your Current Beliefs
{beliefs_str}

## Your Recent Memories
{memory_str}

## Simulation Attention Priorities
Priority topics:
{sim_topics_str}

Priority targets:
{sim_targets_str}

Activity bias: {self.simulation_activity_bias or '(none)'}
Activity level: {self.simulation_activity_level or 'medium'}
Active hours: {', '.join(str(hour) for hour in self.simulation_active_hours) if self.simulation_active_hours else '(all day)'}
Response delay ticks: {self.simulation_response_delay_ticks}

## Current Goal
{self.current_goal or '(none set)'}

Always act consistently with your identity. You are a first-person participant in this world, not an outside observer."""

    def _build_observation_context(self) -> str:
        """Build a text description of the agent's current situation."""
        return (
            f"[Tick {self._current_tick}] "
            f"You are {self._name} ({self.entity_kind}). "
            f"Current goal: {self.current_goal or 'none'}. "
            f"Status: {self.status}. "
            f"Priority topics: {', '.join(self.simulation_priority_topics) if self.simulation_priority_topics else 'none'}. "
            f"Priority targets: {', '.join(self.simulation_priority_targets) if self.simulation_priority_targets else 'none'}. "
            f"Activity bias: {self.simulation_activity_bias or 'none'}. "
            f"Activity level: {self.simulation_activity_level or 'medium'}. "
            f"Active hours: {', '.join(str(hour) for hour in self.simulation_active_hours) if self.simulation_active_hours else 'all day'}. "
            f"Response delay ticks: {self.simulation_response_delay_ticks}."
        )

    def _fetch_world_summary(self) -> str:
        """Fetch world summary from ObservationEnv if available in the router."""
        if self._env is None:
            return ""
        env_modules = getattr(self._env, 'env_modules', [])
        for module in env_modules:
            if hasattr(module, 'get_world_summary'):
                try:
                    entity_id = self._profile.get('entity_id') if isinstance(self._profile, dict) else None
                    result = module.get_world_summary(agent_id=entity_id)
                    if isinstance(result, dict):
                        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
                    return str(result)
                except Exception as e:
                    self._logger.warning(f"WorldSimAgent._fetch_world_summary: {e}")
        return ""

    def _build_action_ctx(self, tick: int, t: datetime) -> dict:
        """Build the context dict passed to the router."""
        profile = self._profile if isinstance(self._profile, dict) else {}
        return {
            "agent_id": self._id,
            "entity_id": profile.get("entity_id", ""),
            "agent_name": self._name,
            "entity_kind": self.entity_kind,
            "current_goal": self.current_goal,
            "tick": tick,
            "t": t.isoformat() if t else None,
            "beliefs": self.beliefs,
            "stance_map": self.stance_map,
            "alliances": self.alliances,
            "status": self.status,
        }

    async def _post_step_reflection(
        self, tick: int, t: datetime, instruction: str, action_result: str
    ) -> None:
        """
        Brief reflection after each step: update memory and beliefs if warranted.
        """
        memory_entry = f"[Tick {tick}] Action: {instruction[:100]} | Result: {action_result[:100]}"
        self.add_memory(memory_entry)

    def set_env(self, env: "RouterBase") -> None:
        """Set the environment router."""
        self._env = env

    # ------------------------------------------------------------------
    # Abstract method implementations (required by AgentBase)
    # ------------------------------------------------------------------

    async def ask(self, message: str, readonly: bool = True) -> str:
        """
        Answer an external question directed at this agent.

        In WorldSimAgent this delegates to answer_user_question.
        """
        return await self.answer_user_question(message)

    async def dump(self) -> dict:
        """Serialize agent state to a dict."""
        return {
            "id": self._id,
            "name": self._name,
            "entity_kind": self.entity_kind,
            "identity_summary": self.identity_summary,
            "goals": self.goals,
            "fears": self.fears,
            "preferences": self.preferences,
            "stance_map": self.stance_map,
            "behavior_style": self.behavior_style,
            "speech_style": self.speech_style,
            "beliefs": self.beliefs,
            "current_goal": self.current_goal,
            "emotions": self.emotions,
            "resources": self.resources,
            "alliances": self.alliances,
            "recent_memories": self.recent_memories,
            "status": self.status,
            "simulation_priority_topics": self.simulation_priority_topics,
            "simulation_priority_targets": self.simulation_priority_targets,
            "simulation_activity_bias": self.simulation_activity_bias,
            "simulation_activity_level": self.simulation_activity_level,
            "simulation_active_hours": self.simulation_active_hours,
            "simulation_response_delay_ticks": self.simulation_response_delay_ticks,
        }

    async def load(self, dump_data: dict) -> None:
        """Restore agent state from a serialized dict."""
        self.entity_kind = dump_data.get("entity_kind", self.entity_kind)
        self.identity_summary = dump_data.get("identity_summary", self.identity_summary)
        self.goals = dump_data.get("goals", self.goals)
        self.fears = dump_data.get("fears", self.fears)
        self.preferences = dump_data.get("preferences", self.preferences)
        self.stance_map = dump_data.get("stance_map", self.stance_map)
        self.behavior_style = dump_data.get("behavior_style", self.behavior_style)
        self.speech_style = dump_data.get("speech_style", self.speech_style)
        self.beliefs = dump_data.get("beliefs", self.beliefs)
        self.current_goal = dump_data.get("current_goal", self.current_goal)
        self.emotions = dump_data.get("emotions", self.emotions)
        self.resources = dump_data.get("resources", self.resources)
        self.alliances = dump_data.get("alliances", self.alliances)
        self.recent_memories = dump_data.get("recent_memories", self.recent_memories)
        self.status = dump_data.get("status", self.status)
        self.simulation_priority_topics = dump_data.get(
            "simulation_priority_topics", self.simulation_priority_topics
        )
        self.simulation_priority_targets = dump_data.get(
            "simulation_priority_targets", self.simulation_priority_targets
        )
        self.simulation_activity_bias = dump_data.get(
            "simulation_activity_bias", self.simulation_activity_bias
        )
        self.simulation_activity_level = dump_data.get(
            "simulation_activity_level", self.simulation_activity_level
        )
        self.simulation_active_hours = dump_data.get(
            "simulation_active_hours", self.simulation_active_hours
        )
        self.simulation_response_delay_ticks = dump_data.get(
            "simulation_response_delay_ticks", self.simulation_response_delay_ticks
        )

    @classmethod
    def mcp_description(cls) -> str:
        return f"""{cls.__name__}: Universal agent for virtual world simulation.

**Description:** Supports person / organization / group / media / observer entities.
Driven by persona (identity, goals, fears, stances, beliefs, memory).
Actions via WorldRouter + llm_world tools.

**Initialization Parameters:**
- id (int): Unique agent ID.
- profile (dict): Agent profile with keys: name, entity_kind, identity_summary, goals,
  fears (opt), preferences (opt), stance_map (opt), behavior_style (opt),
  speech_style (opt), memory_seeds (opt).
- name (str, optional): Override display name.
- replay_writer (ReplayWriter, optional): Replay writer.

**Example:**
```json
{{
  "id": 1,
  "profile": {{
    "name": "ACME Corp",
    "entity_kind": "organization",
    "identity_summary": "A major tech company seeking market dominance.",
    "goals": ["expand market share", "suppress competitors"],
    "fears": ["regulatory action", "public backlash"],
    "behavior_style": "aggressive and strategic"
  }}
}}
```
"""
