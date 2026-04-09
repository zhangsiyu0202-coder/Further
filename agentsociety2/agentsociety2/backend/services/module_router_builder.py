"""
ModuleRouterBuilder: Assemble env modules for agent-side and user-side tooling.

职责：
- 根据 world 配置构建 agent 可用工具模块
- 根据 world 配置构建用户/操作者可用工具模块
- 保持 `llm_world` 核心运行时工具与 operator 工具边界清晰
"""

from __future__ import annotations

from typing import Any, Dict, List

from agentsociety2.contrib.env.global_information import GlobalInformationEnv
from agentsociety2.contrib.env.llm_world import (
    CommunicationEnv,
    EventTimelineEnv,
    InterventionEnv,
    ObservationEnv,
    RelationGraphEnv,
    ReportEnv,
)
from agentsociety2.contrib.env.social_media import SocialMediaSpace

__all__ = [
    "DEFAULT_AGENT_TOOL_MODULES",
    "DEFAULT_USER_TOOL_MODULES",
    "ModuleRouterBuilder",
]


DEFAULT_AGENT_TOOL_MODULES: Dict[str, bool] = {
    "observation": True,
    "relation": True,
    "communication": True,
    "timeline": True,
    "social_propagation": True,
    "global_information": False,
}

DEFAULT_USER_TOOL_MODULES: Dict[str, bool] = {
    "intervention": True,
    "report": True,
}


class ModuleRouterBuilder:
    """Build env module lists with separate agent/user tool scopes."""

    def _get_module_flags(
        self,
        world_state,
        variable_name: str,
        defaults: Dict[str, bool],
    ) -> Dict[str, bool]:
        for g in world_state.global_variables:
            if g.name != variable_name or not isinstance(g.value, dict):
                continue
            normalized = dict(defaults)
            for key, value in g.value.items():
                if key in normalized:
                    normalized[key] = bool(value)
            return normalized
        return dict(defaults)

    def get_agent_tool_modules(self, world_state) -> Dict[str, bool]:
        legacy = self._get_module_flags(
            world_state=world_state,
            variable_name="capability_modules",
            defaults=DEFAULT_AGENT_TOOL_MODULES,
        )
        explicit = self._get_module_flags(
            world_state=world_state,
            variable_name="agent_tool_modules",
            defaults=legacy,
        )
        return explicit

    def get_user_tool_modules(self, world_state) -> Dict[str, bool]:
        return self._get_module_flags(
            world_state=world_state,
            variable_name="user_tool_modules",
            defaults=DEFAULT_USER_TOOL_MODULES,
        )

    def build_agent_env_modules(self, world_manager, world_state) -> List[Any]:
        capabilities = self.get_agent_tool_modules(world_state)
        env_modules: List[Any] = []

        if capabilities.get("observation"):
            env_modules.append(ObservationEnv(world_manager))
        if capabilities.get("relation"):
            env_modules.append(RelationGraphEnv(world_manager))
        if capabilities.get("communication"):
            env_modules.append(CommunicationEnv(world_manager))
        if capabilities.get("timeline"):
            env_modules.append(EventTimelineEnv(world_manager))
        if capabilities.get("social_propagation"):
            agent_pairs = []
            for persona in world_state.personas:
                entity = next((e for e in world_state.entities if e.id == persona.entity_id), None)
                agent_pairs.append((persona.entity_id, entity.name if entity else persona.entity_id))
            env_modules.append(
                SocialMediaSpace(
                    agent_id_name_pairs=agent_pairs,
                    world_manager=world_manager,
                )
            )
        if capabilities.get("global_information"):
            global_info = GlobalInformationEnv()
            global_info._global_information = world_manager.to_summary_text(max_events=8)
            env_modules.append(global_info)

        return env_modules

    def build_user_env_modules(self, world_manager, world_state) -> List[Any]:
        capabilities = self.get_user_tool_modules(world_state)
        env_modules: List[Any] = []

        if capabilities.get("intervention"):
            env_modules.append(InterventionEnv(world_manager))
        if capabilities.get("report"):
            env_modules.append(ReportEnv(world_manager))

        return env_modules

    def build_env_modules(self, world_manager, world_state) -> List[Any]:
        """Backward-compatible alias for agent-side tool assembly."""
        return self.build_agent_env_modules(world_manager=world_manager, world_state=world_state)
