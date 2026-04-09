from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .file_processor import AgentFileProcessor
from .filter import AgentFilter, parse_selection_requirements
from .supplement_checker import AgentSupplementChecker
from .generator import AgentGenerator
from agentsociety2.logger import get_logger

logger = get_logger()


class AgentSelector:
    """
    Agent选择器 - 模块化架构

    流程：
    1. 使用 AgentFilter 进行筛选
    2. 使用 AgentSupplementChecker 检测是否需要补充
    3. 如果需要补充：
       - 如果用户提供了补充数据，处理并加入池中，重新筛选
       - 如果需要LLM生成，使用 AgentGenerator 生成
    """

    def __init__(
        self,
        auto_llm_generate: bool = True,
    ) -> None:
        """
        初始化Agent选择器

        Args:
            auto_llm_generate: 如果为True，当数量不足时自动使用LLM生成，否则需要用户输入
        """
        self._file_processor = AgentFileProcessor()
        self._filter = AgentFilter()
        self._checker = AgentSupplementChecker(auto_llm_generate=auto_llm_generate)
        self._generator = AgentGenerator()

        logger.info(f"AgentSelector initialized, auto_llm_generate={auto_llm_generate}")

    async def select_for_group(
        self,
        *,
        pool_file: Path,
        group_name: str,
        target_num_agents: int,
        selection_requirements: str,
        additional_context: Optional[str] = None,
        user_supplement_data: Optional[List[Dict[str, Any]]] = None,
        user_supplement_file: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """
        为实验组选择Agent

        Args:
            pool_file: Agent池文件路径（标准格式JSON）
            group_name: 组名
            target_num_agents: 目标Agent数量
            selection_requirements: 筛选需求描述
            additional_context: 额外上下文
            user_supplement_data: 用户提供的补充数据（已处理的标准格式）
            user_supplement_file: 用户提供的补充文件（需要处理成标准格式）

        Returns:
            选中的Agent列表
        """
        pool_file = Path(pool_file)
        if not pool_file.exists():
            raise FileNotFoundError(pool_file)

        if target_num_agents <= 0:
            raise ValueError("target_num_agents must be >= 1")

        parts = [
            f"- Group name: {group_name}",
            f"- Target number of agents: {target_num_agents}",
        ]
        if additional_context:
            parts.append(f"- Additional context: {additional_context}")
        parts.append("- Detailed requirements:")
        parts.append(selection_requirements.strip())
        full_requirements = "\n".join(parts)

        # Step 1: 从池中筛选符合要求的Agent
        # 使用LLM生成筛选代码，支持语义理解（如"中国人"匹配"China"）
        logger.info(f"Step 1: Filtering agents from pool: {pool_file}")

        # 添加重试机制，避免因LLM生成的代码偶然错误导致筛选失败
        max_filter_retries = 3
        filtered_agents = []
        filter_error = None

        for filter_retry in range(1, max_filter_retries + 1):
            try:
                filtered_agents = await self._filter.filter(
                    pool_file=pool_file,
                    group_name=group_name,
                    target_num_agents=target_num_agents,
                    selection_requirements=selection_requirements,
                    additional_context=additional_context,
                )
                filter_error = None
                break
            except Exception as exc:
                filter_error = exc
                if filter_retry < max_filter_retries:
                    logger.warning(
                        f"筛选失败 (尝试 {filter_retry}/{max_filter_retries}): {exc}，正在重试..."
                    )
                else:
                    logger.warning(
                        f"筛选最终失败 (尝试 {filter_retry}/{max_filter_retries}): {exc}，将尝试生成Agent"
                    )

        # 如果筛选失败，记录错误但继续流程（后续会通过生成Agent来补足）
        if filter_error:
            logger.warning(f"筛选过程出现错误，将尝试生成Agent: {filter_error}")
            filtered_agents = []

        logger.info(f"Filtered {len(filtered_agents)} agents")

        logger.info("Step 2: Checking if supplement is needed")
        processed_supplement_data = user_supplement_data
        if user_supplement_file and not processed_supplement_data:
            logger.info(f"Processing user supplement file: {user_supplement_file}")
            processed_supplement_data = await self._file_processor.process_file(
                file_path=user_supplement_file,
            )

        check_result = self._checker.check(
            filtered_agents=filtered_agents,
            target_num_agents=target_num_agents,
            user_supplement_data=processed_supplement_data,
        )

        if check_result.is_sufficient:
            logger.info("Number is sufficient, returning filtered agents")
            result = self._apply_field_name_mapping_to_agents(
                check_result.filtered_agents,
                pool_file
            )
            return result

        if check_result.needs_user_input:
            if processed_supplement_data:
                logger.info(
                    f"User provided {len(processed_supplement_data)} supplement agents, "
                    f"merging with pool and re-filtering"
                )
                result = await self._merge_and_refilter(
                    original_pool_file=pool_file,
                    supplement_data=processed_supplement_data,
                    group_name=group_name,
                    target_num_agents=target_num_agents,
                    selection_requirements=selection_requirements,
                    additional_context=additional_context,
                )
                result = self._apply_field_name_mapping_to_agents(result, pool_file)
                return result
            else:
                raise ValueError(
                    f"Insufficient agents: filtered {len(filtered_agents)}, "
                    f"need {target_num_agents}. Please provide supplement data or file."
                )

        if check_result.needs_llm_generate:
            with open(pool_file, "r", encoding="utf-8") as f:
                pool_data = json.load(f)
            metadata = None
            if isinstance(pool_data, dict) and "metadata" in pool_data:
                metadata = pool_data["metadata"]

            filter_config = parse_selection_requirements(selection_requirements)
            group_requirements = []
            for group_req in filter_config.group_requirements:
                req_dict = {"field_name": group_req.field_name}
                if group_req.target_mean is not None:
                    req_dict["target_mean"] = group_req.target_mean
                if group_req.target_std is not None:
                    req_dict["target_std"] = group_req.target_std
                if group_req.target_distribution:
                    req_dict["target_distribution"] = group_req.target_distribution
                if req_dict:
                    group_requirements.append(req_dict)

            if len(filtered_agents) == 0:
                logger.info(
                    f"No agents matched the criteria. Generating all {target_num_agents} agents "
                    f"directly via LLM. Using metadata from pool file to understand field structure."
                )
                if metadata and "fields" in metadata:
                    template_agent = {"profile": {"custom_fields": {}}}
                    for field in metadata["fields"]:
                        field_name = field.get("name", "")
                        field_type = field.get("type", "string")
                        if field_type in ["int", "integer", "number"]:
                            template_agent["profile"]["custom_fields"][field_name] = 0
                        else:
                            template_agent["profile"]["custom_fields"][field_name] = ""
                    generated_agents = await self._generator.generate(
                        count=target_num_agents,
                        base_agents=[template_agent],
                        selection_requirements=full_requirements,
                        group_requirements=group_requirements if group_requirements else None,
                        metadata=metadata,
                    )
                else:
                    default_base_agent = {
                        "profile": {
                            "custom_fields": {
                                "agent_id": "template_001",
                            }
                        }
                    }
                    generated_agents = await self._generator.generate(
                        count=target_num_agents,
                        base_agents=[default_base_agent],
                        selection_requirements=full_requirements,
                        group_requirements=group_requirements if group_requirements else None,
                        metadata=metadata,
                    )
                logger.info(
                    f"Generated {len(generated_agents)} agents directly via LLM"
                )
                # 为生成的Agent添加唯一标识
                for i, agent in enumerate(generated_agents):
                    custom_fields = agent.get("profile", {}).get("custom_fields", {})
                    # 统一使用 generated_ 前缀标识生成的Agent
                    if "agent_id" not in custom_fields:
                        custom_fields["agent_id"] = f"generated_{i+1:03d}"
                    else:
                        agent_id = str(custom_fields["agent_id"])
                        if not agent_id.startswith("generated_"):
                            custom_fields["agent_id"] = f"generated_{agent_id}"

                result = self._apply_field_name_mapping_to_agents(generated_agents, pool_file)
                return result
            else:
                logger.info(
                    f"Generating {check_result.shortage} agents via LLM based on "
                    f"{len(filtered_agents)} filtered agents"
                )
                generated_agents = await self._generator.generate(
                    count=check_result.shortage,
                    base_agents=filtered_agents,
                    selection_requirements=full_requirements,
                    group_requirements=group_requirements if group_requirements else None,
                    metadata=metadata,
                )
                # 为生成的Agent添加唯一标识
                for i, agent in enumerate(generated_agents):
                    custom_fields = agent.get("profile", {}).get("custom_fields", {})
                    # 统一使用 generated_ 前缀标识生成的Agent
                    if "agent_id" not in custom_fields:
                        custom_fields["agent_id"] = f"generated_{i+1:03d}"
                    else:
                        agent_id = str(custom_fields["agent_id"])
                        if not agent_id.startswith("generated_"):
                            custom_fields["agent_id"] = f"generated_{agent_id}"

                result = filtered_agents + generated_agents
                logger.info(
                    f"Final result: {len(result)} agents ({len(filtered_agents)} filtered + {len(generated_agents)} generated)"
                )
                result = self._apply_field_name_mapping_to_agents(result, pool_file)
                return result

        raise RuntimeError("Unexpected supplement check result")

    async def _merge_and_refilter(
        self,
        *,
        original_pool_file: Path,
        supplement_data: List[Dict[str, Any]],
        group_name: str,
        target_num_agents: int,
        selection_requirements: str,
        additional_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        合并补充数据到池中并重新筛选

        Args:
            original_pool_file: 原始池文件
            supplement_data: 补充数据（标准格式）
            group_name: 组名
            target_num_agents: 目标数量
            selection_requirements: 筛选需求
            additional_context: 额外上下文

        Returns:
            重新筛选后的Agent列表
        """
        with open(original_pool_file, "r", encoding="utf-8") as f:
            pool_data = json.load(f)

        # 统一格式：提取agents列表
        if isinstance(pool_data, dict) and "agents" in pool_data:
            original_pool = pool_data["agents"]
            metadata = pool_data.get("metadata", {})
        elif isinstance(pool_data, list):
            original_pool = pool_data
            metadata = {}
        else:
            raise ValueError("Original pool must be a dict with 'agents' key or a list")

        merged_pool = original_pool + supplement_data

        # 更新metadata
        if metadata:
            metadata["total_agents"] = len(merged_pool)
        logger.info(
            f"Merged pool: {len(original_pool)} original + {len(supplement_data)} supplement = {len(merged_pool)} total"
        )

        merged_pool_data = {
            "metadata": metadata if metadata else {
                "total_agents": len(merged_pool),
                "fields": [],
                "created_at": None
            },
            "agents": merged_pool
        }

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as f:
            json.dump(merged_pool_data, f, ensure_ascii=False, indent=2)
            merged_pool_file = Path(f.name)

        try:
            return await self._filter.filter(
                pool_file=merged_pool_file,
                group_name=group_name,
                target_num_agents=target_num_agents,
                selection_requirements=selection_requirements,
                additional_context=additional_context,
            )
        finally:
            if merged_pool_file.exists():
                merged_pool_file.unlink()

    def _apply_field_name_mapping_to_agents(
        self,
        agents: List[Dict[str, Any]],
        pool_file: Path,
    ) -> List[Dict[str, Any]]:
        """
        将Agent数据中的原始字段名转换为有意义的字段名，并将值转换为有意义的字符串

        Args:
            agents: Agent列表
            pool_file: 池文件路径（用于读取metadata）

        Returns:
            转换后的Agent列表
        """
        with open(pool_file, "r", encoding="utf-8") as f:
            pool_data = json.load(f)

        metadata = None
        if isinstance(pool_data, dict) and "metadata" in pool_data:
            metadata = pool_data["metadata"]

        if not metadata:
            logger.warning("No metadata found, returning agents as-is")
            return agents

        # 从metadata中提取字段名映射和值映射
        field_name_mapping = metadata.get("field_name_mapping", {})
        fields = metadata.get("fields", [])

        # 构建字段值映射字典：{原始字段名: {值: 含义}}
        # 例如：{"VAR00002": {"3": "China", "4": "USA"}}
        field_value_mappings = {}
        for field in fields:
            original_name = field.get("name", "")
            value_mappings = field.get("value_mappings", {})
            if value_mappings:
                field_value_mappings[original_name] = value_mappings

        # 应用映射：将原始字段名转换为有意义的名称，将数值转换为有意义的字符串
        mapped_agents = []
        for agent in agents:
            custom_fields = agent.get("profile", {}).get("custom_fields", {})
            if not isinstance(custom_fields, dict):
                mapped_agents.append(agent)
                continue

            new_custom_fields = {}
            for original_name, value in custom_fields.items():
                # agent_id字段保持原样，不进行映射
                if original_name == "agent_id":
                    new_custom_fields[original_name] = value
                    continue

                # 1. 字段名映射：将原始名称（如"VAR00002"）转换为有意义的名称（如"Country"）
                meaningful_name = field_name_mapping.get(original_name, original_name)

                # 2. 值映射：将数值（如3）转换为有意义的字符串（如"China"）
                mapped_value = value
                if original_name in field_value_mappings and value is not None:
                    value_mappings = field_value_mappings[original_name]
                    value_str = str(value).strip()
                    if value_str and value_str in value_mappings:
                        mapped_value = value_mappings[value_str]
                    # 处理数值类型匹配（如int类型的3匹配字符串"3"）
                    elif isinstance(value, (int, float)) and str(int(value)) in value_mappings:
                        mapped_value = value_mappings[str(int(value))]

                new_custom_fields[meaningful_name] = mapped_value

            new_agent = {
                "profile": {
                    "custom_fields": new_custom_fields
                }
            }
            mapped_agents.append(new_agent)

        logger.info(f"Applied field name and value mapping to {len(mapped_agents)} agents")
        return mapped_agents

    async def close(self) -> None:
        """关闭选择器并清理资源"""
        await self._file_processor.close()
        await self._filter.close()
        await self._generator.close()
        logger.info("AgentSelector closed")


__all__ = ["AgentSelector"]
