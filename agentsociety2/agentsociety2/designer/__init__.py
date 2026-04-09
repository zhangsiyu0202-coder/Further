"""
实验设计器模块

提供实验设计、配置构建与验证、实验执行的入口。
"""

from .exp_designer import (
    ExperimentDesigner,
    ExperimentDesign,
    ExperimentGroup,
    ExperimentHypothesis,
    Experiment,
    Hypothesis,
)
from .config_builder import (
    ConfigBuilder,
    ExperimentConfig,
    load_design,
    build,
)
from .exp_pipeline import run_pipeline

__all__ = [
    # 设计
    "ExperimentDesigner",
    "ExperimentDesign",
    "ExperimentGroup",
    "ExperimentHypothesis",
    "Experiment",
    "Hypothesis",
    # 配置构建/验证
    "ConfigBuilder",
    "ExperimentConfig",
    "load_design",
    "build",
    # 一键串联
    "run_pipeline",
]

