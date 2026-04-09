"""
实验数据API

提供实验结果数据的查询接口，支持：
- 获取实验时间线
- 获取agent状态
- 获取实验指标
- 兼容V1前端API格式

关联文件：
- @extension/src/replayWebviewProvider.ts - 前端Replay Webview（调用此API）

API端点：
- GET /api/v1/experiments/{hypothesis_id}/{experiment_id}/info - 实验信息
- GET /api/v1/experiments/{hypothesis_id}/{experiment_id}/timeline - 时间线
- GET /api/v1/experiments/{hypothesis_id}/{experiment_id}/agents/* - Agent数据
- GET /api/v1/experiments/{hypothesis_id}/{experiment_id}/state - 最新状态
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from agentsociety2.logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/experiments", tags=["experiments"])


# ============================================================================
# Pydantic 模型
# ============================================================================


class TimePoint(BaseModel):
    """时间点"""

    day: int
    t: int  # 当天秒数 (0-86400)
    timestamp: str


class AgentProfile(BaseModel):
    """Agent配置文件"""

    id: int
    name: Optional[str] = None
    profile: Optional[Dict[str, Any]] = None


class AgentStatus(BaseModel):
    """Agent状态"""

    id: int
    day: int
    t: int
    lng: Optional[float] = None
    lat: Optional[float] = None
    parent_id: Optional[int] = None
    action: Optional[str] = None
    status: Optional[Dict[str, Any]] = None


class ExperimentInfo(BaseModel):
    """实验信息"""

    experiment_id: str
    hypothesis_id: str
    status: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    agent_count: int
    step_count: int


class StepExecution(BaseModel):
    """步骤执行记录"""

    id: int
    step_index: int
    step_type: str
    step_config: Dict[str, Any]
    start_time: str
    end_time: Optional[str] = None
    success: bool
    result: Optional[str] = None


# ============================================================================
# 辅助函数
# ============================================================================


def _get_experiment_path(
    workspace_path: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> Path:
    """获取实验目录路径"""
    return (
        workspace_path / f"hypothesis_{hypothesis_id}" / f"experiment_{experiment_id}"
    )


def _get_db_connection(db_path: Path) -> sqlite3.Connection:
    """获取数据库连接"""
    if not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"未找到数据库：{db_path}。该实验可能尚未运行。",
        )
    return sqlite3.connect(db_path)


def _parse_state_data(state_data_json: str) -> Dict[str, Any]:
    """解析状态数据JSON"""
    try:
        return json.loads(state_data_json)
    except json.JSONDecodeError:
        return {}


def _datetime_to_day_t(dt: datetime, start_t: datetime) -> tuple[int, int]:
    """将datetime转换为(day, t)格式"""
    delta = dt - start_t
    day = delta.days
    t = int(delta.seconds)
    return day, t


# ============================================================================
# API 端点
# ============================================================================


@router.get("/{hypothesis_id}/{experiment_id}/info")
async def get_experiment_info(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="工作区目录路径"),
) -> ExperimentInfo:
    """获取实验基本信息"""
    workspace = Path(workspace_path)
    exp_path = _get_experiment_path(workspace, hypothesis_id, experiment_id)

    if not exp_path.exists():
        raise HTTPException(status_code=404, detail="未找到实验")

    run_dir = exp_path / "run"
    pid_file = run_dir / "pid.json"
    db_file = run_dir / "sqlite.db"

    # 读取状态
    status = "not_started"
    start_time = None
    end_time = None

    if pid_file.exists():
        try:
            pid_data = json.loads(pid_file.read_text(encoding="utf-8"))
            status = pid_data.get("status", "unknown")
            start_time = pid_data.get("start_time")
            end_time = pid_data.get("end_time")
        except Exception as e:
            logger.warning(f"读取 pid.json 失败：{e}")

    # 获取agent和step数量
    agent_count = 0
    step_count = 0

    if db_file.exists():
        try:
            conn = _get_db_connection(db_file)
            cursor = conn.cursor()

            # 从最新的state_data获取agent数量
            cursor.execute("""
                SELECT state_data FROM experiment_state
                ORDER BY id DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row[0]:
                state_data = _parse_state_data(row[0])
                agents = state_data.get("agents", [])
                agent_count = len(agents)

            # 获取step数量
            cursor.execute("SELECT COUNT(*) FROM step_executions")
            row = cursor.fetchone()
            step_count = row[0] if row else 0

            conn.close()
        except Exception as e:
            logger.warning(f"查询数据库失败：{e}")

    return ExperimentInfo(
        experiment_id=experiment_id,
        hypothesis_id=hypothesis_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        agent_count=agent_count,
        step_count=step_count,
    )


