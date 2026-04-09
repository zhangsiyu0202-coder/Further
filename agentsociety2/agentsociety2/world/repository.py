"""
WorldRepository: Persist and reload world data using SQLite.

职责：
- 负责世界 metadata、entities、relations、personas、events、snapshots、reports 的持久化
- 使用 SQLite 作为默认后端，大字段以 JSON 存储
- 支持 world snapshot 版本管理
- 支持 world reload
"""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from agentsociety2.logger import get_logger
from agentsociety2.world.models import (
    AgentState,
    Entity,
    GlobalVariable,
    Intervention,
    Persona,
    Relation,
    Report,
    SimulationRun,
    WorldEvent,
    WorldState,
)

__all__ = ["WorldRepository"]

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS worlds (
    world_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    build_summary TEXT,
    current_tick INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS world_entities (
    world_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT,
    name TEXT,
    payload_json TEXT,
    PRIMARY KEY (world_id, entity_id)
);

CREATE TABLE IF NOT EXISTS world_relations (
    world_id TEXT NOT NULL,
    relation_id TEXT NOT NULL,
    source_entity_id TEXT,
    target_entity_id TEXT,
    relation_type TEXT,
    payload_json TEXT,
    PRIMARY KEY (world_id, relation_id)
);

CREATE TABLE IF NOT EXISTS world_personas (
    world_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT,
    PRIMARY KEY (world_id, entity_id)
);

CREATE TABLE IF NOT EXISTS world_agent_states (
    world_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT,
    PRIMARY KEY (world_id, entity_id)
);

CREATE TABLE IF NOT EXISTS world_global_variables (
    world_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value_json TEXT,
    description TEXT,
    updated_at TEXT,
    PRIMARY KEY (world_id, name)
);

CREATE TABLE IF NOT EXISTS world_events (
    world_id TEXT NOT NULL,
    run_id TEXT,
    event_id TEXT NOT NULL,
    tick INTEGER,
    event_type TEXT,
    payload_json TEXT,
    created_at TEXT,
    PRIMARY KEY (world_id, event_id)
);

CREATE TABLE IF NOT EXISTS world_snapshots (
    world_id TEXT NOT NULL,
    snapshot_version INTEGER NOT NULL,
    tick INTEGER,
    payload_json TEXT,
    created_at TEXT,
    PRIMARY KEY (world_id, snapshot_version)
);

CREATE TABLE IF NOT EXISTS world_interventions (
    world_id TEXT NOT NULL,
    intervention_id TEXT NOT NULL,
    intervention_type TEXT,
    payload_json TEXT,
    reason TEXT,
    applied_at_tick INTEGER,
    created_at TEXT,
    PRIMARY KEY (world_id, intervention_id)
);

CREATE TABLE IF NOT EXISTS world_reports (
    world_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    report_type TEXT,
    focus TEXT,
    content TEXT,
    sources_json TEXT,
    created_at TEXT,
    PRIMARY KEY (world_id, report_id)
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    run_id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    start_tick INTEGER,
    end_tick INTEGER,
    steps_requested INTEGER,
    steps_executed INTEGER,
    tick_seconds INTEGER,
    mode TEXT,
    status TEXT,
    new_event_count INTEGER,
    created_at TEXT,
    completed_at TEXT
);
"""


class WorldRepository:
    """SQLite-backed repository for world data."""

    def __init__(self, db_path: str = "agentsociety_world.db"):
        self._db_path = db_path
        self._logger = get_logger()
        self._ensure_tables()

    # ------------------------------------------------------------------
    # DB connection management
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_tables(self) -> None:
        with self._conn() as conn:
            conn.executescript(_CREATE_TABLES_SQL)

    # ------------------------------------------------------------------
    # World CRUD
    # ------------------------------------------------------------------

    async def save_world_state(self, world_state: WorldState) -> None:
        """Persist the full world state (upsert all sub-tables)."""
        await asyncio.to_thread(self._save_world_state_sync, world_state)

    def _save_world_state_sync(self, world_state: WorldState) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO worlds
                   (world_id, name, build_summary, current_tick, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    world_state.world_id,
                    world_state.name,
                    world_state.build_summary,
                    world_state.current_tick,
                    world_state.created_at.isoformat(),
                    now,
                ),
            )

            # Entities
            conn.execute(
                "DELETE FROM world_entities WHERE world_id = ?",
                (world_state.world_id,),
            )
            for e in world_state.entities:
                conn.execute(
                    """INSERT INTO world_entities
                       (world_id, entity_id, entity_type, name, payload_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        world_state.world_id,
                        e.id,
                        e.entity_type,
                        e.name,
                        e.model_dump_json(),
                    ),
                )

            # Relations
            conn.execute(
                "DELETE FROM world_relations WHERE world_id = ?",
                (world_state.world_id,),
            )
            for r in world_state.relations:
                conn.execute(
                    """INSERT INTO world_relations
                       (world_id, relation_id, source_entity_id, target_entity_id, relation_type, payload_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        world_state.world_id,
                        r.id,
                        r.source_entity_id,
                        r.target_entity_id,
                        r.relation_type,
                        r.model_dump_json(),
                    ),
                )

            # Personas
            conn.execute(
                "DELETE FROM world_personas WHERE world_id = ?",
                (world_state.world_id,),
            )
            for p in world_state.personas:
                conn.execute(
                    "INSERT INTO world_personas (world_id, entity_id, payload_json) VALUES (?, ?, ?)",
                    (world_state.world_id, p.entity_id, p.model_dump_json()),
                )

            # Agent states
            conn.execute(
                "DELETE FROM world_agent_states WHERE world_id = ?",
                (world_state.world_id,),
            )
            for a in world_state.agent_states:
                conn.execute(
                    "INSERT INTO world_agent_states (world_id, entity_id, payload_json) VALUES (?, ?, ?)",
                    (world_state.world_id, a.entity_id, a.model_dump_json()),
                )

            # Global variables
            conn.execute(
                "DELETE FROM world_global_variables WHERE world_id = ?",
                (world_state.world_id,),
            )
            for g in world_state.global_variables:
                conn.execute(
                    """INSERT INTO world_global_variables
                       (world_id, name, value_json, description, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        world_state.world_id,
                        g.name,
                        json.dumps(g.value),
                        g.description,
                        g.updated_at.isoformat(),
                    ),
                )

        self._logger.info(
            f"WorldRepository: saved world '{world_state.world_id}' "
            f"({len(world_state.entities)} entities)"
        )

    _SNAPSHOT_TIMELINE_LIMIT = 100

    async def save_snapshot(self, world_state: WorldState) -> None:
        """Save a versioned snapshot (async wrapper)."""
        await asyncio.to_thread(self._save_snapshot_sync, world_state)

    def _save_snapshot_sync(self, world_state: WorldState) -> None:
        """Save a versioned snapshot of the world state.

        Timeline is truncated to the most recent ``_SNAPSHOT_TIMELINE_LIMIT``
        events before serialisation to prevent quadratic storage growth.
        Full event history is preserved separately in ``world_events``.
        """
        now = datetime.utcnow().isoformat()
        if len(world_state.timeline) > self._SNAPSHOT_TIMELINE_LIMIT:
            lean = copy.copy(world_state)
            lean.timeline = world_state.timeline[-self._SNAPSHOT_TIMELINE_LIMIT:]
            payload = lean.model_dump_json()
        else:
            payload = world_state.model_dump_json()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO world_snapshots
                   (world_id, snapshot_version, tick, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    world_state.world_id,
                    world_state.snapshot_version,
                    world_state.current_tick,
                    payload,
                    now,
                ),
            )

    async def load_world_state(
        self,
        world_id: str,
        snapshot_version: Optional[int] = None,
        tick: Optional[int] = None,
    ) -> Optional[WorldState]:
        """Load a world state snapshot by latest version, explicit version, or historical tick."""
        return await asyncio.to_thread(self._load_world_state_sync, world_id, snapshot_version, tick)

    def _load_world_state_sync(
        self,
        world_id: str,
        snapshot_version: Optional[int] = None,
        tick: Optional[int] = None,
    ) -> Optional[WorldState]:
        with self._conn() as conn:
            if snapshot_version is not None:
                row = conn.execute(
                    """SELECT payload_json FROM world_snapshots
                       WHERE world_id = ? AND snapshot_version = ?
                       LIMIT 1""",
                    (world_id, snapshot_version),
                ).fetchone()
            elif tick is not None:
                row = conn.execute(
                    """SELECT payload_json FROM world_snapshots
                       WHERE world_id = ? AND tick <= ?
                       ORDER BY tick DESC, snapshot_version DESC LIMIT 1""",
                    (world_id, tick),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT payload_json FROM world_snapshots
                       WHERE world_id = ?
                       ORDER BY snapshot_version DESC LIMIT 1""",
                    (world_id,),
                ).fetchone()
            if row:
                return WorldState.model_validate_json(row["payload_json"])
        return None

    async def list_snapshots(self, world_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        """List snapshot metadata for a world, newest first."""
        return await asyncio.to_thread(self._list_snapshots_sync, world_id, limit)

    def _list_snapshots_sync(self, world_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT snapshot_version, tick, created_at
                   FROM world_snapshots
                   WHERE world_id = ?
                   ORDER BY snapshot_version DESC
                   LIMIT ?""",
                (world_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    async def list_worlds(self) -> List[Dict[str, Any]]:
        """Return a list of world metadata records."""
        return await asyncio.to_thread(self._list_worlds_sync)

    def _list_worlds_sync(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT world_id, name, build_summary, current_tick, created_at, updated_at FROM worlds"
            ).fetchall()
            return [dict(r) for r in rows]

    async def get_world_meta(self, world_id: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._get_world_meta_sync, world_id)

    def _get_world_meta_sync(self, world_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM worlds WHERE world_id = ?", (world_id,)
            ).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def save_events(
        self, world_id: str, events: List[WorldEvent], run_id: Optional[str] = None
    ) -> None:
        await asyncio.to_thread(self._save_events_sync, world_id, events, run_id)

    def _save_events_sync(
        self, world_id: str, events: List[WorldEvent], run_id: Optional[str] = None
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            for e in events:
                conn.execute(
                    """INSERT OR REPLACE INTO world_events
                       (world_id, run_id, event_id, tick, event_type, payload_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        world_id,
                        run_id,
                        e.id,
                        e.tick,
                        e.event_type,
                        e.model_dump_json(),
                        e.created_at.isoformat(),
                    ),
                )

    async def get_events(
        self,
        world_id: str,
        limit: int = 50,
        after_tick: int = -1,
        event_type: Optional[str] = None,
    ) -> List[WorldEvent]:
        return await asyncio.to_thread(self._get_events_sync, world_id, limit, after_tick, event_type)

    def _get_events_sync(
        self,
        world_id: str,
        limit: int = 50,
        after_tick: int = -1,
        event_type: Optional[str] = None,
    ) -> List[WorldEvent]:
        query = "SELECT payload_json FROM world_events WHERE world_id = ?"
        params: list = [world_id]
        if after_tick >= 0:
            query += " AND tick > ?"
            params.append(after_tick)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY tick ASC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [WorldEvent.model_validate_json(r["payload_json"]) for r in rows]

    # ------------------------------------------------------------------
    # Interventions
    # ------------------------------------------------------------------

    async def save_intervention(self, intervention: Intervention) -> None:
        await asyncio.to_thread(self._save_intervention_sync, intervention)

    def _save_intervention_sync(self, intervention: Intervention) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO world_interventions
                   (world_id, intervention_id, intervention_type, payload_json, reason, applied_at_tick, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    intervention.world_id,
                    intervention.intervention_id,
                    intervention.intervention_type,
                    intervention.model_dump_json(),
                    intervention.reason,
                    intervention.applied_at_tick,
                    intervention.created_at.isoformat(),
                ),
            )

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    async def save_report(self, report: Report) -> None:
        await asyncio.to_thread(self._save_report_sync, report)

    def _save_report_sync(self, report: Report) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO world_reports
                   (world_id, report_id, report_type, focus, content, sources_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.world_id,
                    report.report_id,
                    report.report_type,
                    report.focus,
                    report.content,
                    json.dumps(report.sources),
                    report.created_at.isoformat(),
                ),
            )

    async def get_latest_report(self, world_id: str) -> Optional[Report]:
        return await asyncio.to_thread(self._get_latest_report_sync, world_id)

    def _get_latest_report_sync(self, world_id: str) -> Optional[Report]:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM world_reports WHERE world_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (world_id,),
            ).fetchone()
            if row:
                return Report(
                    report_id=row["report_id"],
                    world_id=row["world_id"],
                    report_type=row["report_type"],
                    focus=row["focus"] or "",
                    content=row["content"],
                    sources=json.loads(row["sources_json"] or "[]"),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
        return None

    # ------------------------------------------------------------------
    # Simulation runs
    # ------------------------------------------------------------------

    async def save_run(self, run: SimulationRun) -> None:
        await asyncio.to_thread(self._save_run_sync, run)

    def _save_run_sync(self, run: SimulationRun) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO simulation_runs
                   (run_id, world_id, start_tick, end_tick, steps_requested, steps_executed,
                    tick_seconds, mode, status, new_event_count, created_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.run_id,
                    run.world_id,
                    run.start_tick,
                    run.end_tick,
                    run.steps_requested,
                    run.steps_executed,
                    run.tick_seconds,
                    run.mode,
                    run.status,
                    run.new_event_count,
                    run.created_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                ),
            )

    async def get_latest_run(self, world_id: str) -> Optional[SimulationRun]:
        """Return the most recent simulation run metadata for a world."""
        return await asyncio.to_thread(self._get_latest_run_sync, world_id)

    def _get_latest_run_sync(self, world_id: str) -> Optional[SimulationRun]:
        """Return the most recent simulation run metadata for a world."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM simulation_runs
                   WHERE world_id = ?
                   ORDER BY created_at DESC
                   LIMIT 1""",
                (world_id,),
            ).fetchone()
            if not row:
                return None
            return SimulationRun(
                run_id=row["run_id"],
                world_id=row["world_id"],
                start_tick=row["start_tick"] or 0,
                end_tick=row["end_tick"],
                steps_requested=row["steps_requested"] or 0,
                steps_executed=row["steps_executed"] or 0,
                tick_seconds=row["tick_seconds"] or 300,
                mode=row["mode"] or "batch",
                status=row["status"] or "completed",
                new_event_count=row["new_event_count"] or 0,
                created_at=datetime.fromisoformat(row["created_at"]),
                completed_at=(
                    datetime.fromisoformat(row["completed_at"])
                    if row["completed_at"]
                    else None
                ),
            )
