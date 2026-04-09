"""健康检查路由：/api/v1/health"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health_check():
    """健康检查接口。"""
    return {"status": "健康", "service": "AgentSociety2 世界仿真后端"}