@router.get("/{hypothesis_id}/{experiment_id}/timeline")
async def get_timeline(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="工作区目录路径"),
) -> List[TimePoint]:
    """获取实验时间线（所有记录的时间点）"""
    workspace = Path(workspace_path)
    exp_path = _get_experiment_path(workspace, hypothesis_id, experiment_id)
    db_file = exp_path / "run" / "sqlite.db"

    conn = _get_db_connection(db_file)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, current_time, step_count FROM experiment_state
        ORDER BY id ASC
    """)

    timeline = []
    first_time = None

    for row in cursor.fetchall():
        state_id, current_time_str, step_count = row
        if current_time_str:
            try:
                current_time = datetime.fromisoformat(current_time_str)
                if first_time is None:
                    first_time = current_time

                day, t = _datetime_to_day_t(current_time, first_time)
                timeline.append(
                    TimePoint(
                        day=day,
                        t=t,
                        timestamp=current_time_str,
                    )
                )
            except ValueError:
                continue

    conn.close()
    return timeline


@router.get("/{hypothesis_id}/{experiment_id}/agents")
async def get_agents(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> List[AgentProfile]:
    """获取所有agent的配置信息"""
    workspace = Path(workspace_path)
    exp_path = _get_experiment_path(workspace, hypothesis_id, experiment_id)
    db_file = exp_path / "run" / "sqlite.db"

    conn = _get_db_connection(db_file)
    cursor = conn.cursor()

    # 获取最新的状态数据
    cursor.execute("""
        SELECT state_data FROM experiment_state
        ORDER BY id DESC LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0]:
        return []

    state_data = _parse_state_data(row[0])
    agents_data = state_data.get("agents", [])

    agents = []
    for agent_data in agents_data:
        dump_data = agent_data.get("dump", {})
        profile = dump_data.get("profile", {})

        agents.append(
            AgentProfile(
                id=agent_data.get("id", 0),
                name=profile.get("name", f"Agent_{agent_data.get('id', 0)}"),
                profile=profile,
            )
        )

    return agents


