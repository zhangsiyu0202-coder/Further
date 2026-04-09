"""报告路由：生成与获取世界报告。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from agentsociety2.backend.models import ReportRequest, ReportResponse
from agentsociety2.backend.services.report_service import ReportService

router = APIRouter(prefix="/api/v1/worlds", tags=["reports"])


def _get_service() -> ReportService:
    from agentsociety2.backend.app import get_report_service
    return get_report_service()


@router.post("/{world_id}/report", response_model=ReportResponse)
async def generate_report(world_id: str, req: ReportRequest) -> ReportResponse:
    """为指定世界生成仿真报告。"""
    service = _get_service()
    result = await service.generate_report(
        world_id=world_id,
        report_type=req.report_type,
        focus=req.focus,
    )
    return ReportResponse(**result)


@router.get("/{world_id}/report/latest", response_model=Dict[str, Any])
def get_latest_report(world_id: str) -> Dict[str, Any]:
    """获取指定世界最近一次生成的报告。"""
    service = _get_service()
    report = service.get_latest_report(world_id)
    if not report:
        raise HTTPException(
            status_code=404, detail=f"未找到世界 {world_id} 的报告"
        )
    return report
