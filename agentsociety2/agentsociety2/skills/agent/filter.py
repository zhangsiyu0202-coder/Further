"""
Agent过滤器

从信息池中筛选符合条件的Agent
支持：
1. 直接字段匹配（基于字段值）
2. LLM辅助筛选（语义理解）
3. 分布匹配（如正态分布）
4. 群体要求（如平均值、分布等）
"""

from __future__ import annotations

import json
import re
import random
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

from agentsociety2.code_executor.api import CodeExecutorAPI
from agentsociety2.code_executor.models import CodeGenerationRequest
from agentsociety2.logger import get_logger
from .utils import validate_agent_args

logger = get_logger()

DEFAULT_MODEL_NAME = "qwen3-next-80b-a3b-instruct"

PROMPT_FILTER_AGENTS = """
You are an agent filtering expert. Filter agents from a standardized agent pool based on requirements.

Agent pool file: {pool_file}
Selection requirements: {selection_requirements}
Target number of agents: {target_num_agents}
Group name: {group_name}

Metadata information:
{metadata_info}

INPUT FORMAT:
The input JSON file has structure: {{"metadata": {{...}}, "agents": [...]}}
- Extract agents from data["agents"]
- Each agent has structure: {{"profile": {{"custom_fields": {{field_name: value, ...}}}}}}
- Access field values via: agent["profile"]["custom_fields"][field_name]
- Use metadata to understand field names and value mappings

TASK:
1. Load the input JSON file and extract agents from data["agents"]
2. Load metadata from data["metadata"] to get field_name_mapping and value_mappings
3. Understand the selection requirements semantically - map natural language to field names and values
4. For each requirement:
   - Find the relevant field by searching field_name_mapping
   - Find the relevant value by searching all value_mappings for semantically matching meanings
5. Filter agents that match the requirements
6. Return exactly {target_num_agents} agents (or fewer if insufficient)

IMPORTANT:
- Read all mappings from metadata in the input file, do NOT hardcode
- Search value_mappings across all fields to find matching meanings
- Handle type conversion when comparing values

OUTPUT:
- Save filtered agents as a JSON list to {output_file}
- Each agent object should preserve the original structure from the input file
- Output format: [{{"profile": {{"custom_fields": {{...}}}}}}, ...]

Command-line: python main.py --input "{pool_file}" --output "{output_file}"
Use argparse with --input and --output arguments.
"""


@dataclass
class DistributionRequirement:
    """分布要求"""
    field_name: str
    distribution_type: str  # "normal", "uniform", "custom"
    mean: Optional[float] = None
    std: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None


@dataclass
class GroupRequirement:
    """群体要求"""
    field_name: str
    target_mean: Optional[float] = None
    target_std: Optional[float] = None
    target_min: Optional[float] = None
    target_max: Optional[float] = None
    target_distribution: Optional[str] = None  # "normal", "uniform", etc.


@dataclass
class FilterConfig:
    """筛选配置"""
    field_filters: Dict[str, Union[str, List[str], tuple]] = None
    distribution_requirements: List[DistributionRequirement] = None
    group_requirements: List[GroupRequirement] = None

    def __post_init__(self):
        if self.field_filters is None:
            self.field_filters = {}
        if self.distribution_requirements is None:
            self.distribution_requirements = []
        if self.group_requirements is None:
            self.group_requirements = []


