"""
Agent信息文件处理器。

将输入的各种格式的Agent信息文件转换为标准的Agent信息池。
信息池格式：
[
    {"profile": {"custom_fields": {...}}},
    ...
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentsociety2.code_executor.api import CodeExecutorAPI
from agentsociety2.code_executor.models import CodeGenerationRequest
from agentsociety2.logger import get_logger
from .field_metadata import FieldMetadataSchema
from .utils import validate_agent_args

logger = get_logger()

PROMPT_PROCESS_AGENT_FILE = """
You are a data processing expert. Convert an input file (CSV, Excel, JSON) into a standardized JSON format.

File path: {file_path}
File preview (first {preview_lines} lines/rows):
{file_preview}

Processing approach (ReAct - multiple steps):
1. Explore: Read first 20 rows of each sheet to understand structure
2. Identify mappings: Find field name mappings and value mappings from metadata sheets
3. Process data: Apply mappings and process data sheet
4. Save: Output standardized JSON format

CRITICAL: File may be VERY LARGE - process in chunks, don't load everything at once.

For Excel files with multiple sheets (ALL sheets have headers in first row):
- Data sheet: Usually largest sheet. First row = headers, subsequent rows = agents.
- Mapping sheets: Identify by structure (few rows, 2-3 columns). Extract mappings.

Output schema (save as UTF-8 JSON to {output_filename}):
{{
  "metadata": {{
    "total_agents": <number>,
    "fields": [{{"name": "<original_field_name>", "type": "...", "description": "", "value_mappings": {{}}}}],
    "field_name_mapping": {{"<original>": "<meaningful>"}},
    "created_at": "<timestamp>"
  }},
  "agents": [{{
    "profile": {{
      "custom_fields": {{
        "<original_field_name>": <original_value>
      }}
    }}
  }}]
}}

CRITICAL REQUIREMENTS:
1. Field name mapping:
   - Read mapping from sheet and store in metadata.field_name_mapping
   - Keep original column names in Agent data (DO NOT rename columns)
   - Store mapping for filtering reference
2. Value mapping:
   - Format: value -> meaning
   - Store in metadata only. Keep original values in agent data
3. Header row: First row = headers, NOT agent data. Start from row 2.
4. Process ALL rows, not just first 1000.
5. YOU MUST NOT introduce extra nesting levels or keys outside the required schema.
6. Only use mappings found in file, do NOT guess or invent.

Step 1: Explore file structure
- List all sheets, read first 20 rows of each
- Identify data sheet: Usually largest sheet with many rows
- Identify mapping sheets: Look for sheets with 2-3 columns and few rows

Step 2: Extract mappings
- Field name mapping sheet: Read with header=0, Column 0 = generic name, Column 1 = meaningful name
  * Process ALL rows, skip header row
  * Build field_name_mapping: generic_name -> meaningful_name
- Value mapping sheet: Read with header=0, Column 0 = field name, Column 1 = value, Column 2 = meaning
  * Process ALL rows, skip header row
  * Build value_mappings: field_name -> dict(value -> meaning)
  * Group by field name

Step 3: Process data sheet
- Read with header=0: df_data = pd.read_excel(file_path, sheet_name=data_sheet_name)
  * df_data.columns will be original names like VAR00004, VAR00003, Q5, etc.
- CRITICAL: Keep original column names - DO NOT rename columns
  * Use original column names (VAR00004, Q5, etc.) in Agent data
  * Store field_name_mapping in metadata for filtering reference
