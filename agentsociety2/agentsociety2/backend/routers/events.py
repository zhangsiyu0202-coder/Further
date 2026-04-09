"""SSE 进度推送路由：用于世界构建和图谱构建任务的实时进度流。

客户端使用 EventSource 连接：
  GET /api/v1/tasks/{task_id}/stream?task_type=world_build|graph_build

当任务状态变为 completed 或 failed 时，服务端发送终止事件并关闭连接。
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/v1/tasks", tags=["events"])

_POLL_INTERVAL = 0.8  # seconds between status checks
_MAX_IDLE_TICKS = 600  # ~8 minutes before forced close


def _get_task(task_id: str, task_type: str) -> dict | None:
    if task_type == "world_build":
        from agentsociety2.backend.services.world_builder_service import _tasks
        return _tasks.get(task_id)
    # default: graph_build
    from agentsociety2.backend.services.graph_service import _tasks
    return _tasks.get(task_id)


async def _task_stream(task_id: str, task_type: str) -> AsyncGenerator[str, None]:
    idle = 0
    last_status: str | None = None

    while idle < _MAX_IDLE_TICKS:
        task = _get_task(task_id, task_type)

        if task is None:
            data = json.dumps({"status": "not_found", "task_id": task_id, "progress": 0, "message": "任务不存在"})
            yield f"event: error\ndata: {data}\n\n"
            return

        payload = {
            "task_id": task.get("task_id", task_id),
            "status": task.get("status", "pending"),
            "progress": int(task.get("progress") or 0),
            "message": task.get("message") or "",
            "error": task.get("error"),
        }

        status = payload["status"]
        if status != last_status:
            yield f"data: {json.dumps(payload)}\n\n"
            last_status = status

        if status in {"completed", "failed"}:
            yield f"event: done\ndata: {json.dumps(payload)}\n\n"
            return

        idle += 1
        await asyncio.sleep(_POLL_INTERVAL)

    yield f"event: timeout\ndata: {json.dumps({'task_id': task_id, 'message': '等待超时'})}\n\n"


@router.get("/{task_id}/stream")
async def stream_task_progress(task_id: str, task_type: str = "graph_build") -> StreamingResponse:
    """SSE 流：推送单个后台任务的进度直到完成或失败。

    用法::

        const es = new EventSource(`/api/v1/tasks/${taskId}/stream?task_type=world_build`);
        es.onmessage = (e) => console.log(JSON.parse(e.data));
        es.addEventListener('done', () => es.close());
    """
    return StreamingResponse(
        _task_stream(task_id, task_type),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