def parse_field_filters(selection_requirements: str) -> Dict[str, Union[str, List[str], tuple]]:
    """
    解析字段匹配条件

    特殊值:
    - "*" 或 "all" 表示匹配所有（返回空字典，表示不过滤）
    """
    """
    从selection_requirements中解析字段匹配条件

    支持的格式：
    - field_name: value
    - field_name=value
    - field_name: value1,value2,value3 (多个值，任一匹配即可)
    - field_name >= value (数值比较)
    - field_name <= value (数值比较)
    - field_name > value (数值比较)
    - field_name < value (数值比较)

    也会尝试从自然语言描述中提取字段匹配条件，例如：
    - "personality is cooperative" -> personality: cooperative
    - "reputation high" -> reputation: high
    - "risk_tolerance >= 0.5" -> risk_tolerance >= 0.5

    Returns:
        字段匹配条件字典，格式为 {field_name: value} 或 {field_name: (operator, value)}
        对于多值匹配，value为列表
        对于数值比较，value为元组 (operator, numeric_value)
    """
    filters: Dict[str, Union[str, List[str], tuple]] = {}

    # 检查是否是匹配所有的特殊标记
    req_lower = selection_requirements.strip().lower()
    if req_lower in ['*', 'all', 'match all', 'all agents']:
        return {}  # 返回空字典表示不过滤

    # 移除上下文信息（组名、话题等），只保留字段匹配条件
    lines = selection_requirements.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 跳过明显的上下文信息行
        if line.startswith('-') and any(keyword in line.lower() for keyword in ['group name', 'target number', 'topic', 'hypothesis', 'env modules', 'agent types']):
            continue
        if line.startswith('#'):
            continue

        # 优先匹配明确的字段匹配格式: field_name: value 或 field_name=value
        match = re.match(r'(\w+)\s*[:=]\s*(.+)', line)
        if match:
            field_name = match.group(1).strip()
            value_str = match.group(2).strip()

            # 检查是否是通配符（匹配所有）
            if value_str.strip() in ['*', 'all', 'any']:
                # 对于通配符，不添加该字段的过滤条件（表示该字段不过滤）
                continue

            # 检查是否是数值比较
            num_match = re.match(r'([><]=?)\s*([\d.]+)', value_str)
            if num_match:
                operator = num_match.group(1)
                num_value = float(num_match.group(2))
                filters[field_name] = (operator, num_value)
            else:
                # 检查是否是多值（逗号分隔）
                if ',' in value_str:
                    values = [v.strip() for v in value_str.split(',')]
                    # 过滤掉通配符
                    values = [v for v in values if v not in ['*', 'all', 'any']]
                    if values:  # 只有当还有有效值时才添加
                        filters[field_name] = values
                else:
                    filters[field_name] = value_str
            continue

        # 尝试匹配数值比较格式: field_name >= value
        num_comp_match = re.search(r'(\w+)\s*([><]=?)\s*([\d.]+)', line)
        if num_comp_match:
            field_name = num_comp_match.group(1).strip()
            operator = num_comp_match.group(2).strip()
            num_value = float(num_comp_match.group(3).strip())
            filters[field_name] = (operator, num_value)
            continue

        # 尝试从自然语言中提取字段匹配: "field_name is value" 或 "field_name value"
        # 匹配常见的字段名（下划线或驼峰命名）
        field_pattern = r'\b([a-z_][a-z0-9_]*)\s+(?:is|are|=\s*|=|:)\s*([^\s,]+)'
        lang_match = re.search(field_pattern, line, re.IGNORECASE)
        if lang_match:
            field_name = lang_match.group(1).strip()
            value_str = lang_match.group(2).strip().rstrip('.,;!?')

            # 检查是否是多值
            if ',' in value_str:
                values = [v.strip() for v in value_str.split(',')]
                filters[field_name] = values
            else:
                filters[field_name] = value_str

    return filters


