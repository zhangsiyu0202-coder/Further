"""
分析模块通用工具。分析相关 LLM 输出统一使用 XML 格式解析；
为 generate_paper 工具提供 parse_llm_json_response。
"""

import re
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar, Type

import json_repair
from pydantic import BaseModel
from xenon import TrustLevel, repair_xml_safe

from .models import (
    DIR_ARTIFACTS,
    DIR_CHARTS,
    DIR_DATA,
    DIR_EXPERIMENT_PREFIX,
    DIR_HYPOTHESIS_PREFIX,
    DIR_REPORT_ASSETS,
    DIR_RUN,
    FILE_ANALYSIS_SUMMARY_JSON,
    FILE_PID,
    FILE_README_MD,
    FILE_REPORT_HTML,
    FILE_REPORT_MD,
    FILE_SQLITE,
    ExperimentPaths,
    PresentationPaths,
)

# 进度回调类型，供 service/agents 等使用
AnalysisProgressCallback = Optional[Callable[[str], Awaitable[None]]]


class XmlParseError(Exception):
    """LLM 返回的 XML 解析失败，供调用方捕获并触发 LLM 重试。"""

    def __init__(self, message: str, raw_content: str = ""):
        super().__init__(message)
        self.raw_content = raw_content


_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
T = TypeVar("T", bound=BaseModel)


def _sanitize_id(raw: str) -> str:
    """仅保留安全字符，防止路径穿越。"""
    s = (raw or "").strip()
    s = re.sub(r"[^a-zA-Z0-9_-]", "", s)
    return s or "unknown"


