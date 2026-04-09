"""
Agent生成模块 - 使用LLM生成代码来生成新Agent
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_project_root = Path(__file__).resolve().parents[3]

from agentsociety2.code_executor import (
    CodeExecutorAPI,
    CodeGenerationRequest,
    PathConfig,
)
from agentsociety2.logger import get_logger
from .utils import validate_agent_args

logger = get_logger()

DEFAULT_MODEL_NAME = "qwen3-next-80b-a3b-instruct"


PROMPT_GENERATE_AGENTS = """
You are an expert Python programmer. Your task is to write a Python script (main.py) that generates exactly {count} new Agent configurations based on reference agents and requirements.

Input files (in current directory):
- base_agents.json: Contains {base_count} reference agents that already meet the requirements
- requirements.txt: Contains the selection requirements and group requirements
{metadata_file_info}

Output:
- Save the generated agents as a JSON list to: {output_filename}
- The output MUST be a JSON array with EXACTLY {count} agents (no more, no less)
- Each agent must follow the exact structure: {{"profile": {{"custom_fields": {{...}}}}}}
- This format is compatible with agent_args used in experiment design

Requirements:
{selection_requirements}

{group_requirements_text}

{metadata_info}

Implementation instructions:
1. Read base_agents.json using json.load() to understand the structure and field types
2. Read requirements.txt to understand what is needed
{metadata_read_instructions}
3. Generate exactly {count} new agents that:
   - Follow the same structure as base agents (same field names and types)
   - Meet all selection requirements
   - Satisfy group requirements (if specified) - ensure the ENTIRE group of {count} agents together satisfies these
   - Have unique agent_id starting with "generated_" (e.g., "generated_001", "generated_002", ..., "generated_{count:03d}")
   - All fields in custom_fields MUST have non-null, non-empty values
4. For group requirements:
   - If target_mean is specified, calculate the mean of the field across all {count} agents and adjust to match
   - If target_std is specified, calculate the standard deviation and adjust to match
   - If target_distribution is specified, generate values following that distribution
5. Ensure the generated agents are varied but plausible
6. Use the same field names and types as in base agents - do not invent new fields
7. When generating values, use value_mappings to ensure values are valid (if metadata is provided)
8. Save the result to {output_filename} as UTF-8 JSON

CRITICAL REQUIREMENTS:
- The output JSON array MUST contain EXACTLY {count} agents
- Count the agents before saving: len(agent_list) == {count}
- Use a loop or list comprehension to ensure exact count
- If generating in batches, ensure the total is exactly {count}
- Output format must be compatible with agent_args: [{{"profile": {{"custom_fields": {{...}}}}}}, ...]

Example code structure:
```python
import json

# Read base agents
with open('base_agents.json', 'r', encoding='utf-8') as f:
    base_agents = json.load(f)

# Read requirements
with open('requirements.txt', 'r', encoding='utf-8') as f:
    requirements = f.read()

# Generate exactly {count} agents
generated_agents = []
for i in range({count}):
    agent = {{...}}
    generated_agents.append(agent)

# Verify count
assert len(generated_agents) == {count}, f"Expected {count} agents, got {{len(generated_agents)}}"

# Save to output file
with open('{output_filename}', 'w', encoding='utf-8') as f:
    json.dump(generated_agents, f, ensure_ascii=False, indent=2)
```