def match_agent_field(
    agent_value: Any,
    filter_value: Union[str, List[str], tuple],
    value_mappings: Optional[Dict[str, str]] = None
) -> bool:
    """
    检查Agent字段值是否匹配筛选条件

    Args:
        agent_value: Agent字段的实际值
        filter_value: 筛选条件值（可能是字符串、列表或元组）
        value_mappings: 值映射字典，用于将含义转换为实际值（如{"得分7": "7"}）

    Returns:
        是否匹配
    """
    # 处理通配符（匹配所有）
    if isinstance(filter_value, str) and filter_value.strip() in ['*', 'all', 'any']:
        return True

    # 如果提供了值映射，先尝试将筛选条件转换为实际值
    if value_mappings:
        if isinstance(filter_value, str):
            # 如果筛选条件是含义（如"得分7"），转换为实际值（"7"）
            # value_mappings是反向映射：{"得分7": "7"}
            original_filter = filter_value
            if filter_value in value_mappings:
                filter_value = value_mappings[filter_value]
                logger.debug(
                    f"Value mapping applied: '{original_filter}' -> '{filter_value}'"
                )
            elif isinstance(filter_value, list):
                # 对于列表，转换所有可能的含义
                mapped_values = []
                for v in filter_value:
                    if v in value_mappings:
                        mapped_values.append(value_mappings[v])
                    else:
                        mapped_values.append(v)
                filter_value = mapped_values

    if isinstance(filter_value, tuple):
        # 数值比较 (operator, value)
        operator, target_value = filter_value
        try:
            agent_num = float(agent_value)
            if operator == '>=':
                return agent_num >= target_value
            elif operator == '<=':
                return agent_num <= target_value
            elif operator == '>':
                return agent_num > target_value
            elif operator == '<':
                return agent_num < target_value
            else:
                return False
        except (ValueError, TypeError):
            return False
    elif isinstance(filter_value, list):
        # 多值匹配（任一匹配即可）
        # 如果列表中包含通配符，则匹配所有
        if any(str(v).strip() in ['*', 'all', 'any'] for v in filter_value):
            return True
        agent_str = str(agent_value).strip()
        return any(str(v).strip() == agent_str for v in filter_value)
    else:
        # 精确匹配
        # 尝试数值比较（如果都是数字）
        try:
            agent_num = float(agent_value)
            filter_num = float(filter_value)
            return agent_num == filter_num
        except (ValueError, TypeError):
            # 如果无法转换为数字，使用字符串比较
            agent_str = str(agent_value).strip()
            filter_str = str(filter_value).strip()
            return agent_str == filter_str


