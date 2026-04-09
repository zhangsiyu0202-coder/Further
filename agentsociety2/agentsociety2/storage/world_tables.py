"""
WorldTables: SQLite table schema definitions for world simulation data.

职责：
- 定义世界域数据的 SQLite 表结构（作为 storage/ 层的补充）
- 提供与 ReplayWriter 兼容的 ColumnDef / TableSchema 格式
- 可用于通过 ReplayWriter 注册世界相关自定义表
"""

from __future__ import annotations

from agentsociety2.storage.table_schema import ColumnDef, TableSchema

__all__ = [
    "WORLD_EVENTS_SCHEMA",
    "WORLD_SNAPSHOTS_SCHEMA",
    "WORLD_INTERVENTIONS_SCHEMA",
    "WORLD_REPORTS_SCHEMA",
    "ALL_WORLD_SCHEMAS",
]

WORLD_EVENTS_SCHEMA = TableSchema(
    name="world_events",
    columns=[
        ColumnDef(name="world_id", type="TEXT"),
        ColumnDef(name="run_id", type="TEXT"),
        ColumnDef(name="event_id", type="TEXT", nullable=False),
        ColumnDef(name="tick", type="INTEGER"),
        ColumnDef(name="event_type", type="TEXT"),
        ColumnDef(name="payload_json", type="TEXT"),
        ColumnDef(name="created_at", type="TEXT"),
    ],
    primary_key=["event_id"],
)

WORLD_SNAPSHOTS_SCHEMA = TableSchema(
    name="world_snapshots",
    columns=[
        ColumnDef(name="world_id", type="TEXT", nullable=False),
        ColumnDef(name="snapshot_version", type="INTEGER", nullable=False),
        ColumnDef(name="tick", type="INTEGER"),
        ColumnDef(name="payload_json", type="TEXT"),
        ColumnDef(name="created_at", type="TEXT"),
    ],
    primary_key=["world_id", "snapshot_version"],
)

WORLD_INTERVENTIONS_SCHEMA = TableSchema(
    name="world_interventions",
    columns=[
        ColumnDef(name="world_id", type="TEXT"),
        ColumnDef(name="intervention_id", type="TEXT", nullable=False),
        ColumnDef(name="intervention_type", type="TEXT"),
        ColumnDef(name="payload_json", type="TEXT"),
        ColumnDef(name="reason", type="TEXT"),
        ColumnDef(name="applied_at_tick", type="INTEGER"),
        ColumnDef(name="created_at", type="TEXT"),
    ],
    primary_key=["intervention_id"],
)

WORLD_REPORTS_SCHEMA = TableSchema(
    name="world_reports",
    columns=[
        ColumnDef(name="world_id", type="TEXT"),
        ColumnDef(name="report_id", type="TEXT", nullable=False),
        ColumnDef(name="report_type", type="TEXT"),
        ColumnDef(name="focus", type="TEXT"),
        ColumnDef(name="content", type="TEXT"),
        ColumnDef(name="sources_json", type="TEXT"),
        ColumnDef(name="created_at", type="TEXT"),
    ],
    primary_key=["report_id"],
)

ALL_WORLD_SCHEMAS = [
    WORLD_EVENTS_SCHEMA,
    WORLD_SNAPSHOTS_SCHEMA,
    WORLD_INTERVENTIONS_SCHEMA,
    WORLD_REPORTS_SCHEMA,
]
