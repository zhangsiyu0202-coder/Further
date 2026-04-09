"""
Interaction: Orchestrate chat/intervene/report requests from external users.

职责：
- 对接外部 chat/intervene/report 请求
- 类型 A: 和世界对话（通过 ReportAgent 或直接 LLM）
- 类型 B: 和单个 Agent 对话
- 类型 C: 注入干预
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentsociety2.config import get_llm_router_and_model
from agentsociety2.logger import get_logger
from agentsociety2.world.models import Intervention, WorldEvent
from agentsociety2.world.prompts import WORLD_CHAT_PROMPT
from agentsociety2.world.world_state import WorldStateManager

if TYPE_CHECKING:
    from agentsociety2.agent.world_sim_agent import WorldSimAgent

__all__ = ["WorldInteraction"]


class WorldInteraction:
    """
    Handles external interactions with the virtual world:
    - chat with world (type A)
    - chat with a specific agent (type B)
    - inject interventions (type C)
    """

    def __init__(
        self,
        world_manager: WorldStateManager,
        agents: Optional[List["WorldSimAgent"]] = None,
    ):
        self._world = world_manager
        self._agent_map: Dict[str, "WorldSimAgent"] = {}
        if agents:
            for agent in agents:
                profile = agent._profile if isinstance(agent._profile, dict) else {}
                entity_id = profile.get("entity_id", str(agent.id))
                self._agent_map[entity_id] = agent

        self._llm_router, self._model_name = get_llm_router_and_model("default")
        self._logger = get_logger()

    # ------------------------------------------------------------------
    # Type A: Chat with the world
    # ------------------------------------------------------------------

    async def chat_with_world(self, message: str) -> Dict[str, Any]:
        """
        Answer a user question about the current world state.

        Returns:
            {"answer": str, "sources": list[str]}
        """
        snapshot_summary = self._world.to_summary_text(max_events=15)

        relations_summary = "\n".join(
            f"  - {r.source_entity_id} → {r.target_entity_id}: {r.relation_type} "
            f"({r.polarity}, strength={r.strength:.2f})"
            for r in self._world.relations[:30]
        )

        timeline_summary = "\n".join(
            f"  [tick {e.tick}] {e.title}: {e.description[:80]}"
            for e in self._world.get_recent_events(limit=20)
        )

        prompt = WORLD_CHAT_PROMPT.format(
            world_snapshot_summary=snapshot_summary[:3000],
            timeline_summary=timeline_summary or "(no events yet)",
            relations_summary=relations_summary or "(no relations)",
            question=message,
        )

        try:
            response = await self._llm_router.acompletion(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
            )
            answer = response.choices[0].message.content or ""
        except Exception as e:
            self._logger.error(f"WorldInteraction.chat_with_world failed: {e}")
            answer = f"[Error generating response: {e}]"

        return {
            "answer": answer,
            "sources": ["timeline", "relations", "snapshot"],
        }

    # ------------------------------------------------------------------
    # Type B: Chat with a specific agent
    # ------------------------------------------------------------------

    async def chat_with_agent(self, entity_id: str, message: str) -> Dict[str, Any]:
        """
        Send a question to a specific agent and get a response in-character.

        Args:
            entity_id: The entity ID of the target agent.
            message: The user's question.

        Returns:
            {"agent_id": str, "answer": str, "success": bool}
        """
        agent = self._agent_map.get(entity_id)
        if not agent:
            # Try numeric ID lookup
            for k, a in self._agent_map.items():
                if str(a.id) == entity_id:
                    agent = a
                    break

        if not agent:
            return {
                "agent_id": entity_id,
                "answer": f"Agent '{entity_id}' not found in this world.",
                "success": False,
            }

        try:
            answer = await agent.answer_user_question(message)
            return {"agent_id": entity_id, "answer": answer, "success": True}
        except Exception as e:
            self._logger.error(
                f"WorldInteraction.chat_with_agent '{entity_id}' failed: {e}"
            )
            return {
                "agent_id": entity_id,
                "answer": f"[Error: {e}]",
                "success": False,
            }

    # ------------------------------------------------------------------
    # Type C: Apply intervention
    # ------------------------------------------------------------------

    async def apply_intervention(self, intervention: Intervention) -> Dict[str, Any]:
        """
        Inject an external intervention into the world.

        Returns:
            {"success": bool, "intervention_id": str, "tick": int}
        """
        try:
            self._world.apply_intervention(intervention)
            return {
                "success": True,
                "intervention_id": intervention.intervention_id,
                "tick": self._world.current_tick,
            }
        except Exception as e:
            self._logger.error(
                f"WorldInteraction.apply_intervention failed: {e}"
            )
            return {
                "success": False,
                "intervention_id": intervention.intervention_id,
                "error": str(e),
            }

    def register_agent(self, entity_id: str, agent: "WorldSimAgent") -> None:
        """Register an agent with the interaction layer."""
        self._agent_map[entity_id] = agent