Command-line interface:
- The script will be executed as: python main.py
- Read base_agents.json and requirements.txt from the current directory
- Save output to {output_filename}
"""


class AgentGenerator:
    """Agent生成器 - 使用LLM生成代码来生成新Agent"""

    def __init__(self) -> None:
        self._code_executor = CodeExecutorAPI(
            path_config=PathConfig.default(),
        )
        logger.info("AgentGenerator initialized (code-based generation)")

    async def generate(
        self,
        *,
        count: int,
        base_agents: List[Dict[str, Any]],
        selection_requirements: str,
        group_requirements: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        model_name: str = DEFAULT_MODEL_NAME,
    ) -> List[Dict[str, Any]]:
        """
        使用LLM生成代码来生成新Agent

        Args:
            count: 需要生成的数量（必须精确）
            base_agents: 基础Agent列表（筛选出来的合格Agent）
            selection_requirements: 筛选需求（用于指导调整）
            group_requirements: 群体要求列表，格式为 [{"field_name": "Q5", "target_mean": 3.5}, ...]
            metadata: 元数据，包含字段名映射和值映射
            model_name: LLM模型名称

        Returns:
            生成的Agent列表（精确count个）
        """
        if not base_agents:
            raise ValueError("base_agents cannot be empty, need at least one agent to base on")

        if count <= 0:
            raise ValueError("count must be > 0")

        logger.info(
            f"Generating {count} agents using code generation (based on {len(base_agents)} base agents), model={model_name}"
        )
        if group_requirements:
            logger.info(f"With group requirements: {group_requirements}")

        group_req_text = ""
        if group_requirements:
            group_req_text = "\n\nGROUP REQUIREMENTS (the ENTIRE group of agents should satisfy these):\n"
            for req in group_requirements:
                field_name = req.get("field_name", "")
                if "target_mean" in req:
                    group_req_text += f"- Group average {field_name} should be approximately {req['target_mean']}\n"
                if "target_std" in req:
                    group_req_text += f"- Group standard deviation of {field_name} should be approximately {req['target_std']}\n"
                if "target_distribution" in req:
                    group_req_text += f"- Group {field_name} should follow {req['target_distribution']} distribution\n"
            group_req_text += "\nWhen generating agents, ensure the values of these fields across ALL generated agents satisfy the group requirements.\n"

        import tempfile
        temp_dir = Path(tempfile.mkdtemp())
        base_agents_file = temp_dir / "base_agents.json"
        with open(base_agents_file, "w", encoding="utf-8") as f:
            json.dump(base_agents, f, ensure_ascii=False, indent=2)

        requirements_file = temp_dir / "requirements.txt"
        with open(requirements_file, "w", encoding="utf-8") as f:
            f.write(selection_requirements)
            if group_requirements:
                f.write("\n\n" + group_req_text)

        metadata_file = None
        metadata_file_info = ""
        metadata_info = ""
        metadata_read_instructions = ""
        if metadata:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
                metadata_file = Path(f.name)
            metadata_file_info = f"- metadata.json: Contains field name mappings and value mappings for understanding field structure"
            metadata_info = self._format_metadata_info(metadata)
            metadata_read_instructions = "2.5. If metadata.json exists, read it to understand field_name_mapping and value_mappings"

        output_filename = "generated_agents.json"

        try:
            prompt = PROMPT_GENERATE_AGENTS.format(
                count=count,
                base_count=len(base_agents),
                selection_requirements=selection_requirements,
                group_requirements_text=group_req_text,
                metadata_file_info=metadata_file_info,
                metadata_info=metadata_info,
                metadata_read_instructions=metadata_read_instructions,
                output_filename=output_filename,
            )

            request = CodeGenerationRequest(description=prompt, model=model_name)

            logger.info(f"Generating code to create {count} agents with model {model_name}...")
            extra_files = [str(base_agents_file), str(requirements_file)]
            if metadata_file:
                metadata_file_in_dir = temp_dir / "metadata.json"
                import shutil
                shutil.copy(metadata_file, metadata_file_in_dir)
                extra_files.append(str(metadata_file_in_dir))

            response = await self._code_executor.generate_and_execute(
                request,
                extra_files=extra_files,
                program_args=[],
            )

            if not response.execution_result or not response.execution_result.success:
                error_msg = (
                    response.execution_result.stderr
                    if response.execution_result
                    else "Code execution failed"
                )
                logger.error(f"Agent generation code execution failed: {error_msg}")
                raise RuntimeError(f"Failed to generate agents: {error_msg}")

            # 读取生成的Agent
            artifacts = Path(response.execution_result.artifacts_path)
            output_file = artifacts / output_filename
            if not output_file.exists():
                raise FileNotFoundError(f"Generated agents file not found: {output_file}")

            with open(output_file, "r", encoding="utf-8") as f:
                generated_agents = json.load(f)

            if not isinstance(generated_agents, list):
                raise ValueError(f"Generated agents must be a list, got {type(generated_agents)}")

            # 验证数量
            if len(generated_agents) != count:
                logger.warning(
                    f"Generated {len(generated_agents)} agents, but requested {count}. "
                    f"Truncating or padding as needed."
                )
                if len(generated_agents) > count:
                    generated_agents = generated_agents[:count]
                elif len(generated_agents) < count:
                    # 如果不够，复制最后一个Agent
                    while len(generated_agents) < count:
                        last_agent = generated_agents[-1].copy()
                        custom_fields = last_agent["profile"]["custom_fields"].copy()
                        custom_fields["agent_id"] = f"generated_{len(generated_agents)+1:03d}"
                        last_agent["profile"]["custom_fields"] = custom_fields
                        generated_agents.append(last_agent)

            validate_agent_args(generated_agents)
            logger.info(f"Successfully generated {len(generated_agents)} agents")

            return generated_agents

        finally:
            # 清理临时文件和目录
            import shutil
            if 'temp_dir' in locals() and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            if metadata_file and metadata_file.exists():
                metadata_file.unlink()

    def _format_metadata_info(self, metadata: Dict[str, Any]) -> str:
        """
        格式化metadata信息为字符串，供LLM使用

        Args:
            metadata: metadata字典

        Returns:
            格式化的metadata信息字符串
        """
        if not metadata:
            return ""

        info_parts = []
        info_parts.append("Metadata information (if metadata.json is provided):")
        info_parts.append("")

        # 字段名映射
        field_name_mapping = metadata.get("field_name_mapping", {})
        if field_name_mapping:
            info_parts.append("Field name mapping (original -> meaningful):")
            for original, meaningful in list(field_name_mapping.items())[:20]:
                info_parts.append(f"  {original} -> {meaningful}")
            if len(field_name_mapping) > 20:
                info_parts.append(f"  ... ({len(field_name_mapping)} total)")
            info_parts.append("")

        # 字段信息和值映射
        fields = metadata.get("fields", [])
        if fields:
            info_parts.append("Fields and value mappings:")
            for field in fields[:10]:  # 只显示前10个字段
                name = field.get("name", "")
                meaningful = field_name_mapping.get(name, name)
                value_mappings = field.get("value_mappings", {})

                field_info = f"  {name}"
                if meaningful != name:
                    field_info += f" (meaningful: {meaningful})"
                info_parts.append(field_info)

                if value_mappings:
                    info_parts.append(f"    Value mappings:")
                    for value, meaning in list(value_mappings.items())[:5]:
                        info_parts.append(f"      {value} -> {meaning}")
                    if len(value_mappings) > 5:
                        info_parts.append(f"      ... ({len(value_mappings)} total)")
            if len(fields) > 10:
                info_parts.append(f"  ... ({len(fields)} total fields)")

        return "\n".join(info_parts)

    def _adjust_for_group_requirements(
        self,
        agents: List[Dict[str, Any]],
        group_requirements: List[Dict[str, Any]],
        base_agents: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        调整生成的Agent以满足群体要求

        Args:
            agents: 生成的Agent列表
            group_requirements: 群体要求列表
            base_agents: 基础Agent列表（用于参考值范围）

        Returns:
            调整后的Agent列表
        """
        if not group_requirements or not agents:
            return agents

        import statistics

        adjusted_agents = [agent.copy() for agent in agents]

        for req in group_requirements:
            field_name = req.get("field_name")
            if not field_name:
                continue

            # 获取当前群体的值
            def _get_numeric_value(agent: Dict[str, Any], field: str) -> float | None:
                """安全获取数值字段"""
                custom_fields = agent.get("profile", {}).get("custom_fields", {})
                if field not in custom_fields:
                    return None
                val = custom_fields[field]
                if isinstance(val, (int, float)):
                    return float(val)
                return None

            current_values = [v for v in (_get_numeric_value(a, field_name) for a in adjusted_agents) if v is not None]

            if not current_values:
                # 如果没有值，从base_agents中获取参考范围
                base_values = [v for v in (_get_numeric_value(a, field_name) for a in base_agents) if v is not None]

                if base_values:
                    # 使用base_agents的值范围
                    min_val = min(base_values)
                    max_val = max(base_values)
                else:
                    continue
            else:
                min_val = min(current_values)
                max_val = max(current_values)

            # 调整以满足群体要求
            if "target_mean" in req:
                target_mean = req["target_mean"]
                current_mean = statistics.mean(current_values) if current_values else target_mean

                # 计算需要调整的差值
                diff = target_mean - current_mean

                # 调整每个Agent的值
                for agent in adjusted_agents:
                    current_val = _get_numeric_value(agent, field_name)
                    if current_val is not None:
                        custom_fields = agent.get("profile", {}).get("custom_fields", {})
                        new_val = current_val + diff * 0.5  # 部分调整，避免过度
                        new_val = max(min_val, min(max_val, new_val))
                        custom_fields[field_name] = new_val

            if "target_std" in req and len(current_values) > 1:
                target_std = req["target_std"]
                current_std = statistics.stdev(current_values)

                # 计算缩放因子
                if current_std > 0:
                    scale = target_std / current_std
                    current_mean = statistics.mean(current_values)

                    # 调整每个Agent的值
                    for agent in adjusted_agents:
                        current_val = _get_numeric_value(agent, field_name)
                        if current_val is not None:
                            custom_fields = agent.get("profile", {}).get("custom_fields", {})
                            new_val = current_mean + (current_val - current_mean) * scale
                            new_val = max(min_val, min(max_val, new_val))
                            custom_fields[field_name] = new_val

        return adjusted_agents


    async def close(self) -> None:
        """关闭生成器并清理资源"""
        await self._code_executor.close()
        logger.info("AgentGenerator closed")


__all__ = ["AgentGenerator"]
