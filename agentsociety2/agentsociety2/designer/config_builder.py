"""实验配置构建器"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import json_repair
from agentsociety2.designer.exp_designer import (
    ExperimentDesign,
)
from agentsociety2.logger import get_logger
from agentsociety2.registry import (
    AgentInitConfig,
    CreateInstanceRequest,
    EnvModuleInitConfig,
    get_registered_agent_modules,
    get_registered_env_modules,
)
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field

logger = get_logger()

_project_root = Path(__file__).resolve().parents[2]


PROMPT_FIX_CONFIG = """You are a configuration repair assistant. Fix ONLY format/structure issues so the config validates.

STRICT RULES:
1) Repair format/type/enum/required-field/JSON-structure issues ONLY.
2) Do NOT change experiment intent: keep env_modules, agent_types, env_args, agent_args, and all values unchanged unless the error explicitly says they are invalid.
3) Address only the issues mentioned in the validation error; avoid extra changes.

Current config:
{config_json}

Validation error:
{error_msg}

Return the FULL config JSON only, no explanations.
"""


class ExperimentConfig(BaseModel):
    """单个实验的配置"""

    experiment_name: str = Field(..., description="实验名称")
    hypothesis_index: int = Field(..., description="假设索引")
    group_index: int = Field(..., description="实验组索引")
    experiment_index: int = Field(..., description="实验索引")
    instance_id: str = Field(..., description="实例ID")
    config: CreateInstanceRequest = Field(..., description="实例配置")
    workflow: Optional[str] = Field(None, description="工作流描述")
    num_steps: int = Field(..., description="实验运行的步数/轮数（从假设级别获取）")


class ConfigBuilder:
    """实验配置构建器"""

    def __init__(self, server_url: Optional[str] = None) -> None:
        """
        初始化配置构建器

        Args:
            server_url: MCP server 的 HTTP URL，默认使用 settings.mcp_server_url
        """
        self._server_url = server_url
        logger.info(f"配置构建器初始化，MCP server URL: {self._server_url}")

    def _build_env(
        self, env_types: List[str], env_args: Dict[str, Any]
    ) -> List[EnvModuleInitConfig]:
        """构建环境模块配置

        根据环境模块类型列表和参数字典，构建环境模块初始化配置。
        当只有一个环境模块时，直接使用env_args；多个模块时，从env_args中按模块类型提取参数。

        Args:
            env_types: 环境模块类型列表（如 ["reputation_game"]）
            env_args: 环境模块参数字典
                - 单个模块时：直接包含该模块的参数（如 {"config": {...}}）
                - 多个模块时：按模块类型组织（如 {"reputation_game": {...}, "social_space": {...}}）

        Returns:
            环境模块初始化配置列表

        Raises:
            ValueError: 当模块类型不在注册表中，或没有提供任何模块时
        """
        modules = []
        reg_types = [mt for mt, _ in get_registered_env_modules()]

        for mod_type in env_types:
            if mod_type not in reg_types:
                raise ValueError(
                    f"环境模块类型 '{mod_type}' 不在注册表中。" f"可用类型: {reg_types}"
                )

            # 单个模块时，env_args直接包含该模块的参数
            # 多个模块时，需要从env_args中按模块类型提取
            if len(env_types) == 1:
                mod_args = env_args
            else:
                mod_args = env_args.get(mod_type, {})

            modules.append(EnvModuleInitConfig(module_type=mod_type, args=mod_args))

        if not modules:
            raise ValueError("至少需要一个环境模块")

        return modules

    def _normalize_agent_args(self, agent_args: Dict[str, Any]) -> Dict[str, Any]:
        """将agent_args转换为标准格式（格式转换，不改变值）

        如果agent_args直接包含profile相关字段，包装到profile.custom_fields中

        Args:
            agent_args: Agent参数（可能包含直接字段或已包装的profile）

        Returns:
            标准化后的agent_args
        """
        import copy

        normalized = copy.deepcopy(agent_args)

        profile_fields = [
            "learning_frequency",
            "personality",
            "initial_mood",
            "risk_tolerance",
        ]
        has_direct_fields = any(field in normalized for field in profile_fields)

        if has_direct_fields:
            if "profile" not in normalized:
                normalized["profile"] = {}
            if not isinstance(normalized["profile"], dict):
                normalized["profile"] = {}
            if "custom_fields" not in normalized["profile"]:
                normalized["profile"]["custom_fields"] = {}

            for field in profile_fields:
                if field in normalized:
                    normalized["profile"]["custom_fields"][field] = normalized.pop(
                        field
                    )

        return normalized

    def _build_agents(
        self, agent_types: List[str], agent_args: List[Dict[str, Any]]
    ) -> List[AgentInitConfig]:
        """构建 Agent 配置（格式转换，不改变值）

        agent_args必须是列表，每个元素对应一个Agent的配置。
        每个Agent的配置值保持原样，只做格式转换（如将直接字段包装到profile.custom_fields中）。

        Args:
            agent_types: Agent 类型列表（应该只有一个）
            agent_args: Agent 参数列表，每个元素对应一个Agent的配置

        Returns:
            Agent配置列表
        """
        registered_types = [at for at, _ in get_registered_agent_modules()]

        if len(agent_types) != 1:
            raise ValueError(
                f"当前只支持单个agent_type，但提供了 {len(agent_types)} 个: {agent_types}"
            )

        agent_type = agent_types[0]
        if agent_type not in registered_types:
            raise ValueError(
                f"Agent 类型 '{agent_type}' 不在注册表中。"
                f"可用类型: {registered_types}"
            )

        if not isinstance(agent_args, list):
            raise ValueError(
                f"agent_args必须是列表格式，每个元素对应一个Agent的配置，但得到: {type(agent_args)}"
            )

        if len(agent_args) == 0:
            raise ValueError("agent_args列表不能为空")

        agents = []
        for i, agent_config in enumerate(agent_args):
            if not isinstance(agent_config, dict):
                raise ValueError(
                    f"agent_args列表中的元素必须是字典，但索引 {i} 是: {type(agent_config)}"
                )

            # 支持新格式（包含kwargs字段）和旧格式（扁平结构）
            if "kwargs" in agent_config:
                # 新格式：从kwargs中获取所有初始化参数
                normalized_config = self._normalize_agent_args(agent_config["kwargs"])
            else:
                # 旧格式：直接使用agent_config（排除agent_type和agent_id）
                normalized_config = self._normalize_agent_args(agent_config)
                # 排除顶层字段
                normalized_config.pop("agent_type", None)
                normalized_config.pop("agent_id", None)
            
            normalized_config.pop("id", None)

            agents.append(
                AgentInitConfig(
                    agent_type=agent_type, agent_id=i, args=normalized_config
                )
            )

        return agents

    def build_configs(self, design: ExperimentDesign) -> List[ExperimentConfig]:
        """
        从实验设计构建所有实验的配置

        遍历设计中的所有假设、组和实验，为每个实验构建完整的配置对象。
        包括环境模块、Agent配置、LLM配置等，并生成唯一的实例ID。

        Args:
            design: 实验设计对象，包含假设、组、实验的完整结构

        Returns:
            所有实验的配置列表，每个配置包含：
            - experiment_name: 实验名称
            - hypothesis_index: 假设索引
            - group_index: 组索引
            - experiment_index: 实验索引
            - instance_id: 唯一实例ID
            - config: CreateInstanceRequest对象（包含环境、Agent、LLM等配置）
            - workflow: 工作流描述
            - num_steps: 实验运行步数

        Raises:
            ValueError: 当实验组缺少num_agents字段，或agent_args数量与num_agents不匹配时
        """
        configs = []
        start_t = datetime.now(timezone.utc)

        # 遍历所有假设、组和实验，为每个实验构建配置
        for hypo_idx, hypothesis in enumerate(design.hypotheses):
            for group_idx, group in enumerate(hypothesis.groups):
                for exp_idx, experiment in enumerate(group.experiments):
                    # 构建环境模块配置
                    env_modules = self._build_env(
                        hypothesis.env_modules, experiment.env_args
                    )

                    # 验证实验组必须指定Agent数量
                    if group.num_agents is None:
                        raise ValueError(
                            f"实验组 '{group.name}' 缺少 num_agents 字段。"
                            f"请在工作流设计阶段为每个实验组指定 num_agents。"
                        )

                    # 验证agent_args数量必须与组级num_agents一致
                    actual_count = len(experiment.agent_args)
                    if actual_count != group.num_agents:
                        raise ValueError(
                            f"实验组 '{group.name}' 的实验 '{experiment.name}' 的 agent_args 数量 ({actual_count}) "
                            f"与组级 num_agents ({group.num_agents}) 不匹配。\n"
                            f"请确保该实验的 agent_args 列表包含 exactly {group.num_agents} 个元素，"
                            f"或者将组 '{group.name}' 的 num_agents 修改为 {actual_count}。"
                        )

                    agents = self._build_agents(
                        hypothesis.agent_types,
                        experiment.agent_args,
                    )

                    instance_id = f"{design.topic}_{hypo_idx}_{group_idx}_{exp_idx}_{uuid4().hex[:8]}"
                    instance_id = "".join(
                        c for c in instance_id if c.isalnum() or c in ("-", "_")
                    )

                    config = CreateInstanceRequest(
                        instance_id=instance_id,
                        env_modules=env_modules,
                        agents=agents,
                        start_t=start_t,
                        tick=600, # TODO
                    )

                    configs.append(
                        ExperimentConfig(
                            experiment_name=experiment.name,
                            hypothesis_index=hypo_idx,
                            group_index=group_idx,
                            experiment_index=exp_idx,
                            instance_id=instance_id,
                            config=config,
                            workflow=experiment.workflow,
                            num_steps=hypothesis.num_steps,
                        )
                    )

        logger.info(
            f"为 {len(design.hypotheses)} 个假设生成了 {len(configs)} 个实验配置"
        )
        return configs

    async def _call_mcp(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """通过 HTTP 调用 MCP 工具"""
        async with streamablehttp_client(self._server_url) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                if result.content:
                    for content_item in result.content:
                        if hasattr(content_item, "text"):
                            try:
                                return json_repair.loads(content_item.text)
                            except Exception:
                                return {"text": content_item.text}
                return {}

    async def _validate(
        self, config: CreateInstanceRequest
    ) -> tuple[bool, Optional[str]]:
        """
        验证单个配置

        Args:
            config: 要验证的配置

        Returns:
            (是否成功, 错误信息（如果失败）)
        """
        instance_id = config.instance_id
        instance_created = False

        async def cleanup():
            if instance_created:
                try:
                    await self._call_mcp("close_instance", {"instance_id": instance_id})
                    logger.debug(f"已清理验证实例 {instance_id}")
                except Exception as e:
                    logger.warning(f"清理实例 {instance_id} 失败: {e}")

        try:
            try:
                status_result = await self._call_mcp(
                    "get_instance_status", {"instance_id": instance_id}
                )
                if status_result.get("success"):
                    logger.warning(f"实例 {instance_id} 已存在，先清理")
                    await self._call_mcp("close_instance", {"instance_id": instance_id})
            except Exception:
                pass

            if len(config.env_modules) == 0:
                return False, "至少需要一个环境模块"

            create = await self._call_mcp(
                "create_society_instance",
                {"request": config.model_dump(mode="json")},
            )

            if not create.get("success"):
                error = create.get("error", "Unknown error")
                return False, f"创建实例失败: {error}"

            instance_created = True

            run = await self._call_mcp(
                "run_instance",
                {
                    "instance_id": instance_id,
                    "num_steps": 1,
                    "tick": config.tick,
                },
            )

            if not run.get("success"):
                error = run.get("error", "Unknown error")
                await cleanup()
                return False, f"无法启动运行: {error}"

            logger.info(f"实例 {instance_id} 验证成功")
            await cleanup()
            return True, None

        except Exception as e:
            logger.error(f"验证配置时发生异常: {e}", exc_info=True)
            await cleanup()
            return False, f"验证过程异常: {str(e)}"

    async def _fix_config(
        self, config: CreateInstanceRequest, error: str
    ) -> Optional[CreateInstanceRequest]:
        """使用 LLM 修复配置格式问题"""
        try:
            config_json = json.dumps(
                config.model_dump(mode="json"), indent=2, ensure_ascii=False
            )
            prompt = PROMPT_FIX_CONFIG.format(config_json=config_json, error_msg=error)

            messages = [
                {
                    "role": "system",
                    "content": "You are an expert at fixing JSON config format issues.",
                },
                {"role": "user", "content": prompt},
            ]

            response = await self._router.acompletion(
                model=settings.agent_model_name,
                messages=messages,
                stream=False,
            )

            content = response.choices[0].message.content
            if not content:
                logger.warning("LLM 返回内容为空")
                return None

            fixed_dict = json_repair.loads(content)
            fixed = CreateInstanceRequest.model_validate(fixed_dict)

            logger.info(f"LLM 修复配置成功: {config.instance_id}")
            return fixed

        except Exception as e:
            logger.warning(f"LLM 修复配置失败: {e}")
            return None

    async def validate(
        self, configs: List[ExperimentConfig], max_attempts: int = 5
    ) -> Dict[str, Any]:
        """
        Validate configs with auto-fix enabled by default.

        Args:
            configs: configs to validate
            max_fix_attempts: max LLM fix attempts per config (default 5)
        """
        logger.info(
            f"Start validating {len(configs)} configs (auto-fix on, max attempts {max_attempts})"
        )

        results = {
            "total": len(configs),
            "success": [],
            "failed": [],
        }

        semaphore = asyncio.Semaphore(5)

        async def validate_single(exp: ExperimentConfig):
            async with semaphore:
                config = exp.config
                was_fixed = False

                for attempt in range(max_attempts + 1):
                    success, error = await self._validate(config)
                    if success:
                        if was_fixed:
                            logger.info(
                                f"✓ {exp.experiment_name} ({exp.instance_id}) "
                                f"validated after fix attempt {attempt}"
                            )
                            exp.config = config
                        else:
                            logger.info(
                                f"✓ {exp.experiment_name} ({exp.instance_id}) validated"
                            )
                        return {"status": "success", "exp": exp}

                    if attempt < max_attempts:
                        logger.info(
                            f"Auto-fix attempt {attempt + 1} for {exp.experiment_name} ({exp.instance_id})"
                        )
                        fixed = await self._fix_config(config, error)
                        if fixed:
                            config = fixed
                            was_fixed = True
                            continue
                        logger.warning(
                            f"LLM fix failed for {exp.instance_id}, stop further attempts"
                        )
                        return {"status": "failed", "config": exp, "error": error}

                    logger.warning(
                        f"✗ {exp.experiment_name} ({exp.instance_id}) validation failed: {error}"
                    )
                    return {"status": "failed", "config": exp, "error": error}

        tasks = [validate_single(exp) for exp in configs]
        validation_results = await asyncio.gather(*tasks)

        for res in validation_results:
            if res["status"] == "success":
                results["success"].append(res["exp"])
            else:
                results["failed"].append(
                    {"config": res["config"], "error": res["error"]}
                )

        logger.info(
            f"Validation finished: {len(results['success'])} success, {len(results['failed'])} failed"
        )
        return results

    def save(
        self,
        design: ExperimentDesign,
        configs: List[ExperimentConfig],
        results: Dict[str, Any],
        output_dir: Optional[Path] = None,
    ) -> Path:
        """
        保存配置和验证结果

        Args:
            design: 实验设计
            configs: 所有配置
            results: 验证结果
            output_dir: 输出目录，默认使用 log/experiments/日期

        Returns:
            保存的文件路径
        """
        if output_dir is None:
            timestamp = datetime.now().strftime("%Y%m%d")
            output_dir = _project_root / "log" / "experiments" / timestamp
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y%m%d")
        time_str = datetime.now().strftime("%H%M%S")
        topic_safe = (
            "".join(c for c in design.topic[:40] if c.isalnum() or c in ("-", "_"))
            .strip()
            .replace(" ", "_")
            or "config"
        )
        filename = f"{date_str}_{time_str}_{topic_safe}_configs.json"
        output = output_dir / filename

        data = {
            "design": design.model_dump(mode="json", exclude_none=False),
            "configs": [c.model_dump(mode="json", exclude_none=False) for c in configs],
            "validation_results": {
                "total": results["total"],
                "success_count": len(results["success"]),
                "failed_count": len(results["failed"]),
                "success": [
                    {
                        "experiment_name": c.experiment_name,
                        "instance_id": c.instance_id,
                    }
                    for c in results["success"]
                ],
                "failed": [
                    {
                        "experiment_name": item["config"].experiment_name,
                        "instance_id": item["config"].instance_id,
                        "error": item["error"],
                    }
                    for item in results["failed"]
                ],
            },
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

        temp = output.with_suffix(".tmp")
        try:
            with temp.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp.replace(output)
            logger.info(f"配置已保存: {output}")
            return output
        except Exception as e:
            error = f"保存失败: {e}"
            logger.error(error, exc_info=True)
            try:
                if temp.exists():
                    temp.unlink()
            except Exception:
                pass
            raise RuntimeError(f"{error}。文件路径: {output}")


def load_design(file_path: Path) -> ExperimentDesign:
    """
    从文件加载实验设计

    Args:
        file_path: JSON 文件路径

    Returns:
        实验设计对象
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        data = json_repair.loads(content)
        if "design" in data:
            design_data = data["design"]
        else:
            design_data = data

        return ExperimentDesign.model_validate(design_data)
    except Exception as e:
        logger.error(f"从文件加载失败: {e}")
        raise


async def build(
    design: ExperimentDesign,
    server_url: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    便捷函数：构建并验证所有实验配置

    Args:
        design: 实验设计
        server_url: MCP server URL
        output_dir: 输出目录

    Returns:
        验证结果字典
    """
    builder = ConfigBuilder(server_url=server_url)
    configs = builder.build_configs(design)
    results = await builder.validate(configs)
    saved_path = builder.save(design, configs, results, output_dir)

    if results["failed"]:
        failed_names = [
            f"{item['config'].experiment_name}({item['config'].instance_id})"
            for item in results["failed"]
        ]
        logger.warning(
            f"{len(results['failed'])} 个配置自动修复后仍失败: {failed_names}. "
            f"将仅执行成功的配置。部分结果已保存到 {saved_path}."
        )

    successful_configs = [
        c.model_dump(mode="json", exclude_none=False)
        for c in configs
        if c in results["success"]
    ]

    return {
        "results": results,
        "saved_path": saved_path,
        "configs": successful_configs,  # 只返回成功的配置（字典格式）
    }


__all__ = [
    "ConfigBuilder",
    "ExperimentConfig",
    "load_design",
    "build",
    "settings",
]
