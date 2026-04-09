"""
报告生成子智能体：将分析结果与图表组装成图文并茂的 Markdown/HTML 报告。
"""

import base64
import json
import mimetypes
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agentsociety2.logger import get_logger
from litellm import AllMessageValues
from pydantic import BaseModel

from .models import (
    ExperimentContext,
    AnalysisResult,
    ReportContent,
    ReportAsset,
    AnalysisConfig,
    SUPPORTED_IMAGE_FORMATS,
    DIR_ARTIFACTS,
    DIR_DATA,
    DIR_REPORT_ASSETS,
    DIR_RUN,
    DIR_HYPOTHESIS_PREFIX,
    DIR_EXPERIMENT_PREFIX,
    FILE_ANALYSIS_SUMMARY_JSON,
    FILE_README_MD,
    FILE_REPORT_HTML,
    FILE_REPORT_MD,
)
from .agents import InsightAgent
from .prompts import report_judgment_prompt, report_xml_instruction
from .utils import (
    XmlParseError,
    parse_llm_report_response,
    parse_llm_xml_to_model,
    get_analysis_skills,
    AnalysisProgressCallback,
    _sanitize_id,
)


class ReportGenerationResult(BaseModel):
    """报告生成结果判断"""

    success: bool
    reason: str
    has_markdown: bool
    has_html: bool
    should_retry: bool = False
    retry_instruction: str = ""


