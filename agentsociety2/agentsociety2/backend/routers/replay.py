"""
Replay data query API for simulation playback.

关联文件：
- @extension/src/replayWebviewProvider.ts - 前端Replay Webview（调用此API）
- @extension/src/webview/replay/ - 前端React组件

API端点：
- GET /api/v1/replay/{hypothesis_id}/{experiment_id}/info - 实验基本信息
- GET /api/v1/replay/{hypothesis_id}/{experiment_id}/timeline - 时间线
- GET /api/v1/replay/{hypothesis_id}/{experiment_id}/agents/* - Agent相关数据
- GET /api/v1/replay/{hypothesis_id}/{experiment_id}/social/* - 社交媒体数据
- GET /api/v1/replay/{hypothesis_id}/{experiment_id}/tables/* - 数据库表查询
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite
import json
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import select, desc, func, col, SQLModel, text

from ...storage.models import (
    AgentProfile,
    AgentStatus,
    AgentDialog,
)
from ...contrib.env.social_media.replay_tables import (
    social_user_table,
    social_post_table,
    social_comment_table,
    social_follow_table,
    social_dm_table,
    social_group_table,
    social_group_message_table,
)
router = APIRouter(prefix="/replay", tags=["replay"])


# =============== Data Models (Response Models) ===============
# We reuse SQLModel classes where possible, or define Pydantic models for responses that don't match DB exactly.
# For simplicity, we redefine some response models if they differ significantly or to decouple API from generic DB models.
# But here, most models match nicely.
# However, to maintain API compatibility (camelCase vs snake_case if any, or specific fields), let's keep existing response models
# but map them from DB objects.


class ExperimentInfo(BaseModel):
    """Basic information about an experiment."""

    hypothesis_id: str
    experiment_id: str
    total_steps: int
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    agent_count: int
    has_social: bool = False


class TimelinePoint(BaseModel):
    """A point on the simulation timeline."""

    step: int
    t: datetime


# Use SQLModel classes as response models where appropriate to save code
# But for AgentStatus, we need merged result (status + position)
class AgentStatusResponse(BaseModel):
    """Agent status snapshot at a specific step (Combined with Position)."""

    id: int
    step: int
    t: datetime
    lng: Optional[float]
    lat: Optional[float]
    action: Optional[str]
    status: Dict[str, Any]


class TableList(BaseModel):
    """List of database tables."""

    tables: List[str]


class TableContent(BaseModel):
    """Content of a database table."""

    columns: List[str]
    rows: List[Dict[str, Any]]
    total: int


class SocialNetworkNode(BaseModel):
    user_id: int
    username: str


class SocialNetworkEdge(BaseModel):
    source: int
    target: int


class SocialNetwork(BaseModel):
    nodes: List[SocialNetworkNode]
    edges: List[SocialNetworkEdge]


# Replay API response models for social tables (tables are owned by social_media module)
class SocialUser(BaseModel):
    user_id: int
    username: str
    bio: Optional[str] = None
    created_at: Optional[datetime] = None
    followers_count: Optional[int] = None
    following_count: Optional[int] = None
    posts_count: Optional[int] = None
    profile: Optional[Any] = None


class SocialPost(BaseModel):
    post_id: int
    step: int
    author_id: int
    content: str
    post_type: str
    parent_id: Optional[int] = None
    created_at: Optional[datetime] = None
    likes_count: Optional[int] = 0
    reposts_count: Optional[int] = 0
    comments_count: Optional[int] = 0
    view_count: Optional[int] = 0
    tags: Optional[Any] = None
    topic_category: Optional[str] = None


class SocialComment(BaseModel):
    comment_id: int
    step: int
    post_id: int
    author_id: int
    content: str
    parent_comment_id: Optional[int] = None
    created_at: Optional[datetime] = None
    likes_count: Optional[int] = 0


class SocialDirectMessage(BaseModel):
    message_id: int
    step: int
    from_user_id: int
    to_user_id: int
    content: str
    created_at: Optional[datetime] = None
    read: Optional[int] = 0


class SocialGroupMessage(BaseModel):
    message_id: int
    step: int
    group_id: int
    from_user_id: int
    content: str
    created_at: Optional[datetime] = None
    group_name: Optional[str] = None


class SocialActivityResponse(BaseModel):
    """Per-step social activity: which agents received/sent DMs or sent group messages."""

    step: int
    received_dm_agent_ids: List[int]
    sent_dm_agent_ids: List[int]
    sent_group_message_agent_ids: List[int]


# =============== Helper Functions ===============


def get_db_path(workspace_path: str, hypothesis_id: str, experiment_id: str) -> Path:
    """Get the SQLite database path for an experiment."""
    return (
        Path(workspace_path)
        / f"hypothesis_{hypothesis_id}"
        / f"experiment_{experiment_id}"
        / "run"
        / "sqlite.db"
    )


async def get_db_session(db_path: Path):
    """获取异步数据库会话上下文管理器。"""
    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"未找到数据库：{db_path}")

    connection_string = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(connection_string, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session

    await engine.dispose()


# =============== API Endpoints ===============


@router.get("/{hypothesis_id}/{experiment_id}/info", response_model=ExperimentInfo)
async def get_experiment_info(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> ExperimentInfo:
    """Get basic information about an experiment."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        # Total steps
        result = await session.execute(
            select(func.count(func.distinct(AgentStatus.step)))
        )
        total_steps = result.scalar() or 0

        result = await session.execute(select(func.min(AgentStatus.t)))
        start_time = result.scalar()
        result = await session.execute(select(func.max(AgentStatus.t)))
        end_time = result.scalar()
        result = await session.execute(select(func.count(AgentProfile.id)))
        agent_count = result.scalar() or 0

        def _get_tables(sync_sess):
            from sqlalchemy import inspect

            return inspect(sync_sess.connection()).get_table_names()

        tables = await session.run_sync(_get_tables)
        has_social = "social_user" in tables

        return ExperimentInfo(
            hypothesis_id=hypothesis_id,
            experiment_id=experiment_id,
            total_steps=total_steps,
            start_time=start_time,
            end_time=end_time,
            agent_count=agent_count,
            has_social=has_social,
        )


