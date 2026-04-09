"""
分析子智能体：InsightAgent（洞察与结论）+ DataExplorer（数据探索与图表）。
二者在 Analyzer 编排下协同，产出可交付的图文报告。
"""

import shutil
from datetime import datetime
from pathlib import Path

import json_repair
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel
from agentsociety2.logger import get_logger
from agentsociety2.config import get_llm_router_and_model, get_model_name
from litellm import AllMessageValues

from .models import (
    ExperimentContext,
    AnalysisResult,
    AnalysisConfig,
    SUPPORTED_ASSET_FORMATS,
    DIR_DATA,
)
from .prompts import (
    judgment_prompt,
    analysis_xml_contract,
    strategy_xml_contract,
    adjust_tools_xml_contract,
    visualization_xml_contract,
)
from .utils import (
    XmlParseError,
    parse_llm_xml_response,
    parse_llm_xml_to_model,
    get_analysis_skills,
    extract_database_schema,
    format_database_schema_markdown,
    collect_experiment_files,
    AnalysisProgressCallback,
)
from .tool_executor import AnalysisRunner


def _system_with_skills() -> str:
    """返回分析子智能体的技能说明，并要求返回XML格式。"""
    skills = get_analysis_skills()
    base = "Return only the XML the prompt requests."
    return f"{skills}\n\n---\n\n{base}" if skills else base


class AnalysisJudgment(BaseModel):
    """分析结果判断"""

    success: bool
    reason: str
    should_retry: bool = False
    retry_instruction: str = ""


class StrategyJudgment(BaseModel):
    """分析策略判断"""

    success: bool
    reason: str
    should_retry: bool = False
    retry_instruction: str = ""


class VisualizationJudgment(BaseModel):
    """可视化结果判断"""

    success: bool
    reason: str
    should_retry: bool = False
    retry_instruction: str = ""


