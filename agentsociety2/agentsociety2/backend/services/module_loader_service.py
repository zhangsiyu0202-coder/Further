"""
ModuleLoaderService：枚举可用的世界环境模块与智能体类型。

职责：
- 枚举可用的 llm_world 环境模块
- 枚举可用的 Agent 类型
"""

from __future__ import annotations

from typing import Any, Dict, List

__all__ = ["ModuleLoaderService"]


class ModuleLoaderService:
    """用于列出可用世界模块与智能体类型的服务。"""

    def list_env_modules(self) -> List[Dict[str, Any]]:
        """列出所有可用的 llm_world 环境模块。"""
        return [
            {
                "name": "ObservationEnv",
                "module": "agentsociety2.contrib.env.llm_world.observation_env",
                "description": "为智能体提供语义化观察工具，例如事件、世界摘要与实体信息。",
                "kind": "llm_world",
            },
            {
                "name": "RelationGraphEnv",
                "module": "agentsociety2.contrib.env.llm_world.relation_graph_env",
                "description": "用于查询和更新实体关系的工具集。",
                "kind": "llm_world",
            },
            {
                "name": "CommunicationEnv",
                "module": "agentsociety2.contrib.env.llm_world.communication_env",
                "description": "支持智能体之间的私聊、群聊与广播通信。",
                "kind": "llm_world",
            },
            {
                "name": "EventTimelineEnv",
                "module": "agentsociety2.contrib.env.llm_world.event_timeline_env",
                "description": "用于创建、查询并响应世界事件。",
                "kind": "llm_world",
            },
            {
                "name": "InterventionEnv",
                "module": "agentsociety2.contrib.env.llm_world.intervention_env",
                "description": "用于注入政策冲击、观点变化与资源变动。",
                "kind": "llm_world",
            },
            {
                "name": "ReportEnv",
                "module": "agentsociety2.contrib.env.llm_world.report_env",
                "description": "用于生成世界仿真报告的只读工具。",
                "kind": "llm_world",
            },
        ]

    def list_agent_types(self) -> List[Dict[str, Any]]:
        """列出可用的智能体类型。"""
        return [
            {
                "name": "WorldSimAgent",
                "module": "agentsociety2.agent.world_sim_agent",
                "description": "虚拟世界仿真的默认智能体，支持任意实体类型。",
                "is_default": True,
            },
            {
                "name": "PersonAgent",
                "module": "agentsociety2.agent.person",
                "description": "旧版以人为中心的智能体，带有心理需求模型。",
                "is_default": False,
                "note": "旧版类型；新的仿真请优先使用 WorldSimAgent。",
            },
        ]

    def list_routers(self) -> List[Dict[str, Any]]:
        """列出可用的路由器类型。"""
        return [
            {
                "name": "WorldRouter",
                "module": "agentsociety2.env.router_world",
                "description": "默认路由器，使用结构化 JSON 工具调用，不生成代码。",
                "is_default": True,
            },
            {
                "name": "ReActRouter",
                "module": "agentsociety2.env.router_react",
                "description": "采用 ReAct 推理加行动循环，并结合函数调用。",
                "is_default": False,
            },
            {
                "name": "PlanExecuteRouter",
                "module": "agentsociety2.env.router_plan_execute",
                "description": "先规划、后执行的路由策略。",
                "is_default": False,
            },
        ]
