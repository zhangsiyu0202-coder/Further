"""
标准化实验分析数据模型与统一配置。
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


DIR_HYPOTHESIS_PREFIX = "hypothesis_"
DIR_EXPERIMENT_PREFIX = "experiment_"
DIR_RUN = "run"
DIR_ARTIFACTS = "artifacts"  # run/artifacts: 实验执行产物
DIR_PRESENTATION = "presentation"
DIR_SYNTHESIS = "synthesis"
DIR_DATA = "data"  # presentation 下 data: 分析子智能体写入的分析数据
DIR_CHARTS = "charts"  # presentation 下 charts: DataExplorer 写图目录
DIR_REPORT_ASSETS = "assets"  # presentation 下 assets: 报告嵌入资源（复制自 charts + run/artifacts），包括图表、报告、分析数据等
FILE_SQLITE = "sqlite.db"
FILE_PID = "pid.json"
FILE_HYPOTHESIS_MD = "HYPOTHESIS.md"
FILE_EXPERIMENT_MD = "EXPERIMENT.md"
FILE_REPORT_MD = "report.md"
FILE_REPORT_HTML = "report.html"
FILE_ANALYSIS_SUMMARY_JSON = "analysis_summary.json"
FILE_README_MD = "README.md"
FILE_SYNTHESIS_REPORT_PREFIX = "synthesis_report_"

# Language suffixes for bilingual reports
LANG_ZH = "zh"
LANG_EN = "en"

# Bilingual report file patterns
FILE_REPORT_ZH_MD = f"report_{LANG_ZH}.md"
FILE_REPORT_ZH_HTML = f"report_{LANG_ZH}.html"
FILE_REPORT_EN_MD = f"report_{LANG_EN}.md"
FILE_REPORT_EN_HTML = f"report_{LANG_EN}.html"
FILE_SYNTHESIS_REPORT_ZH_SUFFIX = f"_{LANG_ZH}"
FILE_SYNTHESIS_REPORT_EN_SUFFIX = f"_{LANG_EN}"

SUPPORTED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
SUPPORTED_ASSET_FORMATS = SUPPORTED_IMAGE_FORMATS | {".pdf"}


class ExperimentPaths(BaseModel):
    """单实验在 workspace 下的约定路径（只读，由 utils.experiment_paths 构建）。"""

    hypothesis_base: Path = Field(..., description="hypothesis_<id> directory")
    experiment_path: Path = Field(..., description="experiment_<id> directory")
    run_path: Path = Field(..., description="run directory")
    db_path: Path = Field(..., description="sqlite.db path")
    pid_path: Path = Field(..., description="pid.json path")
    assets_path: Path = Field(..., description="run/artifacts directory")

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PresentationPaths(BaseModel):
    """
    单实验分析产物的输出路径（presentation 下，由 utils.presentation_paths 构建）。

    生成产物布局：
    - output_dir/
      - report.md, report.html, README.md
      - data/analysis_summary.json
      - charts/  （DataExplorer 写图目录，再被复制到 assets）
      - assets/  （报告引用的图片，DIR_REPORT_ASSETS）
    """

    output_dir: Path = Field(
        ..., description="presentation/hypothesis_<id>/experiment_<id>"
    )
    charts_dir: Path = Field(
        ..., description="Charts output directory (DataExplorer writes here)"
    )
    report_assets_dir: Path = Field(
        ..., description="Report assets directory (assets/, referenced by report)"
    )
    report_md: Path = Field(..., description="Markdown report path")
    report_html: Path = Field(..., description="HTML report path")
    result_json: Path = Field(..., description="analysis_summary.json path")
    readme: Path = Field(..., description="README.md path")

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ExperimentStatus(str, Enum):
    """实验执行的状态"""

    SUCCESSFUL = "successful"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class ExperimentDesign(BaseModel):
    """实验设计"""

    hypothesis: str = Field(..., description="Primary hypothesis being tested")
    objectives: List[str] = Field(
        default_factory=list, description="Experiment objectives"
    )
    variables: Dict[str, Any] = Field(default_factory=dict, description="Variables")
    methodology: str = Field(default="", description="Experimental methodology")
    success_criteria: List[str] = Field(
        default_factory=list, description="Success criteria"
    )

    hypothesis_markdown: Optional[str] = Field(
        default=None, description="Raw content of HYPOTHESIS.md if available"
    )
    experiment_markdown: Optional[str] = Field(
        default=None, description="Raw content of EXPERIMENT.md if available"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ExperimentContext(BaseModel):
    """完整实验状态"""

    experiment_id: str = Field(..., description="Experiment identifier")
    hypothesis_id: str = Field(..., description="Hypothesis identifier")
    design: ExperimentDesign = Field(..., description="Experiment design")

    duration_seconds: Optional[float] = Field(None, description="Duration in seconds")
    execution_status: ExperimentStatus = Field(
        default=ExperimentStatus.UNKNOWN, description="Execution status"
    )
    completion_percentage: float = Field(
        default=0.0, description="Completion percentage"
    )
    error_messages: List[str] = Field(
        default_factory=list, description="Error messages"
    )


class AnalysisResult(BaseModel):
    """实验分析结果"""

    experiment_id: str = Field(..., description="Experiment identifier")
    hypothesis_id: str = Field(..., description="Hypothesis identifier")

    insights: List[Any] = Field(default_factory=list, description="Generated insights")
    findings: List[Any] = Field(default_factory=list, description="Key findings")
    conclusions: Any = Field(default="", description="Conclusions")
    recommendations: List[Any] = Field(
        default_factory=list, description="Recommendations"
    )

    generated_at: datetime = Field(
        default_factory=datetime.now, description="Generation time"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ReportContent(BaseModel):
    """报告内容"""

    title: str = Field(..., description="Report title")
    subtitle: str = Field(default="", description="Report subtitle")
    format_preference: str = Field(
        default="markdown", description="Preferred format: markdown, html, or both"
    )
    full_content_markdown: Optional[str] = Field(
        default=None, description="Complete markdown report content"
    )
    full_content_html: Optional[str] = Field(
        default=None, description="Complete HTML report content"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ReportAsset(BaseModel):
    """报告所需要的其他资源"""

    asset_id: str = Field(..., description="Asset identifier")
    asset_type: str = Field(..., description="Asset type")
    title: str = Field(..., description="Asset title")
    description: str = Field(default="", description="Asset description")

    file_path: str = Field(..., description="File path")
    embedded_content: Optional[str] = Field(None, description="Base64 content")
    file_size: int = Field(default=0, description="File size in bytes")

    created_at: datetime = Field(
        default_factory=datetime.now, description="Creation time"
    )
    dimensions: Optional[Dict[str, int]] = Field(None, description="Dimensions")

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AnalysisConfig(BaseModel):
    """分析子智能体统一配置，各组件均从此读取。"""

    workspace_path: str = Field(..., description="Workspace path")
    max_analysis_retries: int = Field(
        5,
        ge=1,
        le=20,
        description="Max retries for analysis/report generation",
    )
    max_strategy_retries: int = Field(
        3,
        ge=1,
        le=10,
        description="Max retries for analysis strategy judgment",
    )
    max_visualization_retries: int = Field(
        3,
        ge=1,
        le=10,
        description="Max retries for visualization judgment",
    )
    max_tool_iterations: int = Field(
        3,
        ge=1,
        le=10,
        description="Max iterations for tool execution loop",
    )
    max_synthesis_report_retries: int = Field(
        3,
        ge=1,
        le=10,
        description="Max retries for synthesis report generation",
    )
    max_code_gen_retries: int = Field(
        5,
        ge=1,
        le=20,
        description="Max retries for code generation in tool executor",
    )
    completion_success_threshold: float = Field(
        70.0,
        ge=0.0,
        le=100.0,
        description="Completion percentage threshold for successful experiment",
    )
    temperature: float = Field(
        0.7,
        ge=0.0,
        le=2.0,
        description="LLM temperature",
    )
    code_execution_timeout: int = Field(
        600,
        ge=60,
        le=3600,
        description="Code executor timeout in seconds",
    )
    synthesis_output_dir_name: str = Field(
        default=DIR_SYNTHESIS,
        description="Subdir under workspace for synthesis reports",
    )
    llm_profile_default: str = Field(
        default="default",
        description="LLM profile for insight, report, strategy (non-code)",
    )
    llm_profile_coder: str = Field(
        default="coder",
        description="LLM profile for code generation",
    )

    @field_validator("workspace_path")
    @classmethod
    def validate_workspace_path(cls, v):
        path = Path(v)
        if not path.exists():
            raise ValueError(f"Workspace path does not exist: {v}")
        return str(path.absolute())


class HypothesisSummary(BaseModel):
    """跨多个实验的分析结果"""

    hypothesis_id: str = Field(..., description="Hypothesis identifier")
    hypothesis_text: str = Field(..., description="Hypothesis text")

    experiment_count: int = Field(default=0, description="Number of experiments")
    successful_experiments: int = Field(
        default=0, description="Number of successful experiments"
    )
    total_completion: float = Field(
        default=0.0, description="Average completion percentage"
    )

    key_insights: List[str] = Field(default_factory=list, description="Key insights")
    main_findings: List[str] = Field(default_factory=list, description="Main findings")
    experiment_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Analysis results for each experiment",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ExperimentSynthesis(BaseModel):
    """多假设/多实验的综合结果。"""

    synthesis_id: str = Field(..., description="Synthesis identifier")
    workspace_path: str = Field(..., description="Workspace path")
    synthesis_timestamp: datetime = Field(
        default_factory=datetime.now, description="Analysis timestamp"
    )

    hypothesis_summaries: List[HypothesisSummary] = Field(
        default_factory=list,
        description="Summary information for each hypothesis",
    )

    synthesis_strategy: str = Field(
        default="", description="Analysis strategy decided by LLM"
    )
    cross_hypothesis_analysis: str = Field(
        default="", description="Cross-hypothesis analysis"
    )
    comparative_insights: List[str] = Field(
        default_factory=list, description="Comparative insights"
    )
    unified_conclusions: str = Field(default="", description="Unified conclusions")
    recommendations: List[str] = Field(
        default_factory=list, description="Comprehensive recommendations"
    )

    best_hypothesis: Optional[str] = Field(
        None, description="Best hypothesis identifier"
    )
    best_hypothesis_reason: str = Field(
        default="", description="Reason for best hypothesis"
    )
    overall_assessment: str = Field(default="", description="Overall assessment")

    synthesis_report_path: Optional[str] = Field(
        None, description="Synthesis report Markdown file path"
    )
    synthesis_report_html_path: Optional[str] = Field(
        None, description="Synthesis report HTML file path"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)
