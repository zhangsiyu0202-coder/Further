"""AgentSociety2 世界仿真后端入口。"""

from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from agentsociety2 import __version__
from agentsociety2.backend.routers import worlds, simulations, interactions, reports, health, graph, events

_project_root = Path(__file__).resolve().parents[2]
load_dotenv(_project_root / ".env")


def _setup_logging():
    log_level = os.getenv("BACKEND_LOG_LEVEL", "info")
    python_log_level = "DEBUG" if log_level.lower() == "trace" else log_level.upper()
    level = getattr(logging, python_log_level, logging.INFO)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            force=True,
        )
    else:
        root_logger.setLevel(level)
    logging.getLogger("agentsociety2").setLevel(level)
    return logging.getLogger("agentsociety2")


_setup_logging()
from agentsociety2.logger import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# Shared service singletons (initialized on startup)
# ---------------------------------------------------------------------------

_world_builder_service = None
_simulation_service = None
_interaction_service = None
_report_service = None


def get_world_builder_service():
    return _world_builder_service


def get_simulation_service():
    return _simulation_service


def get_interaction_service():
    return _interaction_service


def get_report_service():
    return _report_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _world_builder_service, _simulation_service, _interaction_service, _report_service

    logger.info("AgentSociety2 世界仿真后端正在启动...")

    db_path = os.getenv("WORLD_DB_PATH", "agentsociety_world.db")
    from agentsociety2.world import WorldRepository
    from agentsociety2.backend.services.world_builder_service import WorldBuilderService
    from agentsociety2.backend.services.simulation_service import SimulationService
    from agentsociety2.backend.services.interaction_service import InteractionService
    from agentsociety2.backend.services.report_service import ReportService

    repo = WorldRepository(db_path=db_path)
    _world_builder_service = WorldBuilderService(repository=repo)
    _simulation_service = SimulationService(repository=repo)
    _interaction_service = InteractionService(repository=repo)
    _report_service = ReportService(repository=repo)

    logger.info(f"世界数据库路径：{db_path}")
    logger.info("AgentSociety2 世界仿真后端已就绪。")

    yield

    logger.info("AgentSociety2 世界仿真后端正在关闭。")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AgentSociety2 世界仿真后端",
    description=(
        "基于大语言模型的世界仿真后端服务，支持从种子材料构建世界、执行仿真、与世界或智能体对话，并生成报告。"
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register new world simulation routers
app.include_router(worlds.router)
app.include_router(simulations.router)
app.include_router(interactions.router)
app.include_router(reports.router)
app.include_router(health.router)
app.include_router(graph.router)
app.include_router(events.router)


@app.get("/")
async def root():
    return {
        "service": "AgentSociety2 世界仿真后端",
        "version": __version__,
        "status": "运行中",
        "docs": "/docs",
        "api_prefix": "/api/v1",
        "endpoints": {
            "build_world": "POST /api/v1/worlds/build",
            "list_worlds": "GET /api/v1/worlds",
            "get_world": "GET /api/v1/worlds/{world_id}",
            "snapshot": "GET /api/v1/worlds/{world_id}/snapshot",
            "simulate": "POST /api/v1/worlds/{world_id}/simulate",
            "step": "POST /api/v1/worlds/{world_id}/step",
            "timeline": "GET /api/v1/worlds/{world_id}/timeline",
            "intervention": "POST /api/v1/worlds/{world_id}/interventions",
            "chat_world": "POST /api/v1/worlds/{world_id}/chat",
            "chat_agent": "POST /api/v1/worlds/{world_id}/agents/{agent_id}/chat",
            "report": "POST /api/v1/worlds/{world_id}/report",
            "latest_report": "GET /api/v1/worlds/{world_id}/report/latest",
            "build_graph": "POST /api/v1/graph/build",
            "graph_task": "GET /api/v1/graph/tasks/{task_id}",
            "graph_snapshot": "GET /api/v1/graph/{world_id}/snapshot",
            "graph_search": "POST /api/v1/graph/{world_id}/search",
            "graph_entities": "GET /api/v1/graph/{world_id}/entities",
        },
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理异常：{exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "服务器内部错误", "detail": str(exc)},
    )


if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="启动 AgentSociety2 世界仿真后端")
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["critical", "error", "warning", "info", "debug", "trace"],
    )
    args = parser.parse_args()

    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "8001"))
    log_level = args.log_level or os.getenv("BACKEND_LOG_LEVEL", "info")

    if args.log_level:
        os.environ["BACKEND_LOG_LEVEL"] = args.log_level
        _setup_logging()

    logger.info(f"服务启动地址：http://{host}:{port}")
    uvicorn.run(
        "agentsociety2.backend.app:app",
        host=host,
        port=port,
        reload=False,
        log_level=log_level,
    )
