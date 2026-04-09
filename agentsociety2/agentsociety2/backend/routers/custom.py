"""
自定义模块 API 路由

提供扫描、清理、测试自定义模块的 API 端点。

关联文件：
- @extension/src/projectStructureProvider.ts - 前端项目结构视图（调用此API）
- @extension/src/apiClient.ts - API客户端

API端点：
- POST /api/v1/custom/scan - 扫描自定义模块并生成JSON配置
- POST /api/v1/custom/clean - 清理自定义模块配置
- POST /api/v1/custom/test - 测试自定义模块
- GET /api/v1/custom/list - 列出已注册的自定义模块
- GET /api/v1/custom/status - 获取自定义模块状态

内部服务：
- @packages/agentsociety2/agentsociety2/backend/services/custom/scanner.py - 模块扫描
- @packages/agentsociety2/agentsociety2/backend/services/custom/generator.py - JSON生成
- @packages/agentsociety2/agentsociety2/registry/ - 模块注册表
"""

from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import sys
import json
import importlib.util

# 添加工作区路径以确保可以导入自定义模块
workspace_path = os.getenv("WORKSPACE_PATH", "")
if workspace_path:
    workspace_abs_path = os.path.abspath(workspace_path)
    if workspace_abs_path not in sys.path:
        sys.path.insert(0, workspace_abs_path)

# agentsociety2 是一个 Python 包，通过 import 使用
from agentsociety2.backend.services.custom.scanner import CustomModuleScanner
from agentsociety2.backend.services.custom.generator import CustomModuleJsonGenerator
from agentsociety2.backend.services.custom.script_generator import ScriptGenerator
from agentsociety2.registry import (
    get_registered_env_modules,
    get_registered_agent_modules,
    get_registry,
    scan_and_register_custom_modules,
)
from agentsociety2.logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/custom", tags=["custom"])


# ========== 请求/响应模型 ==========


class ScanRequest(BaseModel):
    """扫描请求"""

    workspace_path: Optional[str] = Field(
        None, description="工作区路径，不提供则使用环境变量"
    )


class ScanResponse(BaseModel):
    """扫描响应"""

    success: bool
    agents_found: int
    envs_found: int
    agents_generated: int
    envs_generated: int
    errors: List[str]
    message: Optional[str] = None


class CleanResponse(BaseModel):
    """清理响应"""

    success: bool
    removed_count: int
    message: str


class TestRequest(BaseModel):
    """测试请求"""

    workspace_path: Optional[str] = Field(
        None, description="工作区路径，不提供则使用环境变量"
    )
    module_kind: Optional[str] = Field(
        None, description="模块类型: 'agent' 或 'env_module'，不提供则测试所有"
    )
    module_class_name: Optional[str] = Field(
        None, description="要测试的类名，与 module_kind 配合使用"
    )


class ModuleTestResult(BaseModel):
    """单个模块测试结果"""
    name: str
    success: bool
    output: str
    error: Optional[str] = None


class TestResponse(BaseModel):
    """测试响应"""

    success: bool
    test_output: str
    error: Optional[str] = None
    returncode: Optional[int] = None
    # 结构化测试结果
    results: List[ModuleTestResult] = []
    total_tests: Optional[int] = None
    passed_tests: Optional[int] = None
    failed_tests: Optional[int] = None


class ListResponse(BaseModel):
    """列表响应"""

    success: bool
    agents: List[Dict[str, Any]]
    envs: List[Dict[str, Any]]
    total_agents: int
    total_envs: int


# ========== API 端点 ==========


