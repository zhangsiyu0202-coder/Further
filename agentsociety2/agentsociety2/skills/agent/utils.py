"""
Agent处理工具函数
"""

from typing import Any, Dict, List


def validate_agent_args(agent_args: List[Dict[str, Any]]) -> None:
    """
    验证Agent参数格式（统一验证函数）

    Args:
        agent_args: Agent参数列表

    Raises:
        ValueError: 如果格式不正确
    """
    if not isinstance(agent_args, list):
        raise ValueError("agent_args must be a list")

    if len(agent_args) == 0:
        # Allow empty list - it's valid (e.g., when no agents match filter criteria)
        return

    for idx, agent in enumerate(agent_args):
        if not isinstance(agent, dict):
            raise ValueError(f"agent_args[{idx}] must be a dictionary")

        if "profile" not in agent:
            raise ValueError(f"agent_args[{idx}] missing 'profile' field")

        profile = agent["profile"]
        if not isinstance(profile, dict):
            raise ValueError(f"agent_args[{idx}].profile must be a dictionary")

        if "custom_fields" not in profile:
            raise ValueError(f"agent_args[{idx}].profile missing 'custom_fields' field")

        custom_fields = profile["custom_fields"]
        if not isinstance(custom_fields, dict):
            raise ValueError(f"agent_args[{idx}].profile.custom_fields must be a dictionary")