@router.get(
    "/{hypothesis_id}/{experiment_id}/timeline", response_model=List[TimelinePoint]
)
async def get_timeline(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> List[TimelinePoint]:
    """Get the experiment timeline (all time steps)."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        statement = (
            select(AgentStatus.step, AgentStatus.t)
            .distinct()
            .order_by(AgentStatus.step)
        )
        result = await session.execute(statement)
        rows = result.all()
        return [TimelinePoint(step=r[0], t=r[1]) for r in rows]


@router.get(
    "/{hypothesis_id}/{experiment_id}/agents/profiles",
    response_model=List[AgentProfile],
)
async def get_agent_profiles(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> List[AgentProfile]:
    """Get all agent profiles."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        result = await session.execute(select(AgentProfile))
        return result.scalars().all()


@router.get(
    "/{hypothesis_id}/{experiment_id}/agents/status",
    response_model=List[AgentStatusResponse],
)
async def get_agents_status_at_step(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
    step: Optional[int] = Query(
        None, description="Specific step to query. If not provided, returns the latest."
    ),
) -> List[AgentStatusResponse]:
    """Get all agents' status at a specific step."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        if step is None:
            # Get latest step
            result = await session.execute(select(func.max(AgentStatus.step)))
            step = result.scalar()
            if step is None:
                return []

        # Left join with agent_position (table exists only when position-tracking env is loaded)
        try:
            statement = (
                select(AgentStatus, agent_position_table)
                .select_from(AgentStatus)
                .outerjoin(
                    agent_position_table,
                    (AgentStatus.id == agent_position_table.c.id)
                    & (AgentStatus.step == agent_position_table.c.step),
                )
                .where(AgentStatus.step == step)
            )
            result = await session.execute(statement)
            rows = result.all()

            def _lng_lat_from_row(row):
                pos = row[1]
                if pos is None:
                    return None, None
                # Row may be flat: (AgentStatus, pos_id, pos_step, pos_t, lng, lat, ...) so row[1] is int
                if isinstance(pos, (int, float)) or not hasattr(pos, "_mapping"):
                    if len(row) > 5:
                        return row[4], row[5]
                    return None, None
                mapping = getattr(pos, "_mapping", None)
                if mapping is not None:
                    return mapping.get("lng"), mapping.get("lat")
                return getattr(pos, "lng", None), getattr(pos, "lat", None)

            return [
                AgentStatusResponse(
                    id=row[0].id,
                    step=row[0].step,
                    t=row[0].t,
                    lng=lng,
                    lat=lat,
                    action=row[0].action,
                    status=row[0].status or {},
                )
                for row in rows
                for lng, lat in (_lng_lat_from_row(row),)
            ]
        except OperationalError:
            # agent_position table not present
            result = await session.execute(
                select(AgentStatus).where(AgentStatus.step == step)
            )
            statuses = result.scalars().all()
            return [
                AgentStatusResponse(
                    id=s.id,
                    step=s.step,
                    t=s.t,
                    lng=None,
                    lat=None,
                    action=s.action,
                    status=s.status or {},
                )
                for s in statuses
            ]


@router.get(
    "/{hypothesis_id}/{experiment_id}/agents/{agent_id}/status",
    response_model=List[AgentStatusResponse],
)
async def get_agent_status_history(
    hypothesis_id: str,
    experiment_id: str,
    agent_id: int,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> List[AgentStatusResponse]:
    """Get the complete status history of a specific agent."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        try:
            statement = (
                select(AgentStatus, agent_position_table)
                .select_from(AgentStatus)
                .outerjoin(
                    agent_position_table,
                    (AgentStatus.id == agent_position_table.c.id)
                    & (AgentStatus.step == agent_position_table.c.step),
                )
                .where(AgentStatus.id == agent_id)
                .order_by(AgentStatus.step)
            )
            result = await session.execute(statement)
            rows = result.all()

            def _lng_lat_from_row(row):
                pos = row[1]
                if pos is None:
                    return None, None
                if isinstance(pos, (int, float)) or not hasattr(pos, "_mapping"):
                    if len(row) > 5:
                        return row[4], row[5]
                    return None, None
                mapping = getattr(pos, "_mapping", None)
                if mapping is not None:
                    return mapping.get("lng"), mapping.get("lat")
                return getattr(pos, "lng", None), getattr(pos, "lat", None)

            return [
                AgentStatusResponse(
                    id=row[0].id,
                    step=row[0].step,
                    t=row[0].t,
                    lng=lng,
                    lat=lat,
                    action=row[0].action,
                    status=row[0].status or {},
                )
                for row in rows
                for lng, lat in (_lng_lat_from_row(row),)
            ]
        except OperationalError:
            result = await session.execute(
                select(AgentStatus)
                .where(AgentStatus.id == agent_id)
                .order_by(AgentStatus.step)
            )
            statuses = result.scalars().all()
            return [
                AgentStatusResponse(
                    id=s.id,
                    step=s.step,
                    t=s.t,
                    lng=None,
                    lat=None,
                    action=s.action,
                    status=s.status or {},
                )
                for s in statuses
            ]


@router.get(
    "/{hypothesis_id}/{experiment_id}/agents/{agent_id}/trajectory",
    response_model=List[Dict[str, Any]],
)
async def get_agent_trajectory(
    hypothesis_id: str,
    experiment_id: str,
    agent_id: int,
    workspace_path: str = Query(..., description="Workspace root path"),
    start_step: Optional[int] = Query(None, description="Start step (inclusive)"),
    end_step: Optional[int] = Query(None, description="End step (inclusive)"),
) -> List[Dict[str, Any]]:
    """Get the movement trajectory of a specific agent (requires position-tracking env module)."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        try:
            query = select(agent_position_table).where(
                agent_position_table.c.id == agent_id
            )
            if start_step is not None:
                query = query.where(agent_position_table.c.step >= start_step)
            if end_step is not None:
                query = query.where(agent_position_table.c.step <= end_step)
            query = query.order_by(agent_position_table.c.step)
            result = await session.execute(query)
            rows = result.all()
            return [
                {
                    "step": row.step,
                    "t": row.t.isoformat()
                    if hasattr(row.t, "isoformat")
                    else str(row.t),
                    "lng": row.lng,
                    "lat": row.lat,
                }
                for row in rows
            ]
        except OperationalError:
            return []


@router.get(
    "/{hypothesis_id}/{experiment_id}/agents/{agent_id}/dialog",
    response_model=List[AgentDialog],
)
async def get_agent_dialogs(
    hypothesis_id: str,
    experiment_id: str,
    agent_id: int,
    workspace_path: str = Query(..., description="Workspace root path"),
    dialog_type: Optional[int] = Query(
        None, description="Dialog type filter: 0=thought, 1=agent-to-agent, 2=user"
    ),
) -> List[AgentDialog]:
    """Get dialog records for a specific agent."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        query = select(AgentDialog).where(AgentDialog.agent_id == agent_id)
        if dialog_type is not None:
            query = query.where(AgentDialog.type == dialog_type)

        query = query.order_by(AgentDialog.step, AgentDialog.id)
        result = await session.execute(query)
        return result.scalars().all()


@router.get(
    "/{hypothesis_id}/{experiment_id}/dialogs/step/{step}",
    response_model=List[AgentDialog],
)
async def get_dialogs_at_step(
    hypothesis_id: str,
    experiment_id: str,
    step: int,
    workspace_path: str = Query(..., description="Workspace root path"),
    dialog_type: Optional[int] = Query(
        None,
        description="Dialog type filter: 0=反思 (thought/reflection); V2 only has type 0",
    ),
) -> List[AgentDialog]:
    """Get all dialog records at a specific step."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        query = select(AgentDialog).where(AgentDialog.step == step)
        if dialog_type is not None:
            query = query.where(AgentDialog.type == dialog_type)

        query = query.order_by(AgentDialog.id)
        result = await session.execute(query)
        return result.scalars().all()


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Map SQLAlchemy Row to dict for Pydantic (handles _mapping and datetime)."""
    if hasattr(row, "_mapping"):
        d = dict(row._mapping)
    else:
        d = dict(row)
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v
    return d


@router.get(
    "/{hypothesis_id}/{experiment_id}/social/users/{user_id}",
    response_model=SocialUser,
)
async def get_social_user(
    hypothesis_id: str,
    experiment_id: str,
    user_id: int,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> SocialUser:
    """Get social media profile for a user (table owned by social_media module)."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        try:
            query = select(social_user_table).where(
                social_user_table.c.user_id == user_id
            )
            result = await session.execute(query)
            row = result.one_or_none()
        except OperationalError:
            raise HTTPException(status_code=404, detail="未找到社交用户")
        if not row:
            raise HTTPException(status_code=404, detail="未找到社交用户")
        return SocialUser(**_row_to_dict(row))


@router.get(
    "/{hypothesis_id}/{experiment_id}/social/users/{user_id}/posts",
    response_model=List[SocialPost],
)
async def get_social_posts(
    hypothesis_id: str,
    experiment_id: str,
    user_id: int,
    workspace_path: str = Query(..., description="Workspace root path"),
    max_step: Optional[int] = Query(
        None, description="Only posts with step <= max_step (timeline step)"
    ),
    limit: int = Query(200, ge=1, le=500),
) -> List[SocialPost]:
    """Get posts from a social media user (table owned by social_media module)."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        try:
            query = select(social_post_table).where(
                social_post_table.c.author_id == user_id
            )
            if max_step is not None:
                query = query.where(social_post_table.c.step <= max_step)
            query = query.order_by(desc(social_post_table.c.created_at)).limit(limit)
            result = await session.execute(query)
            rows = result.all()
            return [SocialPost(**_row_to_dict(r)) for r in rows]
        except OperationalError:
            return []


@router.get(
    "/{hypothesis_id}/{experiment_id}/social/posts",
    response_model=List[SocialPost],
)
async def get_all_social_posts(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
    max_step: Optional[int] = Query(
        None, description="Only posts with step <= max_step (timeline step)"
    ),
    limit: int = Query(500, ge=1, le=2000),
) -> List[SocialPost]:
    """Get all posts from all users (table owned by social_media module)."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        try:
            query = select(social_post_table)
            if max_step is not None:
                query = query.where(social_post_table.c.step <= max_step)
            query = query.order_by(
                desc(social_post_table.c.step), desc(social_post_table.c.created_at)
            ).limit(limit)
            result = await session.execute(query)
            rows = result.all()
            return [SocialPost(**_row_to_dict(r)) for r in rows]
        except OperationalError:
            return []


@router.get(
    "/{hypothesis_id}/{experiment_id}/social/posts/{post_id}/comments",
    response_model=List[SocialComment],
)
async def get_post_comments(
    hypothesis_id: str,
    experiment_id: str,
    post_id: int,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> List[SocialComment]:
    """Get all comments for a post (table owned by social_media module)."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        try:
            query = (
                select(social_comment_table)
                .where(social_comment_table.c.post_id == post_id)
                .order_by(social_comment_table.c.created_at)
            )
            result = await session.execute(query)
            rows = result.all()
            return [SocialComment(**_row_to_dict(r)) for r in rows]
        except OperationalError:
            return []


@router.get(
    "/{hypothesis_id}/{experiment_id}/social/users/{user_id}/direct_messages",
    response_model=List[SocialDirectMessage],
)
async def get_social_direct_messages(
    hypothesis_id: str,
    experiment_id: str,
    user_id: int,
    workspace_path: str = Query(..., description="Workspace root path"),
    max_step: Optional[int] = Query(
        None, description="Only messages with step <= max_step (timeline step)"
    ),
    limit: int = Query(500, ge=1, le=2000),
) -> List[SocialDirectMessage]:
    """Get direct messages for a user (table owned by social_media module)."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        try:
            query = select(social_dm_table).where(
                (social_dm_table.c.from_user_id == user_id)
                | (social_dm_table.c.to_user_id == user_id)
            )
            if max_step is not None:
                query = query.where(social_dm_table.c.step <= max_step)
            query = query.order_by(desc(social_dm_table.c.created_at)).limit(limit)
            result = await session.execute(query)
            rows = result.all()
            return [SocialDirectMessage(**_row_to_dict(r)) for r in rows]
        except OperationalError:
            return []


@router.get(
    "/{hypothesis_id}/{experiment_id}/social/users/{user_id}/group_messages",
    response_model=List[SocialGroupMessage],
)
async def get_social_group_messages(
    hypothesis_id: str,
    experiment_id: str,
    user_id: int,
    workspace_path: str = Query(..., description="Workspace root path"),
    max_step: Optional[int] = Query(
        None, description="Only messages with step <= max_step (timeline step)"
    ),
    limit: int = Query(500, ge=1, le=2000),
) -> List[SocialGroupMessage]:
    """Get group messages for a user (tables owned by social_media module)."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        try:
            stmt = (
                select(social_group_message_table, social_group_table.c.group_name)
                .select_from(social_group_message_table)
                .outerjoin(
                    social_group_table,
                    social_group_message_table.c.group_id
                    == social_group_table.c.group_id,
                )
                .where(social_group_message_table.c.from_user_id == user_id)
            )
            if max_step is not None:
                stmt = stmt.where(social_group_message_table.c.step <= max_step)
            stmt = stmt.order_by(desc(social_group_message_table.c.created_at)).limit(
                limit
            )
            result = await session.execute(stmt)
            rows = result.all()
        except OperationalError:
            return []

        response = []
        for row in rows:
            d = _row_to_dict(row)
            response.append(SocialGroupMessage(**d))
        return response


@router.get(
    "/{hypothesis_id}/{experiment_id}/social/network",
    response_model=SocialNetwork,
)
async def get_social_network(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> SocialNetwork:
    """Get social network graph (tables owned by social_media module)."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        try:
            users_result = await session.execute(
                select(social_user_table).order_by(social_user_table.c.user_id)
            )
            users_rows = users_result.all()
            follows_result = await session.execute(
                select(social_follow_table).order_by(social_follow_table.c.id)
            )
            follows_rows = follows_result.all()
        except OperationalError:
            return SocialNetwork(nodes=[], edges=[])

        nodes = [
            SocialNetworkNode(
                user_id=r._mapping["user_id"], username=r._mapping["username"]
            )
            for r in users_rows
        ]
        latest_actions: Dict[tuple[int, int], str] = {}
        for r in follows_rows:
            m = r._mapping
            latest_actions[(m["follower_id"], m["followee_id"])] = m["action"]
        edges = [
            SocialNetworkEdge(source=follower_id, target=followee_id)
            for (follower_id, followee_id), action in latest_actions.items()
            if action == "follow"
        ]
        return SocialNetwork(nodes=nodes, edges=edges)


@router.get(
    "/{hypothesis_id}/{experiment_id}/social/activity",
    response_model=SocialActivityResponse,
)
async def get_social_activity_at_step(
    hypothesis_id: str,
    experiment_id: str,
    step: int = Query(..., ge=0, description="Simulation step to query"),
    workspace_path: str = Query(..., description="Workspace root path"),
) -> SocialActivityResponse:
    """Get which agents had social activity (received/sent DM, sent group message) at a given step."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    received_dm: List[int] = []
    sent_dm: List[int] = []
    sent_group: List[int] = []

    async for session in get_db_session(db_path):
        try:
            result = await session.execute(
                select(social_dm_table.c.to_user_id)
                .where(social_dm_table.c.step == step)
                .distinct()
            )
            received_dm = list({r[0] for r in result.all()})

            result = await session.execute(
                select(social_dm_table.c.from_user_id)
                .where(social_dm_table.c.step == step)
                .distinct()
            )
            sent_dm = list({r[0] for r in result.all()})

            result = await session.execute(
                select(social_group_message_table.c.from_user_id)
                .where(social_group_message_table.c.step == step)
                .distinct()
            )
            sent_group = list({r[0] for r in result.all()})
        except OperationalError:
            pass

        return SocialActivityResponse(
            step=step,
            received_dm_agent_ids=received_dm,
            sent_dm_agent_ids=sent_dm,
            sent_group_message_agent_ids=sent_group,
        )


# =============== Database Inspection Endpoints ===============


@router.get("/{hypothesis_id}/{experiment_id}/tables", response_model=TableList)
async def get_tables(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> TableList:
    """Get list of all tables in the database."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    # Inspection usually requires standard SQLAlchemy inspection, easier with async engine
    async for session in get_db_session(db_path):
        # We can run an inspection on the engine connection
        def get_all_tables(sync_session):
            # sync_session is a sqlalchemy.orm.Session
            from sqlalchemy import inspect

            inspector = inspect(sync_session.connection())
            return inspector.get_table_names()

        tables = await session.run_sync(get_all_tables)
        return TableList(tables=tables)


@router.get(
    "/{hypothesis_id}/{experiment_id}/tables/{table_name}", response_model=TableContent
)
async def get_table_content(
    hypothesis_id: str,
    experiment_id: str,
    table_name: str,
    workspace_path: str = Query(..., description="Workspace root path"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> TableContent:
    """Get content of a specific table."""
    db_path = get_db_path(workspace_path, hypothesis_id, experiment_id)

    async for session in get_db_session(db_path):
        # Use simple text SQL for dynamic table content to avoid schema reflection overhead/complexity
        # Get columns
        # Use PRAGMA or just select * limit 0?
        # Using raw sql is easiest here for generic table

        offset = (page - 1) * page_size

        # Get total count
        count_sql = f"SELECT COUNT(*) FROM {table_name}"
        total_result = await session.execute(text(count_sql))
        total = total_result.scalar() or 0

        # Get data
        data_sql = f"SELECT * FROM {table_name} LIMIT {page_size} OFFSET {offset}"
        result = await session.execute(text(data_sql))

        columns = list(result.keys())
        rows = [dict(row._mapping) for row in result.all()]

        return TableContent(columns=columns, rows=rows, total=total)