@router.get("/{hypothesis_id}/{experiment_id}/agents/{agent_id}/status")
async def get_agent_status(
    hypothesis_id: str,
    experiment_id: str,
    agent_id: int,
    workspace_path: str = Query(..., description="Workspace directory path"),
    day: Optional[int] = Query(None, description="Day number (0-indexed)"),
    t: Optional[int] = Query(None, description="Time within day (seconds, 0-86400)"),
) -> List[AgentStatus]:
    """
    获取指定agent的状态历史

    如果指定day和t，返回该时刻的状态；
    否则返回所有状态历史。
    """
    workspace = Path(workspace_path)
    exp_path = _get_experiment_path(workspace, hypothesis_id, experiment_id)
    db_file = exp_path / "run" / "sqlite.db"

    conn = _get_db_connection(db_file)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT current_time, state_data FROM experiment_state
        ORDER BY id ASC
    """)

    statuses = []
    first_time = None

    for row in cursor.fetchall():
        current_time_str, state_data_json = row
        if not current_time_str or not state_data_json:
            continue

        try:
            current_time = datetime.fromisoformat(current_time_str)
            if first_time is None:
                first_time = current_time

            current_day, current_t = _datetime_to_day_t(current_time, first_time)

            # 如果指定了时间，只返回匹配的状态
            if day is not None and t is not None:
                if current_day != day or abs(current_t - t) > 60:  # 允许1分钟误差
                    continue

            state_data = _parse_state_data(state_data_json)
            agents_data = state_data.get("agents", [])

            for agent_data in agents_data:
                if agent_data.get("id") == agent_id:
                    dump_data = agent_data.get("dump", {})

                    # 提取位置信息（如果有）
                    position = dump_data.get("position", {})
                    lng = position.get("lng") or position.get("longitude")
                    lat = position.get("lat") or position.get("latitude")

                    statuses.append(
                        AgentStatus(
                            id=agent_id,
                            day=current_day,
                            t=current_t,
                            lng=lng,
                            lat=lat,
                            parent_id=dump_data.get("parent_id"),
                            action=dump_data.get("current_action"),
                            status=dump_data.get("status", {}),
                        )
                    )
                    break

        except ValueError:
            continue

    conn.close()
    return statuses


@router.get("/{hypothesis_id}/{experiment_id}/steps")
async def get_step_executions(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> List[StepExecution]:
    """获取步骤执行记录"""
    workspace = Path(workspace_path)
    exp_path = _get_experiment_path(workspace, hypothesis_id, experiment_id)
    db_file = exp_path / "run" / "sqlite.db"

    conn = _get_db_connection(db_file)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, step_index, step_type, step_config, start_time, end_time, success, result
        FROM step_executions
        ORDER BY step_index ASC
    """)

    steps = []
    for row in cursor.fetchall():
        (
            step_id,
            step_index,
            step_type,
            step_config_json,
            start_time,
            end_time,
            success,
            result,
        ) = row

        try:
            step_config = json.loads(step_config_json)
        except json.JSONDecodeError:
            step_config = {}

        steps.append(
            StepExecution(
                id=step_id,
                step_index=step_index,
                step_type=step_type,
                step_config=step_config,
                start_time=start_time,
                end_time=end_time,
                success=bool(success),
                result=result,
            )
        )

    conn.close()
    return steps


@router.get("/{hypothesis_id}/{experiment_id}/state")
async def get_latest_state(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> Dict[str, Any]:
    """获取实验最新状态数据"""
    workspace = Path(workspace_path)
    exp_path = _get_experiment_path(workspace, hypothesis_id, experiment_id)
    db_file = exp_path / "run" / "sqlite.db"

    conn = _get_db_connection(db_file)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT timestamp, current_time, step_count, state_data
        FROM experiment_state
        ORDER BY id DESC LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="No state data found")

    timestamp, current_time, step_count, state_data_json = row

    return {
        "timestamp": timestamp,
        "current_time": current_time,
        "step_count": step_count,
        "state": _parse_state_data(state_data_json) if state_data_json else {},
    }


@router.get("/{hypothesis_id}/{experiment_id}/artifacts")
async def list_artifacts(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> List[Dict[str, str]]:
    """列出实验产出文件"""
    workspace = Path(workspace_path)
    exp_path = _get_experiment_path(workspace, hypothesis_id, experiment_id)
    artifacts_dir = exp_path / "run" / "artifacts"

    if not artifacts_dir.exists():
        return []

    artifacts = []
    for file_path in sorted(artifacts_dir.glob("*.md")):
        artifacts.append(
            {
                "name": file_path.name,
                "path": str(file_path),
                "type": "ask" if file_path.name.startswith("ask_") else "intervene",
            }
        )

    return artifacts


@router.get("/{hypothesis_id}/{experiment_id}/artifacts/{artifact_name}")
async def get_artifact(
    hypothesis_id: str,
    experiment_id: str,
    artifact_name: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> Dict[str, str]:
    """获取指定产出文件内容"""
    workspace = Path(workspace_path)
    exp_path = _get_experiment_path(workspace, hypothesis_id, experiment_id)
    artifact_path = exp_path / "run" / "artifacts" / artifact_name

    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail="未找到产出文件")

    content = artifact_path.read_text(encoding="utf-8")

    return {
        "name": artifact_name,
        "content": content,
    }