@router.post("/scan", response_model=ScanResponse)
async def scan_custom_modules(request: ScanRequest):
    """
    扫描自定义模块并注册到内存

    此接口会：
    1. 扫描 custom/agents/ 和 custom/envs/ 目录（跳过 examples/）
    2. 验证发现的模块
    3. 将模块直接注册到内存中的 registry（不生成 JSON 文件）
    4. 返回扫描结果
    """
    workspace_path = request.workspace_path or os.getenv("WORKSPACE_PATH")
    if not workspace_path:
        raise HTTPException(
            status_code=400,
            detail="Workspace path not provided. Set WORKSPACE_PATH env var or pass in request.",
        )

    try:
        logger.info(f"[Custom Modules] Starting scan of workspace: {workspace_path}")

        # 扫描自定义模块
        scanner = CustomModuleScanner(workspace_path)
        scan_result = scanner.scan_all()

        logger.info(f"[Custom Modules] Scan complete: {len(scan_result['agents'])} agents, {len(scan_result['envs'])} envs found")

        # 直接注册到内存，不生成 JSON 文件
        registry = get_registry()

        # 清除旧的自定义模块
        registry.clear_custom_modules()

        # 注册环境模块
        for env_info in scan_result.get("envs", []):
            try:
                spec = importlib.util.spec_from_file_location(
                    f"custom_env_{env_info['type']}", env_info["file_path"]
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[f"custom_env_{env_info['type']}"] = module
                    spec.loader.exec_module(module)

                    env_class = getattr(module, env_info["class_name"])
                    env_class._is_custom = True

                    module_type = env_info["class_name"]
                    registry.register_env_module(module_type, env_class, is_custom=True)
                    logger.info(f"[Custom Modules] Registered env module: {module_type} from {env_info['file_path']}")
            except Exception as e:
                logger.error(f"[自定义模块] 注册环境模块失败 {env_info.get('type')}: {e}")
                scan_result["errors"].append(f"Env module {env_info.get('type')}: {str(e)}")

        # 注册 Agent
        for agent_info in scan_result.get("agents", []):
            try:
                spec = importlib.util.spec_from_file_location(
                    f"custom_agent_{agent_info['type']}", agent_info["file_path"]
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[f"custom_agent_{agent_info['type']}"] = module
                    spec.loader.exec_module(module)

                    agent_class = getattr(module, agent_info["class_name"])
                    agent_class._is_custom = True

                    module_type = agent_info["class_name"]
                    registry.register_agent_module(module_type, agent_class, is_custom=True)
                    logger.info(f"[Custom Modules] Registered agent: {module_type} from {agent_info['file_path']}")
            except Exception as e:
                logger.error(f"[自定义模块] 注册智能体失败 {agent_info.get('type')}: {e}")
                scan_result["errors"].append(f"Agent {agent_info.get('type')}: {str(e)}")

        message_parts = []
        agents_count = len([a for a in scan_result.get("agents", []) if "Failed" not in str(scan_result.get("errors", []))])
        envs_count = len([e for e in scan_result.get("envs", []) if "Failed" not in str(scan_result.get("errors", []))])

        if agents_count > 0:
            message_parts.append(f"发现 {agents_count} 个 Agent")
        if envs_count > 0:
            message_parts.append(f"发现 {envs_count} 个环境模块")

        if not message_parts:
            message = "未发现任何自定义模块"
        else:
            message = "、".join(message_parts) + "，已注册到内存"

        logger.info(f"[Custom Modules] Scan complete: {message}")

        return ScanResponse(
            success=True,
            agents_found=len(scan_result["agents"]),
            envs_found=len(scan_result["envs"]),
            agents_generated=agents_count,
            envs_generated=envs_count,
            errors=scan_result.get("errors", []),
            message=message,
        )

    except Exception as e:
        logger.error(f"[Custom Modules] Scan failed: {e}")
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@router.post("/clean", response_model=CleanResponse)
async def clean_custom_modules(request: ScanRequest):
    """
    清理自定义模块的 JSON 配置

    删除所有标记为 is_custom=true 的 JSON 配置文件。
    """
    workspace_path = request.workspace_path or os.getenv("WORKSPACE_PATH")
    if not workspace_path:
        raise HTTPException(
            status_code=400,
            detail="Workspace path not provided. Set WORKSPACE_PATH env var or pass in request.",
        )

    try:
        generator = CustomModuleJsonGenerator(workspace_path)
        count = generator.remove_custom_modules()

        return CleanResponse(
            success=True,
            removed_count=count,
            message=f"已清理 {count} 个自定义模块配置",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}")


@router.post("/test", response_model=TestResponse)
async def test_custom_modules(request: TestRequest):
    """
    测试自定义模块

    此接口会：
    1. 扫描 custom/ 目录（如果指定了模块类型和类名，则只测试指定模块）
    2. 运行测试
    3. 返回测试结果

    参数：
    - module_kind: 模块类型 ('agent' 或 'env_module')
    - module_class_name: 要测试的类名
    - 如果不提供这两个参数，则测试所有模块
    """
    workspace_path = request.workspace_path or os.getenv("WORKSPACE_PATH")
    if not workspace_path:
        raise HTTPException(
            status_code=400,
            detail="Workspace path not provided. Set WORKSPACE_PATH env var or pass in request.",
        )

    module_kind = request.module_kind
    module_class_name = request.module_class_name

    try:
        # 记录测试请求
        if module_kind and module_class_name:
            logger.info(f"[Custom Modules] Testing specific module: {module_kind}.{module_class_name}")
        else:
            logger.info(f"[Custom Modules] Starting test of workspace: {workspace_path}")

        # 先扫描模块
        scanner = CustomModuleScanner(workspace_path)
        scan_result = scanner.scan_all()

        # 根据参数过滤要测试的模块
        if module_kind and module_class_name:
            filtered_agents = []
            filtered_envs = []

            if module_kind == "agent":
                for agent_info in scan_result.get("agents", []):
                    if agent_info.get("class_name") == module_class_name:
                        filtered_agents.append(agent_info)
                        logger.info(f"[Custom Modules] Found agent to test: {module_class_name}")
            elif module_kind == "env_module":
                for env_info in scan_result.get("envs", []):
                    if env_info.get("class_name") == module_class_name:
                        filtered_envs.append(env_info)
                        logger.info(f"[Custom Modules] Found env to test: {module_class_name}")

            # 更新 scan_result 只包含要测试的模块
            scan_result["agents"] = filtered_agents
            scan_result["envs"] = filtered_envs

            # 如果没找到指定模块
            if not filtered_agents and not filtered_envs:
                logger.warning(f"[Custom Modules] 未找到模块：{module_kind}.{module_class_name}")
                return TestResponse(
                    success=False,
                    test_output="",
                    error=f"未找到指定的模块: {module_class_name}",
                    results=[],
                    total_tests=0,
                    passed_tests=0,
                    failed_tests=0,
                )

        agents = scan_result.get("agents", [])
        envs = scan_result.get("envs", [])

        logger.info(f"[Custom Modules] Test scan found: {len(agents)} agents, {len(envs)} envs")

        if not agents and not envs:
            logger.warning("[Custom Modules] No custom modules found for testing")
            return TestResponse(
                success=False,
                test_output="",
                error="未发现任何自定义模块，请先在 custom/ 目录下创建模块",
                results=[],
                total_tests=0,
                passed_tests=0,
                failed_tests=0,
            )

        # 生成并运行测试
        builder = ScriptGenerator(workspace_path)
        result = await builder.run_test(scan_result)

        # 记录每个模块的测试结果
        for module_result in result.get("results", []):
            status = "PASSED" if module_result["success"] else "FAILED"
            logger.info(f"[Custom Modules] Test {status}: {module_result['name']}")
            if module_result.get("error"):
                logger.error(f"[Custom Modules] Test error for {module_result['name']}: {module_result['error']}")

        output = result.get("stdout", "")
        stderr = result.get("stderr", "")
        if stderr:
            output = output + "\n--- 错误输出 ---\n" + stderr if output else stderr

        # 记录总体测试结果
        total = result.get("total_tests", 0)
        passed = result.get("passed_tests", 0)
        failed = result.get("failed_tests", 0)
        logger.info(f"[Custom Modules] Test complete: {passed}/{total} passed, {failed} failed")

        return TestResponse(
            success=result["success"],
            test_output=output,
            error=result.get("error"),
            returncode=result.get("returncode"),
            results=[ModuleTestResult(**r) for r in result.get("results", [])],
            total_tests=result.get("total_tests"),
            passed_tests=result.get("passed_tests"),
            failed_tests=result.get("failed_tests"),
        )

    except Exception as e:
        logger.error(f"[Custom Modules] Test failed: {e}")
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")


@router.get("/list", response_model=ListResponse)
async def list_custom_modules():
    """
    列出当前已注册的自定义模块

    返回所有 is_custom=true 的模块信息（从内存注册表中读取）。
    """
    try:
        registry = get_registry()
        result = {"agents": [], "envs": []}

        # 从注册表获取自定义 Agent
        for agent_type, agent_class in get_registered_agent_modules():
            if getattr(agent_class, "_is_custom", False):
                try:
                    description = agent_class.mcp_description()
                except Exception:
                    description = f"{agent_class.__name__}: {agent_class.__doc__ or '暂无说明'}"

                result["agents"].append({
                    "type": agent_type,
                    "class_name": agent_class.__name__,
                    "description": description,
                    "is_custom": True,
                })

        # 从注册表获取自定义环境模块
        for module_type, env_class in get_registered_env_modules():
            if getattr(env_class, "_is_custom", False):
                try:
                    description = env_class.mcp_description()
                except Exception:
                    description = f"{env_class.__name__}: {env_class.__doc__ or '暂无说明'}"

                result["envs"].append({
                    "type": module_type,
                    "class_name": env_class.__name__,
                    "description": description,
                    "is_custom": True,
                })

        return ListResponse(
            success=True,
            agents=result["agents"],
            envs=result["envs"],
            total_agents=len(result["agents"]),
            total_envs=len(result["envs"]),
        )
    except Exception as e:
        logger.error(f"[Custom Modules] List failed: {e}")
        raise HTTPException(status_code=500, detail=f"列表获取失败: {str(e)}")


@router.get("/status")
async def get_custom_modules_status():
    """
    获取自定义模块状态概览
    """
    workspace_path = os.getenv("WORKSPACE_PATH")
    if not workspace_path:
        raise HTTPException(status_code=400, detail="Workspace path not set")

    from pathlib import Path

    custom_dir = Path(workspace_path) / "custom"
    agent_classes_dir = Path(workspace_path) / ".agentsociety/agent_classes"
    env_modules_dir = Path(workspace_path) / ".agentsociety/env_modules"

    status = {
        "custom_dir_exists": custom_dir.exists(),
        "agents_dir_exists": (custom_dir / "agents").exists(),
        "envs_dir_exists": (custom_dir / "envs").exists(),
        "agent_files_count": 0,
        "env_files_count": 0,
        "registered_agents": 0,
        "registered_envs": 0,
    }

    # 统计自定义代码文件
    if status["agents_dir_exists"]:
        status["agent_files_count"] = len(
            [
                f
                for f in (custom_dir / "agents").rglob("*.py")
                if not f.name.startswith("__") and "examples" not in f.parts
            ]
        )

    if status["envs_dir_exists"]:
        status["env_files_count"] = len(
            [
                f
                for f in (custom_dir / "envs").rglob("*.py")
                if not f.name.startswith("__") and "examples" not in f.parts
            ]
        )

    # 统计已注册的模块（从内存注册表中读取）
    try:
        registry = get_registry()
        for agent_type, agent_class in get_registered_agent_modules():
            if getattr(agent_class, "_is_custom", False):
                status["registered_agents"] += 1

        for module_type, env_class in get_registered_env_modules():
            if getattr(env_class, "_is_custom", False):
                status["registered_envs"] += 1
    except Exception as e:
        logger.warning(f"[自定义模块] 统计已注册模块数量失败：{e}")

    return status


@router.get("/classes")
async def list_available_classes(
    workspace_path: str = Query(..., description="工作区路径"),
    include_custom: bool = Query(True, description="是否包含自定义模块"),
) -> Dict[str, Any]:
    """
    列出所有可用的Agent类和Env Module类

    Returns:
        包含可用类列表的字典
    """
    try:
        registry = get_registry()

        # 扫描自定义模块（如果请求）
        if include_custom:
            try:
                scan_and_register_custom_modules(Path(workspace_path), registry)
            except Exception as e:
                logger.warning(f"扫描自定义模块失败：{e}")

        # 获取所有已注册的Agent类
        agents = {}
        for agent_type, agent_class in get_registered_agent_modules():
            try:
                description = agent_class.mcp_description()
            except Exception:
                description = f"{agent_class.__name__}: {agent_class.__doc__ or '暂无说明'}"

            agents[agent_type] = {
                "type": agent_type,
                "class_name": agent_class.__name__,
                "description": description,
                "is_custom": getattr(agent_class, "_is_custom", False),
            }

        # 获取所有已注册的Env Module类
        env_modules = {}
        for module_type, env_class in get_registered_env_modules():
            try:
                description = env_class.mcp_description()
            except Exception:
                description = f"{env_class.__name__}: {env_class.__doc__ or '暂无说明'}"

            env_modules[module_type] = {
                "type": module_type,
                "class_name": env_class.__name__,
                "description": description,
                "is_custom": getattr(env_class, "_is_custom", False),
            }

        # 加载预填充参数，标记哪些类已配置
        prefill_file = Path(workspace_path) / ".agentsociety" / "prefill_params.json"
        env_prefill = {}
        agent_prefill = {}

        if prefill_file.exists():
            try:
                with open(prefill_file, "r", encoding="utf-8") as f:
                    prefill_params = json.load(f)
                    env_prefill = prefill_params.get("env_modules", {})
                    agent_prefill = prefill_params.get("agents", {})
            except Exception as e:
                logger.warning(f"加载预填充参数失败：{e}")

        # 为每个类添加是否已配置的标记
        for module_type in env_modules:
            env_modules[module_type]["has_prefill"] = (
                module_type in env_prefill and bool(env_prefill[module_type])
            )

        for agent_type in agents:
            agents[agent_type]["has_prefill"] = agent_type in agent_prefill and bool(
                agent_prefill[agent_type]
            )

        return {
            "success": True,
            "env_modules": env_modules,
            "agents": agents,
            "env_module_count": len(env_modules),
            "agent_count": len(agents),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"列出可用类失败：{e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"列出可用类失败：{str(e)}"
        )


@router.post("/rescan")
async def rescan_custom_modules(
    workspace_path: str = Query(..., description="工作区路径"),
) -> Dict[str, Any]:
    """
    重新扫描自定义模块

    Returns:
        扫描结果
    """
    try:
        registry = get_registry()

        # 清除旧的自定义模块
        registry.clear_custom_modules()

        # 扫描新的自定义模块
        scan_result = scan_and_register_custom_modules(Path(workspace_path), registry)

        return {
            "success": True,
            "scan_result": scan_result,
            "message": f"已扫描 {len(scan_result.get('envs', []))} 个环境模块和 "
            f"{len(scan_result.get('agents', []))} 个智能体",
        }
    except Exception as e:
        logger.error(f"重新扫描自定义模块失败：{e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"重新扫描自定义模块失败：{str(e)}"
        )