class InsightAgent:
    """分析子智能体：根据实验上下文产出 insights、findings、conclusions、recommendations。"""

    def __init__(
        self,
        llm_router=None,
        model_name: Optional[str] = None,
        temperature: float = 0.7,
        max_retries: int = 5,
        config: Optional[AnalysisConfig] = None,
    ):
        self.logger = get_logger()
        self.config = config
        self.temperature = config.temperature if config else temperature
        self.max_retries = max(
            1,
            min(20, config.max_analysis_retries if config else max_retries),
        )
        profile = config.llm_profile_default if config else "default"
        if llm_router is None:
            self.llm_router, self.model_name = get_llm_router_and_model(profile)
        else:
            self.llm_router = llm_router
            self.model_name = model_name or get_model_name(profile)
        self.logger.info("分析子智能体初始化完成，使用模型: %s", self.model_name)

    async def analyze(
        self,
        context: ExperimentContext,
        custom_instructions: Optional[str] = None,
        literature_summary: Optional[str] = None,
    ) -> AnalysisResult:
        """分析实验，产出分析结果。"""
        self.logger.info("开始分析实验 %s 的分析结果", context.experiment_id)
        initial_prompt = self._build_analysis_prompt(
            context, custom_instructions, literature_summary
        )
        skills = get_analysis_skills()
        messages: List[AllMessageValues] = []
        if skills:
            messages.append({"role": "system", "content": skills})
        messages.append({"role": "user", "content": initial_prompt})
        max_retries = self.max_retries
        parsed: Optional[Dict[str, Any]] = None
        prev_raw_xml = ""

        for attempt in range(max_retries):
            self.logger.info(
                "生成分析结果，使用模型: %s (第 %s/%s 次尝试)",
                self.model_name,
                attempt + 1,
                max_retries,
            )
            try:
                response = await self.llm_router.acompletion(
                    model=self.model_name,
                    messages=messages,
                    temperature=self.temperature,
                )
                raw = response.choices[0].message.content or ""
                parsed = self._parse_analysis_response(raw)
                judgment = await self._judge_analysis_result(parsed, context)
            except XmlParseError as e:
                if attempt >= max_retries - 1:
                    self.logger.warning(
                        "XML解析失败，尝试 %s 次后失败: %s", max_retries, e
                    )
                    parsed = {}
                    break
                self.logger.info("XML解析失败，重试: %s", e)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"XML parse failed: {e}\n\n"
                            "Please fix and return valid XML only."
                        ),
                    }
                )
                continue
            if (
                judgment.success
                or not judgment.should_retry
                or attempt >= max_retries - 1
            ):
                break
            self.logger.info("分析结果需要改进: %s", judgment.reason)
            prev_raw_xml = raw.strip()
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Previous XML output:\n{prev_raw_xml}\n\n"
                        f"Issue: {judgment.reason}\n"
                        f"Fix required: {judgment.retry_instruction}\n"
                        "Return corrected XML only."
                    ),
                }
            )

        if not parsed:
            parsed = {}
        return AnalysisResult(
            experiment_id=context.experiment_id,
            hypothesis_id=context.hypothesis_id,
            insights=parsed.get("insights", []),
            findings=parsed.get("findings", []),
            conclusions=parsed.get("conclusions", ""),
            recommendations=parsed.get("recommendations", []),
            generated_at=datetime.now(),
        )

    def _build_analysis_prompt(
        self,
        context: ExperimentContext,
        custom_instructions: Optional[str] = None,
        literature_summary: Optional[str] = None,
    ) -> str:
        """构建分析子智能体的分析提示。"""
        hypothesis_md_block = ""
        if getattr(context.design, "hypothesis_markdown", None):
            hypothesis_md_block = f"\n## Hypothesis Document (HYPOTHESIS.md)\n\n```markdown\n{context.design.hypothesis_markdown}\n```\n"
        experiment_md_block = ""
        if getattr(context.design, "experiment_markdown", None):
            experiment_md_block = f"\n## Experiment Design Document (EXPERIMENT.md)\n\n```markdown\n{context.design.experiment_markdown}\n```\n"
        literature_block = ""
        if literature_summary and literature_summary.strip():
            literature_block = (
                "\n## Literature context (incorporate into insights and conclusions)\n\n"
                f"{literature_summary.strip()}\n"
            )
        return f"""## Experiment
**Experiment ID**: {context.experiment_id} | **Hypothesis ID**: {context.hypothesis_id}
**Hypothesis**: {context.design.hypothesis}
**Status**: {context.execution_status.value} | **Completion**: {context.completion_percentage:.1f}% | **Duration**: {f"{context.duration_seconds:.2f}s" if context.duration_seconds else "Unknown"}
**Errors**: {chr(10).join([f"- {e}" for e in context.error_messages]) if context.error_messages else "None"}
{hypothesis_md_block}{experiment_md_block}{literature_block}{custom_instructions or ""}
{analysis_xml_contract()}"""

    def _parse_analysis_response(self, content: str) -> Dict[str, Any]:
        """解析分析子智能体的分析结果。"""
        data = parse_llm_xml_response(content, root_tag="analysis")
        insights = data.get("insights", [])
        findings = data.get("findings", [])
        recs = data.get("recommendations", [])
        if isinstance(insights, dict) and "item" in insights:
            insights = (
                insights["item"]
                if isinstance(insights["item"], list)
                else [insights["item"]]
            )
        if isinstance(findings, dict) and "item" in findings:
            findings = (
                findings["item"]
                if isinstance(findings["item"], list)
                else [findings["item"]]
            )
        if isinstance(recs, dict) and "item" in recs:
            recs = recs["item"] if isinstance(recs["item"], list) else [recs["item"]]
        return {
            "insights": (
                insights
                if isinstance(insights, list)
                else [insights]
                if insights
                else []
            ),
            "findings": (
                findings
                if isinstance(findings, list)
                else [findings]
                if findings
                else []
            ),
            "conclusions": data.get("conclusions", "") or "",
            "recommendations": (
                recs if isinstance(recs, list) else [recs] if recs else []
            ),
        }

    async def _judge_analysis_result(
        self, parsed: Dict[str, Any], context: ExperimentContext
    ) -> AnalysisJudgment:
        """判断分析结果是否合理、可接受。"""
        hypothesis_preview = (context.design.hypothesis or "")[:300]
        prompt = f"""Evaluate the analysis for experiment {context.experiment_id}.
Hypothesis (preview): {hypothesis_preview}
Generated: {len(parsed.get("insights", []))} insights, {len(parsed.get("findings", []))} findings, conclusions, {len(parsed.get("recommendations", []))} recommendations.
Check: (1) Substantive content? (2) Relevant to hypothesis? (3) Conclusions reasonable? (4) Any generic/off-topic?
{judgment_prompt()}"""
        response = await self.llm_router.acompletion(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
        )
        content = response.choices[0].message.content or ""
        return parse_llm_xml_to_model(content, AnalysisJudgment, root_tag="judgment")