- For large files: Use nrows in loop (pandas.read_excel() doesn't support chunksize)
- Process ALL rows, apply make_json_serializable() to each value

Step 4: Build output
- For each row: Create agent with profile.custom_fields, use ORIGINAL field names, preserve original values
- Build metadata:
  * total_agents: len(df_data)
  * fields: For each column, create field entry with name (original), type, value_mappings (if available)
  * field_name_mapping: Store the mapping (original -> meaningful)
  * created_at: timestamp
- CRITICAL:
  * Agent data uses original field names in custom_fields
  * metadata.fields[].name uses original field names
  * metadata.field_name_mapping stores mapping for filtering
- Save as UTF-8 JSON to {output_filename}

For CSV: Use pandas.read_csv() with chunksize for large files.
For JSON: Read and parse, convert to agent format.

Helper function for JSON serialization (MUST include):
```python
def make_json_serializable(obj):
    import pandas as pd
    import numpy as np
    from datetime import datetime, date

    # Handle collections first (before checking NaN on arrays)
    if isinstance(obj, dict):
        return dict((k, make_json_serializable(v)) for k, v in obj.items())
    if isinstance(obj, (list, tuple, pd.Series, np.ndarray)):
        if isinstance(obj, (pd.Series, np.ndarray)):
            obj = obj.tolist()
        return [make_json_serializable(item) for item in obj]

    # Handle NaN/NaT (only for scalar values, not arrays)
    try:
        if pd.isna(obj):
            return None
    except (ValueError, TypeError):
        # pd.isna() may fail for some types, continue
        pass

    # Handle Timestamp/DateTime
    if isinstance(obj, pd.Timestamp):
        return obj.strftime('%Y-%m-%d') if hasattr(obj, 'strftime') else str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.strftime('%Y-%m-%d') if hasattr(obj, 'strftime') else str(obj)

    # Handle numpy types
    if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)

    # Handle datetime objects
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()

    # Return as-is if already serializable
    return obj
```

Apply make_json_serializable() to every value before saving.

Type handling: Convert pandas Timestamp/DateTime to strings, NaN/NaT to None, numpy types to native Python types.

Required libraries: pandas, openpyxl (for .xlsx), xlrd (for .xls)

Command-line: python main.py --input "{input_filename}" --output "{output_filename}"
Use argparse with --input and --output arguments.

Handle errors gracefully, raise clear exceptions if format unsupported or data sheet not found.
"""


class AgentFileProcessor:
    """Agent information file processor."""

    def __init__(self):
        """Initialize Agent file processor with fixed default LLM config."""

        self._code_executor = CodeExecutorAPI()
        logger.info("AgentFileProcessor initialized")

    async def process_file(
        self,
        file_path: str | Path,
        agent_type: Optional[str] = None,
        additional_context: Optional[str] = None,
        field_metadata: Optional[FieldMetadataSchema] = None,
    ) -> List[Dict[str, Any]]:
        """
        Process Agent information file and return standard agent_args list.

        Args:
            file_path: 输入文件路径
            agent_type: Agent类型（可选）
            additional_context: 额外上下文（可选）
            field_metadata: 字段元数据（可选，如果提供可以更精确地处理文件）

        Returns:
            Standard agent_args list with format:
            [
                {"profile": {"custom_fields": {...}}},
                ...
            ]

        Raises:
            FileNotFoundError: File does not exist
            ValueError: File processing failed or format incorrect
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Processing Agent information file: {file_path}")

        # 读取文件预览（用于LLM判断文件类型）
        preview_lines = 50  # 预览前50行
        file_preview = self._read_file_preview(file_path, preview_lines)

        context_parts = []
        if agent_type:
            context_parts.append(f"Agent type: {agent_type}")
        if additional_context:
            context_parts.append(f"Additional context: {additional_context}")

        # 如果有字段元数据，添加到上下文中
        if field_metadata:
            metadata_info = []
            for field in field_metadata.fields:
                field_info = f"- {field.name} ({field.label}): {field.field_type.value}"
                if field.options:
                    options_str = ", ".join(
                        [str(opt.value) for opt in field.options[:10]]
                    )
                    if len(field.options) > 10:
                        options_str += f", ... ({len(field.options)} total)"
                    field_info += f" - Options: {options_str}"
                elif field.min_value is not None or field.max_value is not None:
                    range_str = f"[{field.min_value or '?'}, {field.max_value or '?'}]"
                    field_info += f" - Range: {range_str}"
                metadata_info.append(field_info)
            context_parts.append("Field metadata:")
            context_parts.extend(metadata_info)
            context_parts.append("")
            context_parts.append(
                "IMPORTANT: Use the field names and value options from the metadata above when converting data."
            )

        additional_context_str = "\n".join(context_parts) if context_parts else None
        input_filename = file_path.name
        output_filename = f"{file_path.stem}_processed.json"

        prompt = PROMPT_PROCESS_AGENT_FILE.format(
            file_path=str(file_path),
            file_preview=file_preview,
            input_filename=input_filename,
            output_filename=output_filename,
            preview_lines=preview_lines,
        )

        request = CodeGenerationRequest(
            description=prompt,
            input_files=None,
            additional_context=additional_context_str,
        )

        logger.info(
            "Generating processing code and executing in Docker with input file mounted..."
        )
        response = await self._code_executor.generate_and_execute(
            request,
            extra_files=[str(file_path)],
            program_args=[
                "--input",
                input_filename,
                "--output",
                output_filename,
            ],
        )

        if not response.execution_result or not response.execution_result.success:
            error_msg = (
                response.execution_result.stderr
                if response.execution_result
                else "Execution failed"
            )
            raise ValueError(f"Code execution failed: {error_msg}")

        artifacts_path = (
            Path(response.execution_result.artifacts_path)
            if response.execution_result and response.execution_result.artifacts_path
            else None
        )

        if not artifacts_path or not artifacts_path.exists():
            raise ValueError(
                "Code execution succeeded but no artifacts_path found; "
                "expected the processed JSON file in artifacts."
            )

        processed_file_in_artifacts = artifacts_path / output_filename
        if not processed_file_in_artifacts.exists():
            raise ValueError(
                f"Processed JSON file not found in artifacts: {processed_file_in_artifacts}"
            )

        with open(processed_file_in_artifacts, "r", encoding="utf-8") as f:
            pool_data = json.load(f)

        # 统一格式：必须是包含metadata和agents的对象
        if isinstance(pool_data, dict) and "agents" in pool_data:
            # 新格式：包含metadata
            agent_args = pool_data["agents"]
            if "metadata" not in pool_data:
                # 如果没有metadata，自动生成
                if agent_args:
                    sample_fields = list(
                        agent_args[0].get("profile", {}).get("custom_fields", {}).keys()
                    )
                    pool_data["metadata"] = {
                        "total_agents": len(agent_args),
                        "fields": [{"name": f, "type": "str"} for f in sample_fields],
                        "created_at": None,
                    }
        elif isinstance(pool_data, list):
            # 旧格式：只有数组，转换为新格式
            agent_args = pool_data
            if agent_args:
                sample_fields = list(
                    agent_args[0].get("profile", {}).get("custom_fields", {}).keys()
                )
                pool_data = {
                    "metadata": {
                        "total_agents": len(agent_args),
                        "fields": [{"name": f, "type": "str"} for f in sample_fields],
                        "created_at": None,
                    },
                    "agents": agent_args,
                }
            else:
                pool_data = {
                    "metadata": {"total_agents": 0, "fields": [], "created_at": None},
                    "agents": [],
                }
        else:
            raise ValueError(
                f"Processed JSON must be a dict with 'agents' key or a list, got: {type(pool_data)}"
            )

        validate_agent_args(agent_args)
        logger.info(
            f"Successfully processed file, extracted {len(agent_args)} Agent configurations"
        )
        if pool_data.get("metadata", {}).get("fields"):
            field_names = [f["name"] for f in pool_data["metadata"]["fields"]]
            logger.info(
                f"Fields: {', '.join(field_names[:10])}{'...' if len(field_names) > 10 else ''}"
            )

        output_file = file_path.parent / output_filename
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(pool_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Processed agent pool saved to file: {output_file}")

        return agent_args

    def _read_file_preview(self, file_path: Path, max_lines: int = 50) -> str:
        """
        读取文件预览（前若干行）

        Args:
            file_path: 文件路径
            max_lines: 最大行数

        Returns:
            文件预览文本
        """
        suffix = file_path.suffix.lower()

        if suffix in [".xlsx", ".xls"]:
            try:
                import pandas as pd  # type: ignore
            except ImportError:
                return f"Excel file detected (.{suffix}), but pandas is not installed. Please install: pip install pandas openpyxl"

            excel_file = pd.ExcelFile(file_path)
            sheet_names = excel_file.sheet_names
            preview = f"Excel file detected. Total sheets: {len(sheet_names)}\n"
            preview += f"Sheet names: {sheet_names}\n\n"

            for i, sheet_name in enumerate(sheet_names[:5]):
                df = pd.read_excel(file_path, nrows=max_lines, sheet_name=sheet_name)
                preview += f"--- Sheet {i+1}: '{sheet_name}' (shape: {df.shape[0]} rows x {df.shape[1]} cols, showing first {min(max_lines, len(df))} rows) ---\n"
                preview += df.to_string() + "\n\n"

            if len(sheet_names) > 5:
                preview += f"... and {len(sheet_names) - 5} more sheets\n"

            return preview

        elif suffix == ".csv":
            try:
                import pandas as pd  # type: ignore
            except ImportError:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [line for i, line in enumerate(f) if i < max_lines]
                return "".join(lines)

            for encoding in ["utf-8", "gbk"]:
                df = pd.read_csv(file_path, nrows=max_lines, encoding=encoding)
                return f"CSV file detected ({encoding} encoding). Preview:\n\n{df.to_string()}"

            return "CSV file detected, but failed to read with utf-8 or gbk encoding"

        else:
            # 其他文件：按文本读取
            for encoding in ["utf-8", "gbk", "latin-1", "cp1252"]:
                with open(file_path, "r", encoding=encoding, errors="ignore") as f:
                    lines = [line for i, line in enumerate(f) if i < max_lines]
                    return (
                        f"Text file detected (encoding: {encoding}). Preview:\n\n"
                        + "".join(lines)
                    )

            # 如果所有编码都失败，尝试二进制读取前几KB
            with open(file_path, "rb") as f:
                content = f.read(8192)
                return f"Binary file detected. First 8KB (hex preview):\n{content[:200]}..."

    async def close(self) -> None:
        """Close processor and cleanup resources."""
        await self._code_executor.close()
        logger.info("AgentFileProcessor closed")
