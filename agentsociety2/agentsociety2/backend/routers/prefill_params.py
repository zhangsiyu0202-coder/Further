"""预填充参数查询API路由（只读）

关联文件：
- @packages/agentsociety2/agentsociety2/backend/app.py - 主应用，注册此路由 (/api/v1/prefill-params)
- @extension/src/prefillParamsViewProvider.ts - VSCode插件前端调用此API
- @extension/src/webview/prefillParams/ - 前端展示组件

读取文件：
- {workspace}/.agentsociety/prefill_params.json - 预填充参数配置
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Literal

from fastapi import APIRouter, Query, HTTPException
from fastapi import Path as PathParam

from agentsociety2.logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/prefill-params", tags=["prefill-params"])


def _load_prefill_params_file(workspace_path: str) -> Dict[str, Any]:
    """加载全局预填充参数文件"""
    prefill_file = Path(workspace_path) / ".agentsociety" / "prefill_params.json"

    if not prefill_file.exists():
        return {"version": "1.0", "env_modules": {}, "agents": {}}

    try:
        content = prefill_file.read_text(encoding="utf-8")
        return json.loads(content)
    except Exception as e:
        logger.error(f"加载预填充参数文件失败：{e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"加载预填充参数文件失败：{str(e)}"
        )


@router.get("")
async def get_prefill_params(
    workspace_path: str = Query(..., description="工作区路径"),
) -> Dict[str, Any]:
    """
    获取全局预填充参数（所有类的配置）- 只读

    Returns:
        包含所有预填充参数的字典
    """
    try:
        prefill_params = _load_prefill_params_file(workspace_path)
        return {"success": True, "data": prefill_params}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取预填充参数失败：{e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"获取预填充参数失败：{str(e)}"
        )


@router.get("/{class_kind}/{class_name}")
async def get_class_prefill_params(
    class_kind: Literal["env_module", "agent"] = PathParam(
        ..., description="类类型：env_module 或 agent"
    ),
    class_name: str = PathParam(
        ..., description="类名，如 observation_env, basic_agent"
    ),
    workspace_path: str = Query(..., description="工作区路径"),
) -> Dict[str, Any]:
    """
    获取特定类的预填充参数 - 只读

    Args:
        workspace_path: 工作区路径
        class_kind: 类类型（env_module 或 agent）
        class_name: 类名

    Returns:
        包含特定类预填充参数的字典
    """
    try:
        prefill_params = _load_prefill_params_file(workspace_path)

        # 根据class_kind选择对应的键
        params_key = "env_modules" if class_kind == "env_module" else "agents"
        class_params = prefill_params.get(params_key, {}).get(class_name, {})

        return {
            "success": True,
            "class_kind": class_kind,
            "class_name": class_name,
            "params": class_params,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取类预填充参数失败：{e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"获取类预填充参数失败：{str(e)}"
        )