class DataExplorer:
    """数据探索子智能体：决定分析策略、选表/选工具、执行并生成图表。"""

    def __init__(
        self,
        config: AnalysisConfig,
        llm_router=None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        workspace_path: Optional[Path] = None,
    ):
        """数据探索子智能体初始化。"""
        self.logger = get_logger()
        self.config = config
        self.temperature = (
            temperature if temperature is not None else config.temperature
        )
        self.workspace_path = workspace_path or Path.cwd()
        profile = config.llm_profile_default
        if llm_router is None:
            self.llm_router, self.model_name = get_llm_router_and_model(profile)
        else:
            self.llm_router = llm_router
            self.model_name = (
                model_name if model_name is not None else get_model_name(profile)
            )
        self.logger.info("数据探索子智能体初始化完成，使用模型: %s", self.model_name)

    async def analyze_data(
        self,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        db_path: Path,
        output_dir: Path,
        on_progress: AnalysisProgressCallback = None,
    ) -> Dict[str, Any]:
        """分析数据，产出分析结果。"""
        self.logger.info("开始分析数据，实验ID: %s", context.experiment_id)

        async def progress(msg: str) -> None:
            if on_progress:
                await on_progress(msg)

        data_summary = self._examine_data_sources(db_path)
        tool_executor = AnalysisRunner(
            self.workspace_path,
            output_dir,
            tool_registry=None,
            config=self.config,
        )
        available_tools = tool_executor.discover_tools_with_schemas()
        self.logger.info("发现 %s 个可用工具", len(available_tools))

        await progress("Deciding analysis strategy...")
        analysis_plan = await self._decide_analysis_strategy_with_judgment(
            context, analysis_result, data_summary, available_tools, on_progress
        )
        tool_results = {}
        if analysis_plan.get("tools_to_use"):
            await progress("Running data tools...")
            tool_results = await self._execute_tools_with_feedback(
                tool_executor,
                analysis_plan.get("tools_to_use", []),
                db_path,
                output_dir,
                context,
                analysis_result,
                data_summary,
                on_progress=on_progress,
            )
        (
            visualization_plan,
            generated_charts,
        ) = await self._decide_and_generate_visualizations_with_judgment(
            context,
            analysis_result,
            data_summary,
            tool_results,
            db_path,
            output_dir,
            tool_executor,
            on_progress=on_progress,
        )
        eda_profile_path = tool_results.get("eda_profile", {}).get("path")
        eda_sweetviz_path = tool_results.get("eda_sweetviz", {}).get("path")
        return {
            "analysis_plan": analysis_plan,
            "tool_results": tool_results,
            "visualization_plan": visualization_plan,
            "generated_charts": generated_charts,
            "eda_profile_path": Path(eda_profile_path) if eda_profile_path else None,
            "eda_sweetviz_path": Path(eda_sweetviz_path) if eda_sweetviz_path else None,
        }

    async def _run_eda_tool(
        self,
        tool_name: str,
        db_path: Path,
        output_dir: Path,
        on_progress=None,
    ) -> Dict[str, Any]:
        """执行 EDA 工具（eda_profile 或 eda_sweetviz），由数据探索子智能体决策调用。"""
        data_dir = output_dir / DIR_DATA
        data_dir.mkdir(parents=True, exist_ok=True)
        path = None
        if tool_name == "eda_profile":
            from .eda import generate_eda_profile

            path = generate_eda_profile(db_path, data_dir, config=self.config)
            if path and on_progress:
                await on_progress("EDA (ydata) generated: %s" % path.name)
        elif tool_name == "eda_sweetviz":
            from .eda import generate_sweetviz_profile

            path = generate_sweetviz_profile(db_path, data_dir, config=self.config)
            if path and on_progress:
                await on_progress("EDA (sweetviz) generated: %s" % path.name)
        if path and path.exists():
            return {"success": True, "path": str(path), "tool_name": tool_name}
        return {
            "success": False,
            "error": "EDA generation failed or skipped",
            "tool_name": tool_name,
        }

    def _examine_data_sources(self, db_path: Path) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "database": {"path": str(db_path), "exists": db_path.exists()},
        }
        if db_path.exists():
            schema = extract_database_schema(db_path)
            summary["database"]["schema_markdown"] = format_database_schema_markdown(
                schema, include_row_counts=True, db_path=db_path
            )
            summary["database"]["tables"] = list(schema.keys())
        return summary

    async def _decide_analysis_strategy(
        self,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        data_summary: Dict[str, Any],
        available_tools: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """决定分析策略，选表/选工具。"""
        tools_list = "None"
        if available_tools:
            builtin = {
                k: v for k, v in available_tools.items() if v.get("type") == "builtin"
            }
            tools_list = (
                self._format_tools_list(builtin) if builtin else "No built-in tools"
            )
        db_info = data_summary.get("database", {})
        if db_info.get("exists"):
            eda_tools = [
                "- **eda_profile** (tool_type=eda_profile): Generate EDA report via ydata-profiling (stats, distributions, missing). Use when you need data overview before deep analysis.",
                "- **eda_sweetviz** (tool_type=eda_sweetviz): Generate EDA via Sweetviz (correlations, target analysis). Use for complementary view.",
            ]
            tools_list = (
                tools_list
                + "\n\n**EDA tools** (use first when schema is complex or hypothesis needs distribution understanding):\n"
                + "\n".join(eda_tools)
            )
        schema_block = (
            db_info.get("schema_markdown")
            or "(no schema; use code_executor to discover.)"
        )
        prompt = f"""Decide how to analyze the experiment data and which tools to run.
**Hypothesis**: {context.design.hypothesis}
**Completion**: {context.completion_percentage:.1f}% | **Status**: {context.execution_status.value}
**Previous insights**: {chr(10).join([f"- {i}" for i in analysis_result.insights[:5]]) if analysis_result.insights else "None yet."}
**Database**: {db_info.get("path", "")}
**Database schema (read first; use only these tables/columns)**:
{schema_block}
**Available tools**: {tools_list}
{strategy_xml_contract()}
Include eda_profile or eda_sweetviz as first step when you need data overview (distributions, correlations) before code analysis."""
        response = await self.llm_router.acompletion(
            model=self.model_name,
            messages=[
                {"role": "system", "content": _system_with_skills()},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
        )
        data = parse_llm_xml_response(
            response.choices[0].message.content or "", root_tag="strategy"
        )
        tools = data.get("tools_to_use", [])
        if isinstance(tools, dict) and "tool" in tools:
            tools = (
                tools["tool"] if isinstance(tools["tool"], list) else [tools["tool"]]
            )
        if not isinstance(tools, list):
            tools = []
        normalized = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            params = t.get("parameters", {})
            if isinstance(params, str):
                try:
                    params = json_repair.loads(params) if params.strip() else {}
                except Exception:
                    params = {}
            normalized.append(
                {
                    "tool_name": t.get("tool_name", "code_executor"),
                    "tool_type": t.get("tool_type", "code_executor"),
                    "action": t.get("action", ""),
                    "parameters": params if isinstance(params, dict) else {},
                }
            )
        return {
            "analysis_strategy": data.get("analysis_strategy", ""),
            "tools_to_use": normalized,
        }

    async def _judge_analysis_strategy(
        self,
        analysis_plan: Dict[str, Any],
        context: ExperimentContext,
        data_summary: Dict[str, Any],
    ) -> StrategyJudgment:
        """判断分析策略是否合理、可执行。"""
        prompt = f"""Evaluate the analysis strategy for experiment {context.experiment_id}.

**Hypothesis**: {context.design.hypothesis}
**Database**: {data_summary.get("database", {}).get("path", "")}

**Proposed strategy**:
- analysis_strategy: {analysis_plan.get("analysis_strategy", "")}
- tools_to_use: {analysis_plan.get("tools_to_use", [])}

Check: (1) Strategy relevant to hypothesis? (2) Tools appropriate for schema? (3) EDA tools used when data overview needed? (4) Action descriptions clear?
{judgment_prompt()}"""
        response = await self.llm_router.acompletion(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        content = response.choices[0].message.content or ""
        return parse_llm_xml_to_model(content, StrategyJudgment, root_tag="judgment")

    async def _decide_analysis_strategy_with_judgment(
        self,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        data_summary: Dict[str, Any],
        available_tools: Optional[Dict[str, Dict[str, Any]]],
        on_progress: Optional[AnalysisProgressCallback],
    ) -> Dict[str, Any]:
        """决定分析策略，经 LLM 裁判通过后返回。"""
        max_retries = self.config.max_strategy_retries
        for attempt in range(max_retries):
            try:
                analysis_plan = await self._decide_analysis_strategy(
                    context, analysis_result, data_summary, available_tools
                )
                judgment = await self._judge_analysis_strategy(
                    analysis_plan, context, data_summary
                )
            except XmlParseError as e:
                if attempt >= max_retries - 1:
                    self.logger.warning(
                        "分析策略XML解析失败，尝试 %s 次后失败: %s",
                        max_retries,
                        e,
                    )
                    return {"analysis_strategy": "", "tools_to_use": []}
                if on_progress:
                    await on_progress(f"Strategy XML parse failed, retrying: {e}")
                continue
            if (
                judgment.success
                or not judgment.should_retry
                or attempt >= max_retries - 1
            ):
                return analysis_plan
            if on_progress:
                await on_progress(f"Strategy needs improvement: {judgment.reason}")
            self.logger.info(
                "Strategy judgment: %s, retrying: %s",
                judgment.reason,
                judgment.retry_instruction,
            )
        return analysis_plan

    async def _execute_tools_with_feedback(
        self,
        tool_executor: AnalysisRunner,
        tools_to_use: List[Dict[str, Any]],
        db_path: Path,
        output_dir: Path,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        data_summary: Dict[str, Any],
        on_progress: AnalysisProgressCallback = None,
    ) -> Dict[str, Any]:
        """执行工具，并根据反馈调整策略。"""

        async def progress(msg: str) -> None:
            if on_progress:
                await on_progress(msg)

        results = {}
        conversation_history = []
        max_iter = self.config.max_tool_iterations
        for iteration in range(max_iter):
            current_tools = tools_to_use if iteration == 0 else []
            if iteration > 0:
                adj = await self._adjust_strategy_based_on_results(
                    context,
                    analysis_result,
                    data_summary,
                    results,
                    conversation_history,
                )
                if not adj.get("tools_to_use"):
                    break
                current_tools = adj.get("tools_to_use", [])
            for i, tool_spec in enumerate(current_tools):
                tool_name = tool_spec.get("tool_name", f"tool_{i}")
                tool_type = tool_spec.get("tool_type", "code_executor")
                parameters = tool_spec.get("parameters", {})
                await progress(f"Running tool: {tool_name}...")
                if tool_type in ("eda_profile", "eda_sweetviz") or tool_name in (
                    "eda_profile",
                    "eda_sweetviz",
                ):
                    result = await self._run_eda_tool(
                        tool_name,
                        db_path,
                        output_dir,
                        on_progress=progress,
                    )
                else:
                    exec_parameters = parameters.copy()
                    if tool_type == "code_executor":
                        exec_parameters["db_path"] = str(db_path)
                        exec_parameters["code_description"] = tool_spec.get(
                            "action", ""
                        )
                        exec_parameters["extra_files"] = collect_experiment_files(
                            db_path
                        )
                    result = await tool_executor.execute_tool(
                        tool_name=tool_name,
                        tool_type=tool_type,
                        parameters=exec_parameters,
                    )
                results[tool_name] = result
                conversation_history.append(
                    {"tool": tool_name, "result": result, "iteration": iteration + 1}
                )
        return results

    async def _adjust_strategy_based_on_results(
        self,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        data_summary: Dict[str, Any],
        current_results: Dict[str, Any],
        conversation_history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """根据工具执行结果，决定是否继续执行工具或停止。"""
        prompt = f"""Decide whether to run more tools or stop.
**Hypothesis**: {context.design.hypothesis} | **Completion**: {context.completion_percentage:.1f}%
**Tool results**: {self._format_tool_results(current_results)}
**Recent**: {chr(10).join([f"- Iter {h['iteration']}: {h['tool']} - {'OK' if h['result'].get('success') else 'Failed'}" for h in conversation_history[-5:]])}
{adjust_tools_xml_contract()}"""
        response = await self.llm_router.acompletion(
            model=self.model_name,
            messages=[
                {"role": "system", "content": _system_with_skills()},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
        )
        data = parse_llm_xml_response(
            response.choices[0].message.content or "", root_tag="adjust"
        )
        tools = data.get("tools_to_use", [])
        if isinstance(tools, dict):
            t = tools.get("tool", [])
            tools = t if isinstance(t, list) else [t] if t else []
        elif not isinstance(tools, list):
            tools = []
        normalized = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            params = t.get("parameters", {})
            if isinstance(params, str):
                try:
                    params = json_repair.loads(params) if params.strip() else {}
                except Exception:
                    params = {}
            normalized.append(
                {
                    "tool_name": t.get("tool_name", "code_executor"),
                    "tool_type": t.get("tool_type", "code_executor"),
                    "action": t.get("action", ""),
                    "parameters": params if isinstance(params, dict) else {},
                }
            )
        return {"assessment": data.get("assessment", ""), "tools_to_use": normalized}

    async def _decide_visualizations(
        self,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        data_summary: Dict[str, Any],
        analysis_results: Dict[str, Any],
        previous_feedback: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """决定可视化方案，生成图表。"""
        feedback_block = ""
        if previous_feedback and previous_feedback.strip():
            feedback_block = (
                f"\n**Previous attempt feedback (must address)**: {previous_feedback}\n"
            )
        schema_block = (
            data_summary.get("database", {}).get("schema_markdown") or "(no schema)"
        )
        prompt = f"""Decide which charts to generate.
**Hypothesis**: {context.design.hypothesis} | **Completion**: {context.completion_percentage:.1f}%
**Insights**: {chr(10).join([f"- {i}" for i in analysis_result.insights[:5]]) if analysis_result.insights else "None."}
**Database**: {data_summary["database"]["path"]}
**Table row counts** (from schema): Check which tables have data before suggesting charts.
{schema_block}
**Tool results**: {self._format_tool_results(analysis_results)}
{feedback_block}
{visualization_xml_contract()}"""
        response = await self.llm_router.acompletion(
            model=self.model_name,
            messages=[
                {"role": "system", "content": _system_with_skills()},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
        )
        data = parse_llm_xml_response(
            response.choices[0].message.content or "", root_tag="visualizations"
        )
        viz = data.get("viz", data.get("visualizations", []))
        if isinstance(viz, dict):
            viz = [viz]
        if not isinstance(viz, list):
            viz = []
        return [
            {
                "use_tool": v.get("use_tool", True) if isinstance(v, dict) else True,
                "tool_name": (
                    v.get("tool_name", "code_executor")
                    if isinstance(v, dict)
                    else "code_executor"
                ),
                "tool_description": (
                    v.get("tool_description", "") if isinstance(v, dict) else ""
                ),
            }
            for v in viz
        ]

    async def _judge_visualizations(
        self,
        visualization_plan: List[Dict[str, Any]],
        generated_charts: List[Path],
        context: ExperimentContext,
        tool_results: Dict[str, Any],
        error_logs: Optional[List[str]] = None,
    ) -> VisualizationJudgment:
        """判断可视化结果是否充分、与假设相关。"""
        chart_names = [p.name for p in generated_charts]
        hyp = context.design.hypothesis or "Not specified"
        errors_block = ""
        if error_logs:
            errors_block = "\n**Execution Errors**:\n" + "\n".join(
                f"- {e}" for e in error_logs
            )

        prompt = f"""Evaluate the visualization output for experiment {context.experiment_id}.

**Hypothesis**: {hyp}
**Visualization plan**: {len(visualization_plan)} items
**Generated charts**: {chart_names}{errors_block}

Note: Diagnostic charts (e.g. table_row_counts_diagnostic.png) are auto-generated supplements; do not count them as plan violations. Plan items refer to main analysis charts only.

Check: (1) Charts relevant to hypothesis? (2) Adequate for report? (3) Any failures that need retry? (If errors are present, suggest how to fix code/data issues).
If no charts were planned (empty plan), success=true. If plan had items but none generated, success=false.
{judgment_prompt()}"""
        response = await self.llm_router.acompletion(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        content = response.choices[0].message.content or ""
        return parse_llm_xml_to_model(
            content, VisualizationJudgment, root_tag="judgment"
        )

    async def _decide_and_generate_visualizations_with_judgment(
        self,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        data_summary: Dict[str, Any],
        tool_results: Dict[str, Any],
        db_path: Path,
        output_dir: Path,
        tool_executor: AnalysisRunner,
        on_progress: AnalysisProgressCallback = None,
    ) -> tuple[List[Dict[str, Any]], List[Path]]:
        """决定可视化方案、生成图表，经分析子智能体裁判通过后返回。"""
        max_retries = self.config.max_visualization_retries
        previous_feedback: Optional[str] = None
        visualization_plan: List[Dict[str, Any]] = []
        generated_charts: List[Path] = []

        async def progress(msg: str) -> None:
            if on_progress:
                await on_progress(msg)

        for attempt in range(max_retries):
            try:
                await progress("Deciding visualizations...")
                visualization_plan = await self._decide_visualizations(
                    context,
                    analysis_result,
                    data_summary,
                    tool_results,
                    previous_feedback=previous_feedback,
                )
            except XmlParseError as e:
                if attempt >= max_retries - 1:
                    self.logger.warning(
                        "可视化XML解析失败，尝试 %s 次后失败: %s",
                        max_retries,
                        e,
                    )
                    return [], []
                previous_feedback = str(e)
                continue

            if not visualization_plan:
                return [], []

            await progress("Generating charts...")
            generated_charts, error_logs = await self._generate_visualizations(
                visualization_plan,
                db_path,
                output_dir,
                tool_executor,
                on_progress=on_progress,
            )
            try:
                judgment = await self._judge_visualizations(
                    visualization_plan,
                    generated_charts,
                    context,
                    tool_results,
                    error_logs=error_logs,
                )
            except XmlParseError as e:
                if attempt >= max_retries - 1:
                    self.logger.warning("可视化判断XML解析失败: %s", e)
                    return visualization_plan, generated_charts
                previous_feedback = str(e)
                continue
            if (
                judgment.success
                or not judgment.should_retry
                or attempt >= max_retries - 1
            ):
                return visualization_plan, generated_charts
            previous_feedback = f"{judgment.reason}. {judgment.retry_instruction}"
            self.logger.info("可视化判断: %s, 重试", judgment.reason)

        return visualization_plan, generated_charts

    async def _generate_visualizations(
        self,
        visualization_plan: List[Dict[str, Any]],
        db_path: Path,
        output_dir: Path,
        tool_executor: AnalysisRunner,
        on_progress: AnalysisProgressCallback = None,
    ) -> Tuple[List[Path], List[str]]:
        async def progress(msg: str) -> None:
            if on_progress:
                await on_progress(msg)

        generated_charts: List[Path] = []
        error_logs: List[str] = []
        if not visualization_plan or not any(
            v.get("use_tool") or v.get("tool_name") for v in visualization_plan
        ):
            return generated_charts, error_logs
        total = sum(
            1 for v in visualization_plan if v.get("use_tool") or v.get("tool_name")
        )
        done = 0
        for viz in visualization_plan:
            if not viz.get("use_tool") and not viz.get("tool_name"):
                continue
            done += 1
            await progress(
                f"Generating chart {done}/{total}..."
                if total > 1
                else "Generating chart..."
            )
            tool_description = (
                viz.get("tool_description") or viz.get("description") or ""
            )
            if not tool_description:
                continue
            result = await tool_executor.execute_tool(
                tool_name=viz.get("tool_name", "code_executor"),
                tool_type="code_executor",
                parameters={
                    "db_path": str(db_path),
                    "code_description": tool_description,
                    "extra_files": collect_experiment_files(db_path),
                },
            )
            if not result.get("success"):
                error_msg = result.get("error", "unknown")
                self.logger.warning("工具执行失败: %s", error_msg)
                error_logs.append(f"Chart {done} failed: {error_msg}")
                continue
            generated_charts.extend(
                self._collect_generated_chart_paths(result, output_dir)
            )
        return generated_charts, error_logs

    def _collect_generated_chart_paths(
        self, tool_result: Dict[str, Any], output_dir: Path
    ) -> List[Path]:
        """标准化收集工具产出的图表文件。"""
        chart_paths: List[Path] = []
        for artifact_path_str in tool_result.get("artifacts", []):
            artifact_path = Path(artifact_path_str)
            if not artifact_path.exists() or not artifact_path.is_file():
                continue
            if artifact_path.suffix.lower() not in SUPPORTED_ASSET_FORMATS:
                continue
            dest_path = output_dir / artifact_path.name
            if artifact_path.resolve() != dest_path.resolve():
                shutil.copy2(artifact_path, dest_path)
            chart_paths.append(dest_path)
        return chart_paths

    def _format_tools_list(self, tools: Dict[str, Dict[str, Any]]) -> str:
        """格式化工具列表。"""
        if not tools:
            return "No built-in tools available"
        file_order = [
            "read_file",
            "write_file",
            "list_directory",
            "glob",
            "search_file_content",
        ]
        entries = []
        for name, info in tools.items():
            desc = info.get("description", "No description")
            params = info.get("parameters_description") or info.get("parameters")
            if params is not None and not isinstance(params, str):
                params = ", ".join(str(p) for p in params)
            line = f"- **{name}**: {desc}" + (
                f" Parameters: {params}" if params else ""
            )
            entries.append(
                (file_order.index(name) if name in file_order else 999, line)
            )
        entries.sort(key=lambda x: x[0])
        return "\n".join(e[1] for e in entries)

    def _format_tool_results(self, tool_results: Dict[str, Any]) -> str:
        """格式化工具执行结果。"""
        if not tool_results:
            return "No tool execution results"
        lines = []
        for name, result in tool_results.items():
            success = result.get("success", False)
            lines.append(f"\n**{name}**: {'✅ Success' if success else '❌ Failed'}")
            if success:
                if "path" in result:
                    lines.append(f"Output: {result['path']}")
                elif "stdout" in result:
                    lines.append(f"Output: {result['stdout'][:500]}")
                if "result" in result and "path" not in result:
                    lines.append(f"Result: {str(result['result'])[:500]}")
            else:
                lines.append(f"Error: {result.get('error', 'Unknown')}")
        return "\n".join(lines) if lines else "No results"

    async def close(self) -> None:
        """关闭数据探索子智能体。"""
        pass