class AssetProcessor:
    """发现并处理报告所需的可视化资源（复制/内嵌）。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path
        self.logger = get_logger()

    def discover_assets(
        self, experiment_id: str, hypothesis_id: str
    ) -> List[ReportAsset]:
        """
        在固定默认路径下发现可视化资源。

        Args:
            experiment_id: 实验ID
            hypothesis_id: 假设ID

        Returns:
            发现到的 ReportAsset 列表
        """
        hid = _sanitize_id(hypothesis_id)
        eid = _sanitize_id(experiment_id)
        asset_path = (
            self.workspace_path
            / f"{DIR_HYPOTHESIS_PREFIX}{hid}"
            / f"{DIR_EXPERIMENT_PREFIX}{eid}"
            / DIR_RUN
            / DIR_ARTIFACTS
        )

        assets: List[ReportAsset] = []
        if not asset_path.exists():
            return assets

        for file_path in asset_path.rglob("*"):
            if file_path.suffix.lower() not in SUPPORTED_IMAGE_FORMATS:
                continue
            assets.append(
                ReportAsset(
                    asset_id=f"viz_{file_path.stem}",
                    asset_type="visualization",
                    title=self._format_title(file_path.stem),
                    file_path=str(file_path),
                    description=f"Generated visualization: {file_path.name}",
                    file_size=file_path.stat().st_size,
                    embedded_content=None,
                )
            )

        return assets

    def process_assets(
        self, assets: List[ReportAsset], output_dir: Path
    ) -> Dict[str, Any]:
        """
        处理资源并复制到输出目录，同时可选生成可内嵌的 base64 数据。

        Args:
            assets: ReportAsset 列表
            output_dir: 输出目录

        Returns:
            asset_id -> 处理后信息 的字典
        """
        assets_dir = output_dir / DIR_REPORT_ASSETS
        assets_dir.mkdir(exist_ok=True)
        processed_assets: Dict[str, Any] = {}

        for asset in assets:
            source_path = Path(asset.file_path)
            if not source_path.exists():
                self.logger.warning("资源不存在: %s", source_path)
                continue

            dest_path = assets_dir / source_path.name
            src_resolved = source_path.resolve(strict=False)
            dst_resolved = dest_path.resolve(strict=False)
            if src_resolved != dst_resolved:
                shutil.copy2(source_path, dest_path)

            if source_path.suffix.lower() in SUPPORTED_IMAGE_FORMATS:
                with open(source_path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                    mime_type, _ = mimetypes.guess_type(source_path.name)
                    if not mime_type:
                        suffix = source_path.suffix.lower()
                        mime_type = (
                            f"image/{suffix[1:]}"
                            if suffix.startswith(".")
                            else "application/octet-stream"
                        )
                    asset.embedded_content = f"data:{mime_type};base64,{encoded}"

            processed_assets[asset.asset_id] = {
                "title": asset.title,
                "local_path": str(dest_path),
                "relative_path": f"{DIR_REPORT_ASSETS}/{source_path.name}",
                "embedded_data": asset.embedded_content,
                "description": asset.description,
            }

        return processed_assets

    def _format_title(self, filename: str) -> str:
        """将文件名格式化为可读标题。"""
        title = filename.replace("_", " ").replace("-", " ")
        return " ".join(word.capitalize() for word in title.split())


class Reporter:
    """报告子智能体：将洞察与图表组装成图文并茂的 Markdown/HTML 报告。"""

    def __init__(self, agent: InsightAgent, config: AnalysisConfig):
        """
        Args:
            agent: InsightAgent 实例（用于 LLM 生成内容）
            config: 分析配置（必须，用于 max_retries 等）
        """
        self.logger = get_logger()
        self.agent = agent
        self.config = config
        self.max_retries = config.max_analysis_retries
        self.logger.info("使用 %s 来生成报告", self.agent.model_name)

    async def generate(
        self,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        processed_assets: Dict[str, Any],
        output_dir: Path,
        literature_summary: Optional[str] = None,
        eda_profile_path: Optional[Path] = None,
        eda_sweetviz_path: Optional[Path] = None,
        quick_stats_md: Optional[str] = None,
        on_progress: AnalysisProgressCallback = None,
    ) -> Tuple[Dict[str, str], bool]:
        """
        生成图文并茂的报告（Markdown + HTML）。
        literature_summary: 可选，文献摘要。
        eda_profile_path: 可选，ydata-profiling EDA 概览路径。
        eda_sweetviz_path: 可选，Sweetviz EDA 报告路径。
        quick_stats_md: 可选，pandas describe 统计摘要（Markdown），供 LLM 参考。
        Returns: (文件路径字典, report_complete 是否成功)
        """

        async def progress(msg: str) -> None:
            if on_progress:
                await on_progress(msg)

        max_retries = self.max_retries
        retry_count = 0
        last_retry_instruction: Optional[str] = None

        while retry_count < max_retries:
            try:
                await progress("Generating report content...")
                content = await self._generate_content(
                    context,
                    analysis_result,
                    processed_assets,
                    literature_summary,
                    eda_profile_path,
                    eda_sweetviz_path,
                    quick_stats_md,
                    previous_retry_instruction=last_retry_instruction,
                )
                files = {}
                await progress("Saving report (Markdown & HTML)...")
                md_path = await self._save_markdown(content, output_dir)
                md_path = self._embed_charts_in_markdown(
                    md_path, output_dir, processed_assets
                )
                files["markdown"] = str(md_path)
                html_path = await self._save_html(content, output_dir)
                html_path = self._embed_charts_in_html(
                    html_path, output_dir, processed_assets
                )
                html_path = self._embed_eda_in_html(
                    html_path, output_dir, eda_profile_path, eda_sweetviz_path
                )
                files["html"] = str(html_path)
                await progress("Checking report quality...")
                judgment = await self._judge_report_generation(
                    content, md_path, html_path, processed_assets
                )
            except XmlParseError as e:
                self.logger.warning("报告XML解析失败: %s", e)
                if retry_count >= max_retries - 1:
                    files = await self._save_supporting_files(
                        context, analysis_result, output_dir
                    )
                    files["markdown"] = str(output_dir / FILE_REPORT_MD)
                    files["html"] = str(output_dir / FILE_REPORT_HTML)
                    return (files, False)
                last_retry_instruction = (
                    f"XML parse failed: {e}. Return valid XML only."
                )
                retry_count += 1
                self.logger.info(
                    "重试报告生成，XML解析错误 (%s/%s)", retry_count, max_retries
                )
                continue
            except Exception as e:
                self.logger.warning("报告生成异常: %s", e)
                judgment = await self._judge_exception(e, retry_count, max_retries)
                if not judgment.should_retry or retry_count >= max_retries - 1:
                    self.logger.error("报告生成异常后失败: %s", judgment.reason)
                    files = await self._save_supporting_files(
                        context, analysis_result, output_dir
                    )
                    files["markdown"] = str(output_dir / FILE_REPORT_MD)
                    files["html"] = str(output_dir / FILE_REPORT_HTML)
                    return (files, False)
                last_retry_instruction = judgment.retry_instruction
                retry_count += 1
                self.logger.info(
                    "重试报告生成，异常 (%s/%s): %s",
                    retry_count,
                    max_retries,
                    judgment.retry_instruction,
                )
                continue

            if judgment.success:
                files.update(
                    await self._save_supporting_files(
                        context, analysis_result, output_dir
                    )
                )
                return (files, True)

            if not judgment.should_retry or retry_count >= max_retries - 1:
                self.logger.warning(
                    "报告生成失败: %s. 保存部分结果。",
                    judgment.reason,
                )
                files.update(
                    await self._save_supporting_files(
                        context, analysis_result, output_dir
                    )
                )
                return (files, False)

            last_retry_instruction = judgment.retry_instruction
            retry_count += 1
            self.logger.info(
                "重试报告生成 (%s/%s): %s",
                retry_count,
                max_retries,
                judgment.retry_instruction,
            )

        return ({}, False)

    async def _generate_content(
        self,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        processed_assets: Dict[str, Any],
        literature_summary: Optional[str] = None,
        eda_profile_path: Optional[Path] = None,
        eda_sweetviz_path: Optional[Path] = None,
        quick_stats_md: Optional[str] = None,
        previous_retry_instruction: Optional[str] = None,
    ) -> ReportContent:
        """构建报告生成 prompt。"""
        prompt = self._build_prompt(
            context,
            analysis_result,
            processed_assets,
            literature_summary,
            eda_profile_path,
            eda_sweetviz_path,
            quick_stats_md,
            previous_retry_instruction,
        )
        skills = get_analysis_skills()
        system = (
            f"{skills}\n\n---\n\n"
            "You are an experiment report expert. Based on analysis context and data, **decide** layout, structure, and which charts to include. "
            "Select charts that best support your findings; place them where they fit the narrative. You may include all, some, or none—based on relevance. "
            "HTML must be **professional and visually appealing**: proper layout, clear hierarchy, spacing and styling. "
            f"{report_xml_instruction()} "
            'For charts you include: HTML use <img src="assets/filename.png" alt="title">; Markdown use ![title](assets/filename.png).'
        )
        if not skills:
            system = (
                "Based on report content and charts, decide layout and generate a professional HTML report. "
                f"{report_xml_instruction()}"
            )
        messages: List[AllMessageValues] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        self.logger.info("使用 %s 生成报告内容", self.agent.model_name)

        response = await self.agent.llm_router.acompletion(
            model=self.agent.model_name,
            messages=messages,
            temperature=self.agent.temperature,
        )

        llm_content = response.choices[0].message.content or ""
        return self._parse_content(llm_content, context)

    def _build_prompt(
        self,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        processed_assets: Dict[str, Any],
        literature_summary: Optional[str] = None,
        eda_profile_path: Optional[Path] = None,
        eda_sweetviz_path: Optional[Path] = None,
        quick_stats_md: Optional[str] = None,
        previous_retry_instruction: Optional[str] = None,
    ) -> str:
        status_msg = self._get_status_message(context.execution_status.value)
        viz_block = self._format_viz_for_llm(processed_assets)
        retry_block = ""
        if previous_retry_instruction and previous_retry_instruction.strip():
            retry_block = f"\n## Previous feedback (must address)\n{previous_retry_instruction.strip()}\n\n"
        literature_block = ""
        if literature_summary and literature_summary.strip():
            lit = literature_summary.strip()
            if len(lit) > 3000:
                lit = lit[:3000] + "\n\n[... truncated for length ...]"
            literature_block = f"\n## Literature\n{lit}\n\n"
        eda_block = ""
        eda_files: List[str] = []
        if eda_profile_path and eda_profile_path.exists():
            eda_files.append(
                "**data/eda_profile.html** (ydata-profiling: stats, distributions, missing)"
            )
        if eda_sweetviz_path and eda_sweetviz_path.exists():
            eda_files.append(
                "**data/eda_sweetviz.html** (Sweetviz: correlations, target analysis)"
            )
        if eda_files:
            eda_block = (
                "\n## Data overview (EDA)\n"
                "Exploratory data analysis profiles generated:\n"
                + "\n".join(f"- {f}" for f in eda_files)
                + '\n\nInclude links or references to these in your report (e.g. a "Data Overview" section). '
                "Summarize key findings if relevant to the hypothesis.\n\n"
            )
        quick_stats_block = ""
        if quick_stats_md and quick_stats_md.strip():
            qs = quick_stats_md.strip()
            if len(qs) > 2500:
                qs = qs[:2500] + "\n\n[... truncated ...]"
            quick_stats_block = (
                "\n## Quick stats (pandas describe)\n"
                "Use these for reference when discussing data:\n\n"
                f"{qs}\n\n"
            )

        return f"""## Experiment Context