def experiment_paths(
    workspace_path: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> ExperimentPaths:
    """按约定聚合单实验路径；id 会做安全清洗。"""
    wp = Path(workspace_path).resolve()
    hid = _sanitize_id(hypothesis_id)
    eid = _sanitize_id(experiment_id)
    base = wp / f"{DIR_HYPOTHESIS_PREFIX}{hid}"
    exp = base / f"{DIR_EXPERIMENT_PREFIX}{eid}"
    run = exp / DIR_RUN
    return ExperimentPaths(
        hypothesis_base=base,
        experiment_path=exp,
        run_path=run,
        db_path=run / FILE_SQLITE,
        pid_path=run / FILE_PID,
        assets_path=run / DIR_ARTIFACTS,
    )


def presentation_paths(
    presentation_root: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> PresentationPaths:
    """单实验分析产物路径：output_dir、charts_dir、report_assets、报告与数据文件。"""
    root = Path(presentation_root).resolve()
    hid = _sanitize_id(hypothesis_id)
    eid = _sanitize_id(experiment_id)
    output_dir = (
        root / f"{DIR_HYPOTHESIS_PREFIX}{hid}" / f"{DIR_EXPERIMENT_PREFIX}{eid}"
    )
    charts_dir = output_dir / DIR_CHARTS
    report_assets_dir = output_dir / DIR_REPORT_ASSETS
    data_dir = output_dir / DIR_DATA
    return PresentationPaths(
        output_dir=output_dir,
        charts_dir=charts_dir,
        report_assets_dir=report_assets_dir,
        report_md=output_dir / FILE_REPORT_MD,
        report_html=output_dir / FILE_REPORT_HTML,
        result_json=data_dir / FILE_ANALYSIS_SUMMARY_JSON,
        readme=output_dir / FILE_README_MD,
    )


def get_analysis_skills() -> str:
    """从 skills/ 目录按文件名顺序加载所有 .md 技能文件。"""
    parts: List[str] = []
    if _SKILLS_DIR.exists():
        for p in sorted(_SKILLS_DIR.glob("*.md")):
            txt = p.read_text(encoding="utf-8").strip()
            if txt:
                parts.append(txt)
    return "\n\n---\n\n".join(parts).strip()


def _extract_xml_from_content(content: str) -> str:
    """从 LLM 输出中提取 XML。支持整段或 ```xml ... ``` 代码块。"""
    raw = (content or "").strip()
    if not raw:
        return ""
    if raw.startswith("<"):
        return raw
    if "```" in raw:
        for part in raw.split("```"):
            s = part.strip().lstrip("xml").strip()
            if s.startswith("<"):
                return s
    return raw


def _xml_element_to_value(el: ET.Element) -> Any:
    """将 XML 元素转为 Python 值。"""
    children = list(el)
    if not children:
        text = (el.text or "").strip()
        if text.lower() in ("true", "false"):
            return text.lower() == "true"
        return text
    # 有子元素：若全为同标签且多个，直接返回列表；否则返回 dict
    tags = [c.tag for c in children]
    if len(set(tags)) == 1 and len(children) > 1:
        return [_xml_element_to_value(c) for c in children]
    result: Dict[str, Any] = {}
    for c in children:
        val = _xml_element_to_value(c)
        if c.tag in result:
            if not isinstance(result[c.tag], list):
                result[c.tag] = [result[c.tag]]
            result[c.tag].append(val)
        else:
            result[c.tag] = val
    return result


def _parse_xml_to_root(xml_str: str) -> ET.Element:
    """解析 XML 字符串为 Element，失败时尝试用 xenon 修复后再解析。失败则抛出 XmlParseError。"""
    try:
        return ET.fromstring(xml_str)
    except ET.ParseError:
        try:
            repaired = repair_xml_safe(xml_str, trust=TrustLevel.UNTRUSTED)
            return ET.fromstring(repaired)
        except Exception as e:
            raise XmlParseError(
                f"XML parse failed after repair attempt: {e}", raw_content=xml_str
            ) from e


def parse_llm_xml_response(content: str, root_tag: str = "result") -> Dict[str, Any]:
    """
    解析 LLM 返回的 XML，转为 dict。
    解析失败抛出 XmlParseError，供调用方捕获并触发 LLM 重试。
    root_tag: 根标签名，用于提取顶层 dict（若根为 <judgment>，则取其子节点为 dict）。
    """
    xml_str = _extract_xml_from_content(content)
    if not xml_str:
        raise XmlParseError("No XML content extracted", raw_content=content)
    root = _parse_xml_to_root(xml_str)
    if root.tag == root_tag:
        return {c.tag: _xml_element_to_value(c) for c in root}
    # 根为 root_tag 的包装
    inner = root.find(root_tag)
    if inner is None:
        inner = root.find(f".//{root_tag}")
    if inner is not None:
        return {c.tag: _xml_element_to_value(c) for c in inner}
    return {c.tag: _xml_element_to_value(c) for c in root}


def parse_llm_xml_to_model(
    content: str, model_class: Type[T], root_tag: str = "result"
) -> T:
    """解析 LLM 返回的 XML 并验证为 Pydantic 模型。"""
    data = parse_llm_xml_response(content, root_tag)
    # 处理 item 包装：<insights><item>a</item></insights> -> insights: ["a"]
    for k, v in list(data.items()):
        if isinstance(v, dict) and "item" in v and len(v) == 1:
            items = v["item"]
            data[k] = items if isinstance(items, list) else [items]
    return model_class.model_validate(data)


def _take_json_string(content: str) -> str:
    """从约定格式中取出 JSON 字符串：整段即 JSON，或 ```json ... ``` 中唯一一段。"""
    raw = (content or "").strip()
    if not raw:
        return ""
    if raw.startswith("```"):
        parts = raw.split("```")
        for i, p in enumerate(parts):
            s = p.strip()
            if i == 0:
                s = s.lstrip("json").strip()
            if s and (s.startswith("{") or s.startswith("[")):
                return s
        return ""
    return raw


def parse_llm_json_response(content: str) -> Dict[str, Any]:
    """解析 LLM 返回的 JSON，约定为单段 JSON 或 ```json ... ```。返回 dict，失败返回 {}。"""
    json_str = _take_json_string(content)
    if not json_str:
        return {}
    data = json_repair.loads(json_str)
    return data if isinstance(data, dict) else {}


def parse_llm_report_response(content: str) -> Dict[str, str]:
    """
    解析报告类 LLM 输出，仅支持 XML 格式。
    格式：<report><markdown><![CDATA[...]]></markdown><html><![CDATA[...]]></html></report>
    CDATA 便于嵌入 HTML，无需转义。
    解析失败（含 xenon 修复后仍失败）则抛出 XmlParseError，由调用方触发 LLM 重试。
    """
    raw = (content or "").strip()
    if not raw:
        raise XmlParseError("Empty report content", raw_content=content)
    # 从代码块提取 XML（若 LLM 包在 ```xml 中）
    xml_str = raw
    if "```" in raw:
        for part in raw.split("```"):
            s = part.strip().lstrip("xml").strip()
            if "<report" in s or s.startswith("<report"):
                xml_str = s
                break
    root = _parse_xml_to_root(xml_str)
    md_el = root.find(".//markdown")
    if md_el is None:
        md_el = root.find("markdown")
    html_el = root.find(".//html")
    if html_el is None:
        html_el = root.find("html")
    md = "".join((md_el.itertext() if md_el is not None else []))
    html = "".join((html_el.itertext() if html_el is not None else []))
    return {"markdown": md.strip(), "html": html.strip()}


# ---------- 先读结构再处理：DB schema 与实验文件 ----------


def extract_database_schema(db_path: Path) -> Dict[str, Any]:
    """提取 SQLite 表结构；先查 sqlite_master 再按表取 PRAGMA。"""
    if not db_path or not db_path.exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = cursor.fetchall()
    schema = {}
    for (table_name,) in tables:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        schema[table_name] = [
            {
                "name": col[1],
                "type": col[2],
                "notnull": bool(col[3]),
                "pk": bool(col[5]),
            }
            for col in columns
        ]
    conn.close()
    return schema


def format_database_schema_markdown(
    schema: Dict[str, Any],
    include_row_counts: bool = False,
    db_path: Optional[Path] = None,
) -> str:
    """将 schema 格式化为 Markdown，可选行数。"""
    if not schema:
        return "Schema not available"
    lines = []
    for table_name, columns in schema.items():
        lines.append(f"### Table: `{table_name}`")
        lines.append(f"Columns: {', '.join([col['name'] for col in columns])}")
        for col in columns:
            pk_marker = " (PRIMARY KEY)" if col.get("pk") else ""
            lines.append(f"  - {col['name']} ({col['type']}){pk_marker}")
        lines.append("")
    if include_row_counts and db_path:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        lines.append("### Table Row Counts")
        for table_name in schema:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            lines.append(f"- `{table_name}`: {count} rows")
        conn.close()
    return "\n".join(lines)


def collect_experiment_files(db_path: Path) -> List[str]:
    """收集 run 目录下可供执行器使用的文件路径（含 sqlite.db、同级文件、run/artifacts）。"""
    if not db_path:
        return []
    files: List[str] = [str(db_path)]
    if not db_path.exists():
        return files
    run_dir = db_path.parent
    if run_dir.exists():
        for p in run_dir.glob("*"):
            if p.is_file() and p != db_path:
                files.append(str(p))
        artifacts_dir = run_dir / DIR_ARTIFACTS
        if artifacts_dir.exists():
            for p in artifacts_dir.rglob("*"):
                if p.is_file():
                    files.append(str(p))
    return files
