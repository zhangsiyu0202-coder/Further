"""
为实验数据库表生成概览报告并纳入分析上下文
"""

from pathlib import Path
from typing import Any, Optional, Tuple

from agentsociety2.logger import get_logger

from .models import AnalysisConfig

_logger = get_logger()


def _load_first_table_df(
    db_path: Path,
    table_name: Optional[str] = None,
    max_rows: int = 10_000,
) -> Tuple[Optional[str], Optional[Any]]:
    """获取首个有数据的表并读成 DataFrame。返回 (表名, df) 或 (None, None)。"""
    import sqlite3
    import pandas as pd

    if not db_path.exists():
        return None, None
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = [row[0] for row in cur.fetchall()]
        if not tables:
            return None, None
        if table_name and table_name in tables:
            name = table_name
        else:
            name = None
            for t in tables:
                cur.execute(f"SELECT COUNT(*) FROM [{t}]")
                if cur.fetchone()[0] > 0:
                    name = t
                    break
            if name is None:
                return None, None
        df = pd.read_sql_query(f"SELECT * FROM [{name}] LIMIT {max_rows}", conn)
    finally:
        conn.close()
    return (name, df) if not df.empty else (None, None)


def generate_quick_stats(
    db_path: Path,
    table_name: Optional[str] = None,
    max_rows: int = 5_000,
    config: Optional[AnalysisConfig] = None,
) -> Optional[str]:
    """
    使用 pandas describe() 生成数值列统计摘要，返回 Markdown 文本。
    """
    name, df = _load_first_table_df(db_path, table_name, max_rows)
    if name is None or df is None:
        return None
    try:
        desc = df.describe(include="all")
        try:
            md = desc.to_markdown()
        except Exception:
            md = desc.to_string()
        return f"Table: {name}\n\n```\n{md}\n```"
    except Exception as e:
        _logger.debug("为 %s 生成快速统计摘要失败: %s", db_path, e)
        return None


def generate_eda_profile(
    db_path: Path,
    output_dir: Path,
    table_name: Optional[str] = None,
    max_rows: int = 10_000,
    config: Optional[AnalysisConfig] = None,
) -> Optional[Path]:
    """
    对 SQLite 中单表生成 EDA 概览 HTML。

    Args:
        db_path: 数据库路径
        output_dir: 输出目录
        table_name: 指定表名；不传则取首个有数据的表
        max_rows: 最大行数，避免大表过慢

    Returns:
        生成的 HTML 路径，或 None（失败）
    """
    name, df = _load_first_table_df(db_path, table_name, max_rows)
    if name is None or df is None:
        return None

    from ydata_profiling import ProfileReport

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / "eda_profile.html"
    try:
        profile = ProfileReport(df, title=f"EDA: {name}", minimal=True)
        profile.to_file(str(out_file))
        return out_file
    except Exception as e:
        _logger.debug("为 %s 生成EDA概览HTML失败: %s", db_path, e)
        return None


def generate_sweetviz_profile(
    db_path: Path,
    output_dir: Path,
    table_name: Optional[str] = None,
    max_rows: int = 10_000,
    config: Optional[AnalysisConfig] = None,
) -> Optional[Path]:
    """
    使用 Sweetviz 对 SQLite 单表生成 EDA HTML。
    与 ydata-profiling 互补：Sweetviz 侧重相关性、目标变量分析，界面更轻量。

    Args:
        db_path: 数据库路径
        output_dir: 输出目录
        table_name: 指定表名；不传则取首个有数据的表
        max_rows: 最大行数

    Returns:
        生成的 HTML 路径，或 None（失败）
    """
    name, df = _load_first_table_df(db_path, table_name, max_rows)
    if name is None or df is None:
        return None

    import sweetviz as sv

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / "eda_sweetviz.html"
    try:
        report = sv.analyze(df)
        report.show_html(str(out_file), open_browser=False)
        return out_file if out_file.exists() else None
    except Exception as e:
        _logger.debug("为 %s 生成SweetvizEDA概览HTML失败: %s", db_path, e)
        return None