**Experiment ID**: {context.experiment_id}
**Hypothesis**: {context.design.hypothesis}
**Completion**: {context.completion_percentage:.1f}%
**Status**: {context.execution_status.value}
**Duration**: {f"{context.duration_seconds:.2f}s" if context.duration_seconds else "Not available"}

**Objectives**: {self._format_list(context.design.objectives) if context.design.objectives else "Not specified"}
**Success Criteria**: {self._format_list(context.design.success_criteria) if context.design.success_criteria else "Not specified"}
**Status context**: {status_msg}

## Analysis Results

**Key Insights** ({len(analysis_result.insights)}):
{self._format_list_truncated(analysis_result.insights, max_items=8, max_item_len=250)}

**Findings** ({len(analysis_result.findings)}):
{self._format_list_truncated(analysis_result.findings, max_items=8, max_item_len=250)}

**Conclusions**:
{self._truncate_text(analysis_result.conclusions or "", 1500)}

**Recommendations** ({len(analysis_result.recommendations)}):
{self._format_list_truncated(analysis_result.recommendations, max_items=6, max_item_len=200)}

## Visualizations (for layout)

{viz_block}
{retry_block}{literature_block}
{eda_block}
{quick_stats_block}

Based on the above content, generate a professional report. **Decide** which visualizations (if any) support your analysis and embed them where they fit. HTML must be a complete document (DOCTYPE, head, body, styles)."""

    def _format_viz_for_llm(self, processed_assets: Dict[str, Any]) -> str:
        """将图表信息提供给 LLM，仅传路径和标题以控制 prompt 长度（不传 base64）。"""
        if not processed_assets:
            return "No visualizations available."
        lines = []
        for asset_id, data in processed_assets.items():
            title = data.get("title", asset_id)
            rel = data.get("relative_path", "")
            desc = (data.get("description") or "").strip()
            lines.append(f"### {title}")
            lines.append(f"- Path: {rel}")
            if desc:
                lines.append(f"- Description: {desc[:200]}")
            lines.append("")
        lines.append(
            "**Decide** which charts support your analysis and embed them where appropriate. "
            f'HTML: <img src="{DIR_REPORT_ASSETS}/filename.png" alt="title">. '
            f"Markdown: ![title]({DIR_REPORT_ASSETS}/filename.png)."
        )
        return "\n".join(lines)

    def _parse_content(self, content: str, context: ExperimentContext) -> ReportContent:
        """解析 LLM 返回的 XML，获取 markdown 与 html。"""
        data = parse_llm_report_response(content)
        markdown_content = (data.get("markdown") or "").strip()
        html_content = (data.get("html") or "").strip()
        title = f"Analysis: {context.design.hypothesis}"
        subtitle = f"Experiment {context.experiment_id}"
        return ReportContent(
            title=title,
            subtitle=subtitle,
            format_preference="both",
            full_content_markdown=markdown_content,
            full_content_html=html_content,
        )

    async def _judge_exception(
        self, exc: Exception, retry_count: int, max_retries: int
    ) -> ReportGenerationResult:
        """出现异常时由 LLM 裁判判断是否可重试及改进方向。"""
        prompt = f"""An exception occurred during report generation:

