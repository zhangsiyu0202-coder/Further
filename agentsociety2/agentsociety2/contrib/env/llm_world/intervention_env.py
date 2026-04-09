"""
InterventionEnv: Provides external intervention injection tools for the world.

职责：
- 注入政策
- 注入舆情冲击
- 注入资源变化
- 注入人物/组织态度改变
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

from agentsociety2.env.base import EnvBase, tool
from agentsociety2.world.models import Intervention, WorldEvent

if TYPE_CHECKING:
    from agentsociety2.world.world_state import WorldStateManager

__all__ = ["InterventionEnv"]


class InterventionEnv(EnvBase):
    """
    Intervention environment module.

    Exposes tools that allow external actors (or privileged agents) to inject
    policy shocks, opinion shifts, resource changes, and attitude modifications
    into the running simulation.
    """

    def __init__(self, world_manager: "WorldStateManager"):
        super().__init__()
        self._world = world_manager

    @property
    def description(self) -> str:
        return (
            "InterventionEnv: Tools for injecting external interventions into the simulation "
            "(policy shocks, opinion shifts, resource changes, attitude modifications)."
        )

    async def step(self, tick: int, t: datetime) -> None:
        self.t = t

    @tool(readonly=False)
    def inject_policy_shock(
        self,
        policy_name: str,
        description: str,
        severity: float = 0.5,
        affected_entity_ids: Optional[list] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Inject a policy shock into the simulation world.

        Args:
            policy_name: Name of the policy.
            description: What the policy does.
            severity: Severity [0.0, 1.0].
            affected_entity_ids: Entities most impacted (optional).
            reason: Why this intervention is being made.

        Returns:
            Intervention ID and status.
        """
        intervention = Intervention(
            world_id=self._world.world_id,
            intervention_type="policy_shock",
            payload={
                "policy_name": policy_name,
                "description": description,
                "severity": severity,
                "affected_entities": affected_entity_ids or [],
            },
            reason=reason,
        )
        self._world.apply_intervention(intervention)

        # Also set a global variable for the policy
        self._world.set_global_variable(
            f"policy:{policy_name}",
            {"active": True, "severity": severity, "description": description},
            description=f"Policy shock: {policy_name}",
        )

        return {"success": True, "intervention_id": intervention.intervention_id}

    @tool(readonly=False)
    def inject_opinion_shift(
        self,
        topic: str,
        shift_direction: str,
        magnitude: float = 0.3,
        affected_entity_ids: Optional[list] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Inject a public opinion shift on a topic.

        Args:
            topic: The topic affected.
            shift_direction: Direction of shift ('positive' or 'negative').
            magnitude: Magnitude of shift [0.0, 1.0].
            affected_entity_ids: Entities whose stance toward the topic changes.
            reason: Why this intervention is being made.

        Returns:
            Intervention ID and status.
        """
        intervention = Intervention(
            world_id=self._world.world_id,
            intervention_type="opinion_shift",
            payload={
                "topic": topic,
                "direction": shift_direction,
                "magnitude": magnitude,
                "affected_entities": affected_entity_ids or [],
            },
            reason=reason,
        )
        self._world.apply_intervention(intervention)

        # Update global variable to track opinion
        self._world.set_global_variable(
            f"opinion:{topic}",
            {"direction": shift_direction, "magnitude": magnitude},
            description=f"Opinion on: {topic}",
        )

        return {"success": True, "intervention_id": intervention.intervention_id}

    @tool(readonly=False)
    def inject_resource_change(
        self,
        entity_id: str,
        resource_type: str,
        delta: float,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Change a resource value for a specific entity.

        Args:
            entity_id: Target entity ID.
            resource_type: Type of resource (e.g., 'funds', 'personnel', 'reputation').
            delta: Amount to add (positive) or remove (negative).
            reason: Why this is happening.

        Returns:
            Success status and new resource level (if tracked).
        """
        agent_state = self._world.get_agent_state(entity_id)
        if not agent_state:
            return {"success": False, "error": f"No agent state for entity '{entity_id}'"}

        current = agent_state.resources.get(resource_type, 0.0)
        agent_state.resources[resource_type] = current + delta
        self._world.update_agent_state(agent_state)

        # Record intervention event
        intervention = Intervention(
            world_id=self._world.world_id,
            intervention_type="resource_change",
            payload={
                "entity_id": entity_id,
                "resource_type": resource_type,
                "delta": delta,
                "new_value": agent_state.resources[resource_type],
            },
            reason=reason,
        )
        self._world.apply_intervention(intervention)

        return {
            "success": True,
            "intervention_id": intervention.intervention_id,
            "new_value": agent_state.resources[resource_type],
        }

    @tool(readonly=False)
    def inject_attitude_change(
        self,
        entity_id: str,
        target_entity_id: str,
        new_polarity: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Force a change in one entity's attitude toward another.

        Args:
            entity_id: The entity whose attitude changes.
            target_entity_id: The entity being perceived.
            new_polarity: New polarity — 'positive', 'neutral', or 'negative'.
            reason: Why this intervention is being made.

        Returns:
            Success status.
        """
        if new_polarity not in ("positive", "neutral", "negative"):
            return {
                "success": False,
                "error": "polarity must be positive, neutral, or negative",
            }

        success = self._world.update_relation_polarity(
            entity_id, target_entity_id, new_polarity
        )

        intervention = Intervention(
            world_id=self._world.world_id,
            intervention_type="attitude_change",
            payload={
                "entity_id": entity_id,
                "target_entity_id": target_entity_id,
                "new_polarity": new_polarity,
            },
            reason=reason,
        )
        self._world.apply_intervention(intervention)

        return {
            "success": success,
            "intervention_id": intervention.intervention_id,
        }

    @tool(readonly=False)
    def set_global_variable(
        self,
        variable_name: str,
        value: Any,
        description: str = "",
    ) -> Dict[str, Any]:
        """
        Directly set a global world variable.

        Args:
            variable_name: Variable name.
            value: New value (any JSON-serializable type).
            description: Optional description.

        Returns:
            Success status.
        """
        self._world.set_global_variable(variable_name, value, description)
        return {"success": True, "variable_name": variable_name, "value": value}
