"""
代码执行器API
"""

import json
import uuid
from datetime import datetime
from typing import Optional

from agentsociety2.code_executor.code_executor import CodeExecutor
from agentsociety2.code_executor.code_generator import CodeGenerator
from agentsociety2.code_executor.code_saver import CodeSaver
from agentsociety2.code_executor.dependency_detector import DependencyDetector
from agentsociety2.code_executor.models import (
    CodeGenerationRequest,
    CodeGenerationResponse,
    ExecutionResult,
)

from agentsociety2.code_executor.path_config import PathConfig
from agentsociety2.code_executor.runtime_config import DockerRuntimeConfig
from agentsociety2.logger import get_logger

logger = get_logger()


class CodeExecutorAPI:
    """
    代码执行器API

    提供完整的代码生成和执行流程：
    1. AI 代码生成
    2. 智能依赖检测
    3. 代码保存
    4. Docker Sandbox执行（按需安装缺失依赖）
    """

    def __init__(
        self,
        path_config: Optional[PathConfig] = None,
        docker_config: Optional[DockerRuntimeConfig] = None,
    ):
        """
        初始化代码执行器API

        Args:
            config: LLM配置，包含模型列表等信息
            model_name: 用于代码生成的模型名称
            path_config: 路径配置对象。如果为None，将尝试从环境变量创建，否则使用默认配置。
        """
        if path_config is None:
            path_config = PathConfig.from_env()
            if path_config.work_dir is None and path_config.default_save_dir is None:
                path_config = PathConfig.default()

        self._path_config = path_config
        self._docker_config = docker_config or DockerRuntimeConfig.from_env()
        self._log_dir = self._path_config.get_log_dir()

        self._code_generator = CodeGenerator()
        self._dependency_detector = DependencyDetector()
        self._executor = CodeExecutor(
            work_dir=self._path_config.get_work_dir(),
            docker_config=self._docker_config,
            artifacts_dir=self._path_config.get_artifacts_dir(),
        )
        self._code_saver = CodeSaver(path_config)

        logger.info("CodeExecutorAPI初始化完成")

    async def generate_and_execute(
        self,
        request: CodeGenerationRequest,
        *,
        timeout: int = 300,
        input_data: Optional[str] = None,
        extra_files: Optional[list[str]] = None,
        program_args: Optional[list[str]] = None,
    ) -> CodeGenerationResponse:
        """
        生成代码并在 Docker 沙箱中执行。

        Args:
            request: 代码生成请求

        Returns:
            代码生成响应，包含生成的代码、执行结果等信息
        """
        task_id = str(uuid.uuid4())[:8]

        logger.info(f"开始处理任务 {task_id}: {request.description[:50]}...")

        try:
            logger.info("步骤1: AI代码生成")
            generated_code = await self._code_generator.generate(
                description=request.description,
                input_files=request.input_files,
                additional_context=request.additional_context,
            )

            logger.info("步骤2: 智能依赖检测")
            detected_dependencies = self._dependency_detector.detect(generated_code)
            logger.info(f"检测到依赖: {detected_dependencies}")

            saved_path = None
            logger.info("步骤3: 代码保存")
            if request.save_path:
                saved_path = self._code_saver.save(
                    generated_code,
                    save_path=request.save_path,
                    unique_id=task_id,
                )
            else:
                saved_path = self._code_saver.save(
                    generated_code,
                    unique_id=task_id,
                )

            # 4. 代码执行（始终执行）
            logger.info("步骤4: 代码执行")
            execution_result = await self._executor.execute(
                generated_code,
                dependencies=detected_dependencies,
                timeout=timeout,
                input_data=input_data,
                extra_files=extra_files,
                program_args=program_args,
            )

            response = CodeGenerationResponse(
                generated_code=generated_code,
                detected_dependencies=detected_dependencies,
                execution_result=execution_result,
                saved_path=saved_path,
            )

            self._write_work_log(
                task_id=task_id,
                request=request,
                detected_dependencies=detected_dependencies,
                execution_result=execution_result,
                saved_path=saved_path,
            )

            logger.info(f"任务 {task_id} 处理完成")
            return response

        except Exception as e:
            logger.error(f"任务 {task_id} 处理失败: {e}")
            raise

    async def close(self) -> None:
        """
        关闭API，清理资源
        """

        logger.info("CodeExecutorAPI已关闭")

    def _write_work_log(
        self,
        *,
        task_id: str,
        request: CodeGenerationRequest,
        detected_dependencies: list[str],
        execution_result: Optional["ExecutionResult"],
        saved_path: Optional[str],
    ) -> None:
        """
        将完整的工作日志写入日志目录
        """
        log_entry = {
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat(),
            "request": request.model_dump(),
            "detected_dependencies": detected_dependencies,
            "execution_result": (
                execution_result.model_dump() if execution_result else None
            ),
            "saved_path": saved_path,
        }

        log_file = (
            self._log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}.json"
        )

        try:
            with open(log_file, "w", encoding="utf-8") as fp:
                json.dump(log_entry, fp, ensure_ascii=False, indent=2)
            logger.info("工作日志已保存: %s", log_file)
        except Exception as exc:
            logger.warning("保存工作日志失败: %s", exc)