**Exception type**: {type(exc).__name__}
**Exception message**: {exc}

Please judge:
1. Can this exception be resolved by retry? (e.g. transient network failure, LLM output format issues)
2. If retryable, how to improve? (e.g. check dependencies, adjust prompt)
3. If not retryable (e.g. missing required dependency like markdown), state clearly.

Current retry count: {retry_count}/{max_retries}

{report_judgment_prompt()}"""
        try:
            response = await self.agent.llm_router.acompletion(
                model=self.agent.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            content = response.choices[0].message.content
            if content:
                return parse_llm_xml_to_model(
                    content, ReportGenerationResult, root_tag="judgment"
                )
        except Exception as judge_err:
            self.logger.warning("裁判异常失败: %s", judge_err)
        is_import = isinstance(exc, ImportError)
        return ReportGenerationResult(
            success=False,
            reason=str(exc),
            has_markdown=False,
            has_html=False,
            should_retry=not is_import and retry_count < max_retries - 1,
            retry_instruction=(
                "Install missing dependencies (e.g. pip install markdown) or fix the reported error."
                if is_import
                else "Retry report generation; check logs for details."
            ),
        )

    async def _judge_report_generation(
        self,
        content: ReportContent,
        md_path: Path,
        html_path: Path,
        processed_assets: Optional[Dict[str, Any]] = None,
    ) -> ReportGenerationResult:
        """裁判报告生成结果。"""
        md_exists = md_path.exists() and md_path.stat().st_size > 0
        html_exists = html_path.exists() and html_path.stat().st_size > 0
        has_markdown_content = bool(
            content.full_content_markdown and content.full_content_markdown.strip()
        )
        has_html_content = bool(
            content.full_content_html and content.full_content_html.strip()
        )
        html_preview = (content.full_content_html or "")[:800]
        num_assets = len(processed_assets) if processed_assets else 0

        report_summary = f"""## Report Generation Result