def match_agent(
    agent: Dict[str, Any],
    filters: Dict[str, Union[str, List[str], tuple]],
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    检查Agent是否匹配所有筛选条件

    Args:
        agent: Agent对象
        filters: 字段筛选条件字典（可以使用有意义的字段名或原始字段名）
        metadata: 元数据，包含字段信息和值映射

    Returns:
        是否匹配所有条件
    """
    if not filters:
        # 如果没有筛选条件，返回True（包含所有Agent）
            return True

    custom_fields = agent.get("profile", {}).get("custom_fields", {})
    if not isinstance(custom_fields, dict):
        return False

    # 构建字段名映射（有意义名称 -> 原始名称）
    field_name_mapping_reverse = {}
    if metadata and "field_name_mapping" in metadata:
        # field_name_mapping格式：原始名称 -> 有意义名称
        # 构建反向映射：有意义名称 -> 原始名称
        for original, meaningful in metadata["field_name_mapping"].items():
            field_name_mapping_reverse[meaningful] = original

    # 构建字段名到值映射的字典（用于快速查找）
    field_value_mappings = {}
    if metadata and "fields" in metadata:
        for field_info in metadata["fields"]:
            field_name = field_info.get("name", "")  # 原始字段名（VAR00004, Q5等）
            value_mappings = field_info.get("value_mappings", {})
            if value_mappings:
                # 创建反向映射：含义 -> 值（如{"得分7": "7"}）
                reverse_mapping = {v: k for k, v in value_mappings.items()}
                field_value_mappings[field_name] = reverse_mapping

    # 检查所有筛选条件
    for field_name, filter_value in filters.items():
        # 如果使用的是有意义的字段名，转换为原始字段名
        original_field_name = field_name_mapping_reverse.get(field_name, field_name)

        if original_field_name not in custom_fields:
            # 如果字段不存在，不匹配
            return False

        agent_value = custom_fields[original_field_name]
        # 获取该字段的值映射（如果有）
        value_mappings = field_value_mappings.get(original_field_name)
        if not match_agent_field(agent_value, filter_value, value_mappings):
            return False

    return True


def parse_selection_requirements(selection_requirements: str) -> FilterConfig:
    """
    解析筛选需求，提取字段匹配、分布要求、群体要求等

    Returns:
        FilterConfig对象
    """
    config = FilterConfig()

    # 解析字段匹配条件
    config.field_filters = parse_field_filters(selection_requirements)

    # 解析分布要求（如 "risk_tolerance with normal distribution, mean=0.6, std=0.1"）
    dist_pattern = r'(\w+)\s+with\s+(\w+)\s+distribution(?:\s*,\s*mean\s*=\s*([\d.]+))?(?:\s*,\s*std\s*=\s*([\d.]+))?'
    for match in re.finditer(dist_pattern, selection_requirements, re.IGNORECASE):
        field_name = match.group(1)
        dist_type = match.group(2).lower()
        mean = float(match.group(3)) if match.group(3) else None
        std = float(match.group(4)) if match.group(4) else None
        config.distribution_requirements.append(
            DistributionRequirement(
                field_name=field_name,
                distribution_type=dist_type,
                mean=mean,
                std=std,
            )
        )

    # 解析群体要求（如 "group average risk_tolerance = 0.6" 或 "group mean Q5 = 3.5"）
    group_patterns = [
        (r'group\s+(?:average|mean)\s+(\w+)\s*=\s*([\d.]+)', 'mean'),
        (r'group\s+std\s+(\w+)\s*=\s*([\d.]+)', 'std'),
        (r'group\s+(\w+)\s+should\s+have\s+(\w+)\s+distribution', 'distribution'),
    ]
    for pattern, req_type in group_patterns:
        for match in re.finditer(pattern, selection_requirements, re.IGNORECASE):
            field_name = match.group(1)
            if req_type == 'mean':
                target_value = float(match.group(2))
                config.group_requirements.append(
                    GroupRequirement(field_name=field_name, target_mean=target_value)
                )
            elif req_type == 'std':
                target_value = float(match.group(2))
                config.group_requirements.append(
                    GroupRequirement(field_name=field_name, target_std=target_value)
                )
            elif req_type == 'distribution':
                dist_type = match.group(2).lower()
                config.group_requirements.append(
                    GroupRequirement(field_name=field_name, target_distribution=dist_type)
                )

    return config


def select_with_distribution(
    agents: List[Dict[str, Any]],
    requirement: DistributionRequirement,
    target_count: int,
) -> List[Dict[str, Any]]:
    """
    根据分布要求选择Agent

    Args:
        agents: 候选Agent列表
        requirement: 分布要求
        target_count: 目标数量

    Returns:
        选中的Agent列表
    """
    field_name = requirement.field_name

    # 提取字段值
    agent_values = []
    for agent in agents:
        custom_fields = agent.get("profile", {}).get("custom_fields", {})
        if field_name in custom_fields:
            try:
                value = float(custom_fields[field_name])
                agent_values.append((agent, value))
            except (ValueError, TypeError):
                continue

    if not agent_values:
        return []

    if requirement.distribution_type == "normal":
        # 正态分布选择
        if requirement.mean is not None and requirement.std is not None:
            # 计算每个Agent的权重（基于正态分布概率密度）
            weights = []
            for agent, value in agent_values:
                # 简化的权重计算：距离均值越近，权重越大
                distance = abs(value - requirement.mean)
                weight = 1.0 / (1.0 + distance / requirement.std)
                weights.append(weight)

            # 根据权重选择
            if len(agent_values) <= target_count:
                return [agent for agent, _ in agent_values]

            # 加权随机选择
            selected = random.choices(
                agent_values,
                weights=weights,
                k=min(target_count, len(agent_values))
            )
            return [agent for agent, _ in selected]

    elif requirement.distribution_type == "uniform":
        # 均匀分布：随机选择
        if len(agent_values) <= target_count:
            return [agent for agent, _ in agent_values]
        return [agent for agent, _ in random.sample(agent_values, target_count)]

    # 默认：随机选择
    if len(agent_values) <= target_count:
        return [agent for agent, _ in agent_values]
    return [agent for agent, _ in random.sample(agent_values, target_count)]


def select_with_group_requirements(
    agents: List[Dict[str, Any]],
    requirements: List[GroupRequirement],
    target_count: int,
) -> List[Dict[str, Any]]:
    """
    根据群体要求选择Agent（使用贪心算法）

    Args:
        agents: 候选Agent列表
        requirements: 群体要求列表
        target_count: 目标数量

    Returns:
        选中的Agent列表
    """
    if not requirements or not agents:
        return agents[:target_count] if len(agents) >= target_count else agents

    selected = []
    remaining = agents.copy()

    # 贪心选择：每次选择一个Agent，使得当前群体的统计量最接近目标
    for _ in range(min(target_count, len(agents))):
        best_agent = None
        best_score = float('inf')

        for agent in remaining:
            # 尝试添加这个Agent
            test_selected = selected + [agent]

            # 计算当前群体的统计量
            score = 0.0
            for req in requirements:
                field_name = req.field_name
                values = []
                for a in test_selected:
                    custom_fields = a.get("profile", {}).get("custom_fields", {})
                    if field_name in custom_fields:
                        try:
                            values.append(float(custom_fields[field_name]))
                        except (ValueError, TypeError):
                            pass

                if not values:
                    score += 1000  # 惩罚：没有值
                    continue

                # 计算与目标的差距
                if req.target_mean is not None:
                    current_mean = statistics.mean(values)
                    score += abs(current_mean - req.target_mean) * len(test_selected)

                if req.target_std is not None and len(values) > 1:
                    current_std = statistics.stdev(values)
                    score += abs(current_std - req.target_std) * len(test_selected)

            if score < best_score:
                best_score = score
                best_agent = agent

        if best_agent:
            selected.append(best_agent)
            remaining.remove(best_agent)
        else:
            break

    return selected


class AgentFilter:
    """Agent筛选器 - 使用LLM理解筛选需求并生成筛选代码"""

    def __init__(self) -> None:
        """
        初始化Agent筛选器

        Args:
            model_name: LLM模型名称，默认使用DEFAULT_MODEL_NAME
        """

        # 初始化代码执行器
        self._code_executor = CodeExecutorAPI()

        logger.info("AgentFilter initialized")


    async def filter(
        self,
        *,
        pool_file: Path,
        group_name: str,
        target_num_agents: int,
        selection_requirements: str,
        additional_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        根据需求筛选Agent（使用LLM理解需求并生成筛选代码）

        Args:
            pool_file: Agent池文件路径
            group_name: 组名
            target_num_agents: 目标Agent数量
            selection_requirements: 筛选需求描述（自然语言或结构化格式）
            additional_context: 额外上下文

        Returns:
            筛选后的Agent列表（最多target_num_agents个）
        """
        pool_file = Path(pool_file)
        if not pool_file.exists():
            raise FileNotFoundError(f"Pool file not found: {pool_file}")

        if target_num_agents <= 0:
            raise ValueError("target_num_agents must be >= 1")

        logger.info(
            f"Filtering agents for group '{group_name}': "
            f"requirements='{selection_requirements[:100]}...', "
            f"target={target_num_agents}"
        )

        # 读取Agent池以获取metadata
        with open(pool_file, "r", encoding="utf-8") as f:
            pool_data = json.load(f)

        # 获取metadata
        metadata = None
        if isinstance(pool_data, dict) and "metadata" in pool_data:
            metadata = pool_data["metadata"]
            logger.info(
                f"Loaded metadata: {metadata.get('total_agents', 'unknown')} agents, "
                f"{len(metadata.get('fields', []))} fields"
            )
        else:
            logger.warning("No metadata found in pool file, LLM will work with limited context")

        # 构建metadata信息字符串
        metadata_info = self._format_metadata_info(metadata)

        # 构建输出文件名
        output_file = f"filtered_{group_name}_{target_num_agents}.json"

        # 构建prompt
        prompt = PROMPT_FILTER_AGENTS.format(
            pool_file=pool_file.name,
            selection_requirements=selection_requirements,
            target_num_agents=target_num_agents,
            group_name=group_name,
            metadata_info=metadata_info,
            output_file=output_file,
        )

        # 添加额外上下文
        additional_context_str = None
        if additional_context:
            additional_context_str = f"Additional context: {additional_context}"

        request = CodeGenerationRequest(
            description=prompt,
            input_files=None,
            additional_context=additional_context_str,
        )

        logger.info("Generating filtering code and executing in Docker...")
        response = await self._code_executor.generate_and_execute(
            request,
            extra_files=[str(pool_file)],
            program_args=[
                "--input",
                pool_file.name,
                "--output",
                output_file,
            ],
        )

        if not response.execution_result or not response.execution_result.success:
            error_msg = (
                response.execution_result.stderr
                if response.execution_result
                else "Execution failed"
            )
            logger.error(f"Filtering failed: {error_msg}")
            raise ValueError(f"Filtering failed: {error_msg}")

        # 读取筛选结果
        artifacts_path = (
            Path(response.execution_result.artifacts_path)
            if response.execution_result and response.execution_result.artifacts_path
            else None
        )

        if not artifacts_path or not artifacts_path.exists():
            raise FileNotFoundError(
                f"Output file not found: {output_file}. "
                f"Artifacts path: {artifacts_path}"
            )

        output_path = artifacts_path / output_file
        if not output_path.exists():
            # 尝试在artifact目录中查找
            artifact_files = list(artifacts_path.glob("*.json"))
            if artifact_files:
                output_path = artifact_files[0]
                logger.info(f"Found output file: {output_path}")
            else:
                raise FileNotFoundError(
                    f"Output file not found: {output_file}. "
                    f"Artifacts path: {artifacts_path}"
                )

        with open(output_path, "r", encoding="utf-8") as f:
            filtered_data = json.load(f)

        # 处理不同的输出格式
        if isinstance(filtered_data, list):
            filtered_agents = filtered_data
        elif isinstance(filtered_data, dict):
            # 如果返回的是dict，尝试提取agents列表
            if "agents" in filtered_data:
                filtered_agents = filtered_data["agents"]
            elif "results" in filtered_data:
                filtered_agents = filtered_data["results"]
            else:
                raise ValueError(
                    f"Filter output is a dict but doesn't contain 'agents' or 'results' key. "
                    f"Keys: {list(filtered_data.keys())}"
                )
        else:
            raise ValueError(
                f"Filter output must be a list or dict with 'agents' key, got {type(filtered_data)}"
            )

        validate_agent_args(filtered_agents)

        logger.info(
            f"Filter for group '{group_name}': found {len(filtered_agents)} matching agents "
            f"(target: {target_num_agents})"
        )

        # 限制数量
        if len(filtered_agents) > target_num_agents:
            logger.info(
                f"Filter returned {len(filtered_agents)} agents, but target is {target_num_agents}. "
                f"Truncating to {target_num_agents}."
            )
            filtered_agents = filtered_agents[:target_num_agents]

        # 应用字段名映射和值映射：将原始字段名转换为有意义的字段名，将值转换为有意义的字符串
        if metadata:
            filtered_agents = self._apply_field_and_value_mapping(filtered_agents, metadata)
            logger.info("Applied field name and value mapping to filtered agents")

        return filtered_agents

    def _apply_field_and_value_mapping(
        self,
        agents: List[Dict[str, Any]],
        metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        将Agent数据中的原始字段名转换为有意义的字段名，并将值转换为有意义的字符串

        Args:
            agents: Agent列表
            metadata: metadata字典，包含field_name_mapping和fields信息

        Returns:
            转换后的Agent列表
        """
        field_name_mapping = metadata.get("field_name_mapping", {})
        fields = metadata.get("fields", [])

        # 构建字段名到值映射的字典
        # 格式: {原始字段名: {值: 含义}}
        field_value_mappings = {}
        for field in fields:
            original_name = field.get("name", "")
            value_mappings = field.get("value_mappings", {})
            if value_mappings:
                field_value_mappings[original_name] = value_mappings

        mapped_agents = []
        for agent in agents:
            custom_fields = agent.get("profile", {}).get("custom_fields", {})
            if not isinstance(custom_fields, dict):
                mapped_agents.append(agent)
                continue

            # 创建新的custom_fields，使用有意义的字段名和值
            new_custom_fields = {}
            for original_name, value in custom_fields.items():
                # 1. 字段名映射：原始名称 -> 有意义的名称
                meaningful_name = field_name_mapping.get(original_name, original_name)

                # 2. 值映射：如果有值映射，将值转换为有意义的字符串
                mapped_value = value
                if original_name in field_value_mappings:
                    value_mappings = field_value_mappings[original_name]
                    # 将值转换为字符串进行查找
                    value_str = str(value)
                    if value_str in value_mappings:
                        mapped_value = value_mappings[value_str]
                    # 也尝试数值匹配（如果值是int但映射的key是str）
                    elif isinstance(value, (int, float)) and str(int(value)) in value_mappings:
                        mapped_value = value_mappings[str(int(value))]

                new_custom_fields[meaningful_name] = mapped_value

            # 创建新的agent对象
            new_agent = {
                "profile": {
                    "custom_fields": new_custom_fields
                }
            }
            mapped_agents.append(new_agent)

        return mapped_agents

    def _format_metadata_info(self, metadata: Optional[Dict[str, Any]]) -> str:
        """
        格式化metadata信息为字符串，供LLM使用

        Args:
            metadata: metadata字典

        Returns:
            格式化的metadata信息字符串
        """
        if not metadata:
            return "No metadata available."

        info_parts = []

        # 基本信息
        info_parts.append(f"Total agents: {metadata.get('total_agents', 'unknown')}")
        info_parts.append("")

        # 字段名映射 - 完整展示
        field_name_mapping = metadata.get("field_name_mapping", {})
        if field_name_mapping:
            info_parts.append("Field name mapping (original field name -> meaningful name):")
            for original, meaningful in field_name_mapping.items():
                info_parts.append(f"  {original} -> {meaningful}")
            info_parts.append("")

        # 字段信息 - 完整展示值映射，强调要从metadata中读取
        fields = metadata.get("fields", [])
        if fields:
            info_parts.append("Fields and their value mappings (READ FROM metadata in input file):")
            info_parts.append("")
            info_parts.append("To access value mappings in code:")
            info_parts.append("  data = json.load(open(input_file))")
            info_parts.append("  metadata = data['metadata']")
            info_parts.append("  field_name_mapping = metadata['field_name_mapping']")
            info_parts.append("  for field in metadata['fields']:")
            info_parts.append("    field_name = field['name']")
            info_parts.append("    value_mappings = field.get('value_mappings', {{}})")
            info_parts.append("")
            info_parts.append("Available fields with value mappings:")
            for field in fields:
                name = field.get("name", "")
                field_type = field.get("type", "unknown")
                description = field.get("description", "")
                value_mappings = field.get("value_mappings", {})

                # 使用有意义的字段名（如果有映射）
                meaningful_name = field_name_mapping.get(name, name)
                field_info = f"  Field: {name}"
                if meaningful_name != name:
                    field_info += f" (meaningful name: {meaningful})"
                field_info += f" (type: {field_type})"
                if description:
                    field_info += f" - {description}"
                info_parts.append(field_info)

                if value_mappings:
                    # 显示所有值映射，让LLM知道完整的映射关系
                    info_parts.append(f"    Value mappings (value -> meaning):")
                    for value, meaning in value_mappings.items():
                        info_parts.append(f"      {value} -> {meaning}")
                else:
                    info_parts.append(f"    (No value mappings - use direct value matching)")
                info_parts.append("")

        return "\n".join(info_parts)


    async def close(self) -> None:
        """关闭筛选器并清理资源"""
        if hasattr(self, "_code_executor"):
            await self._code_executor.close()
        logger.info("AgentFilter closed")


__all__ = ["AgentFilter", "parse_selection_requirements"]
