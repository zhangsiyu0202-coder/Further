"""
Agent补充检测模块 - 检测筛选结果，决定是否需要补充
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from agentsociety2.logger import get_logger

logger = get_logger()


class SupplementDecision(Enum):
    """补充决策"""
    SUFFICIENT = "sufficient"  # 数量足够，无需补充
    NEED_USER_INPUT = "need_user_input"  # 需要用户提供补充信息
    NEED_LLM_GENERATE = "need_llm_generate"  # 需要LLM生成


class SupplementCheckResult:
    """补充检测结果"""

    def __init__(
        self,
        decision: SupplementDecision,
        filtered_agents: List[Dict[str, Any]],
        target_num: int,
        shortage: int = 0,
        user_supplement_data: Optional[List[Dict[str, Any]]] = None,
    ):
        self.decision = decision
        self.filtered_agents = filtered_agents
        self.target_num = target_num
        self.shortage = shortage  # 缺少的数量
        self.user_supplement_data = user_supplement_data  # 用户提供的补充数据

    @property
    def is_sufficient(self) -> bool:
        """是否数量足够"""
        return self.decision == SupplementDecision.SUFFICIENT

    @property
    def needs_user_input(self) -> bool:
        """是否需要用户输入"""
        return self.decision == SupplementDecision.NEED_USER_INPUT

    @property
    def needs_llm_generate(self) -> bool:
        """是否需要LLM生成"""
        return self.decision == SupplementDecision.NEED_LLM_GENERATE


class AgentSupplementChecker:
    """Agent补充检测器"""

    def __init__(
        self,
        auto_llm_generate: bool = False,
    ):
        """
        初始化补充检测器

        Args:
            auto_llm_generate: 如果为True，当数量不足时自动使用LLM生成，否则需要用户输入
        """
        self.auto_llm_generate = auto_llm_generate
        logger.info(f"AgentSupplementChecker initialized, auto_llm_generate={auto_llm_generate}")

    def check(
        self,
        *,
        filtered_agents: List[Dict[str, Any]],
        target_num_agents: int,
        user_supplement_data: Optional[List[Dict[str, Any]]] = None,
    ) -> SupplementCheckResult:
        """
        检测筛选结果，决定是否需要补充

        Args:
            filtered_agents: 筛选后的Agent列表
            target_num_agents: 目标Agent数量
            user_supplement_data: 用户提供的补充数据（如果用户已经提供了）

        Returns:
            补充检测结果
        """
        current_count = len(filtered_agents)
        shortage = max(0, target_num_agents - current_count)

        logger.info(
            f"Supplement check: filtered={current_count}, target={target_num_agents}, "
            f"shortage={shortage}"
        )

        if shortage == 0:
            if current_count > target_num_agents:
                logger.warning(
                    f"Filtered agents ({current_count}) exceed target ({target_num_agents}), "
                    f"truncating to target."
                )
                filtered_agents = filtered_agents[:target_num_agents]

            return SupplementCheckResult(
                decision=SupplementDecision.SUFFICIENT,
                filtered_agents=filtered_agents,
                target_num=target_num_agents,
                shortage=0,
            )

        if user_supplement_data:
            logger.info(f"User provided {len(user_supplement_data)} supplement agents")
            return SupplementCheckResult(
                decision=SupplementDecision.NEED_USER_INPUT,
                filtered_agents=filtered_agents,
                target_num=target_num_agents,
                shortage=shortage,
                user_supplement_data=user_supplement_data,
            )

        if self.auto_llm_generate:
            logger.info("Auto-generating agents via LLM")
            return SupplementCheckResult(
                decision=SupplementDecision.NEED_LLM_GENERATE,
                filtered_agents=filtered_agents,
                target_num=target_num_agents,
                shortage=shortage,
            )

        logger.info("Need user input for supplement")
        return SupplementCheckResult(
            decision=SupplementDecision.NEED_USER_INPUT,
            filtered_agents=filtered_agents,
            target_num=target_num_agents,
            shortage=shortage,
        )


__all__ = ["AgentSupplementChecker", "SupplementCheckResult", "SupplementDecision"]