**Markdown Report**:
- File exists: {md_exists}
- Has content: {has_markdown_content}
- File size: {md_path.stat().st_size if md_exists else 0} bytes

**HTML Report**:
- File exists: {html_exists}
- Has content: {has_html_content}
- File size: {html_path.stat().st_size if html_exists else 0} bytes

**Visualizations**: {num_assets} assets available. Author may have chosen to include all, some, or none.

**HTML Preview** (first 800 chars):
{html_preview}

Evaluate:
1. Both Markdown and HTML must be present and meaningful.
2. HTML must be complete document (DOCTYPE, head, body) with proper layout.
3. If the report includes chart references, they should be properly embedded (img src, assets path).
4. success=true if content is coherent and HTML is properly formatted. Chart inclusion is the author's choice.

{report_judgment_prompt()}"""

        messages: List[AllMessageValues] = [{"role": "user", "content": report_summary}]

        response = await self.agent.llm_router.acompletion(
            model=self.agent.model_name,
            messages=messages,
            temperature=self.agent.temperature,
        )

        response_content = response.choices[0].message.content
        if not response_content:
            return ReportGenerationResult(
                success=False,
                reason="LLM returned empty response",
                has_markdown=has_markdown_content,
                has_html=has_html_content,
                should_retry=True,
                retry_instruction="Regenerate report with complete content",
            )

        return parse_llm_xml_to_model(
            response_content, ReportGenerationResult, root_tag="judgment"
        )

    async def _save_markdown(
        self,
        content: ReportContent,
        output_dir: Path,
    ) -> Path:
        """
        保存 Markdown 报告。

        Args:
            content: ReportContent 对象
            output_dir: 输出目录

        Returns:
            保存的 Markdown 文件路径
        """
        md_file = output_dir / FILE_REPORT_MD
        md_content = content.full_content_markdown or ""
        md_file.write_text(md_content, encoding="utf-8")
        self.logger.info("保存 Markdown 报告: %s", md_file)
        return md_file

    async def _save_html(
        self,
        content: ReportContent,
        output_dir: Path,
    ) -> Path:
        """
        保存 HTML 报告。

        Args:
            content: ReportContent 对象
            output_dir: 输出目录

        Returns:
            保存的 HTML 文件路径
        """
        html_file = output_dir / FILE_REPORT_HTML
        html_content = content.full_content_html or ""
        html_file.write_text(html_content, encoding="utf-8")
        self.logger.info("保存 HTML 报告: %s", html_file)
        return html_file

    def _embed_charts_in_html(
        self,
        html_path: Path,
        output_dir: Path,
        processed_assets: Dict[str, Any],
    ) -> Path:
        """
        图表嵌入由分析子智能体在生成报告时智能决定，此处不做硬编码补充。
        图表文件已由 process_assets 复制到 assets/，分析子智能体通过相对路径引用即可。
        """
        return html_path

    def _embed_charts_in_markdown(
        self,
        md_path: Path,
        output_dir: Path,
        processed_assets: Dict[str, Any],
    ) -> Path:
        """
        图表嵌入由分析子智能体在生成报告时智能决定，此处不做硬编码补充。
        """
        return md_path

    def _embed_eda_in_html(
        self,
        html_path: Path,
        output_dir: Path,
        eda_profile_path: Optional[Path] = None,
        eda_sweetviz_path: Optional[Path] = None,
    ) -> Path:
        """
        将 EDA 报告嵌入报告 HTML，形成统一入口。在 </body> 前插入 Data Overview 区块，
        含 iframe 嵌入 ydata/sweetviz 生成的 HTML。
        """
        eda_parts: List[Tuple[str, str]] = []
        for p, title in (
            (eda_profile_path, "ydata-profiling"),
            (eda_sweetviz_path, "Sweetviz"),
        ):
            if p and p.exists() and (p == output_dir or output_dir in p.parents):
                eda_parts.append((title, str(p.relative_to(output_dir))))

        if not eda_parts:
            return html_path

        html_content = html_path.read_text(encoding="utf-8")
        eda_section = self._build_eda_embed_section(eda_parts)
        if "</body>" in html_content:
            html_content = html_content.replace("</body>", f"{eda_section}\n</body>")
        else:
            html_content += eda_section
        html_path.write_text(html_content, encoding="utf-8")
        self.logger.info("将 EDA 报告嵌入报告 HTML")
        return html_path

    def _build_eda_embed_section(self, eda_parts: List[Tuple[str, str]]) -> str:
        """构建 EDA 报告嵌入区块 HTML。"""
        style = """
        .eda-embed-section { margin-top: 2em; padding: 1em; border-top: 1px solid #ddd; }
        .eda-embed-section h2 { font-size: 1.25em; margin-bottom: 0.5em; }
        .eda-embed-section iframe { width: 100%; height: 600px; border: 1px solid #ccc; margin-top: 0.5em; }
        """
        parts_html = ""
        for title, src in eda_parts:
            parts_html += f'<div class="eda-embed"><h3>{title}</h3><iframe src="{src}" title="{title}"></iframe></div>'
        return f"""
<section class="eda-embed-section" id="data-overview">
<style>{style}</style>
<h2>Data Overview (EDA)</h2>
<p>Exploratory data analysis profiles. Scroll within each frame to explore.</p>
{parts_html}
</section>"""

    async def _save_supporting_files(
        self,
        context: ExperimentContext,
        analysis_result: AnalysisResult,
        output_dir: Path,
    ) -> Dict[str, str]:
        """
        保存支持文件。

        Args:
            context: 实验上下文
            analysis_result: 分析结果
            output_dir: 输出目录

        Returns:
            文件路径字典
        """
        files = {}

        data_dir = output_dir / DIR_DATA
        data_dir.mkdir(exist_ok=True)
        result_file = data_dir / FILE_ANALYSIS_SUMMARY_JSON
        result_file.write_text(
            json.dumps(analysis_result.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        files["result_data"] = str(result_file)

        readme_file = output_dir / FILE_README_MD
        readme_content = f"""# Experiment Analysis Results

**Experiment ID:** {context.experiment_id}  
**Hypothesis ID:** {context.hypothesis_id}  
**Generated:** {analysis_result.generated_at.strftime("%Y-%m-%d %H:%M:%S")}

## Files

- `report.md` - Markdown report
- `report.html` - HTML report (unified: analysis + embedded EDA if available)
- `data/analysis_summary.json` - Analysis summary
- `data/eda_profile.html` - EDA (ydata-profiling), when generated
- `data/eda_sweetviz.html` - EDA (Sweetviz), when generated
"""
        readme_file.write_text(readme_content, encoding="utf-8")
        files["readme"] = str(readme_file)

        return files

    def _format_list(self, items: List[Any]) -> str:
        """
        格式化列表用于提示词。

        Args:
            items: 要格式化的项目列表

        Returns:
            格式化的 Markdown 列表字符串
        """
        return "\n".join([f"- {item}" for item in items]) if items else "None"

    def _format_list_truncated(
        self, items: List[Any], max_items: int = 10, max_item_len: int = 300
    ) -> str:
        """格式化列表并截断，控制 prompt 长度。"""
        if not items:
            return "None"
        truncated = [
            (str(i)[:max_item_len] + ("..." if len(str(i)) > max_item_len else ""))
            for i in items[:max_items]
        ]
        suffix = (
            f"\n... ({len(items) - max_items} more)" if len(items) > max_items else ""
        )
        return "\n".join([f"- {t}" for t in truncated]) + suffix

    def _truncate_text(self, text: str, max_len: int) -> str:
        """截断文本到指定长度。"""
        if not text:
            return ""
        s = str(text).strip()
        return s[:max_len] + ("..." if len(s) > max_len else "")

    def _get_status_message(self, status: str) -> str:
        """与 ExperimentStatus 枚举值一致。"""
        messages = {
            "successful": "Experiment completed successfully. Focus on positive outcomes.",
            "partial_success": "Partial success. Discuss achievements and limitations.",
            "failed": "Experiment did not meet criteria. Analyze what went wrong.",
            "interrupted": "Experiment was interrupted. Discuss partial results.",
        }
        return messages.get(
            status, "Status uncertain. Present findings with limitations."
        )
