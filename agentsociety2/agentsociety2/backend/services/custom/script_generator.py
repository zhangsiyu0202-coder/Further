"""
安全测试执行器

使用动态导入和反射机制测试自定义模块，避免代码注入风险。

安全设计原则：
1. 使用 importlib 动态导入，而非 exec/eval
2. 使用反射调用类和方法，而非代码拼接
3. 在内存中执行测试，不生成临时脚本文件
4. 验证所有输入，限制可导入的模块路径
"""

import importlib
import inspect
import io
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Dict, Any, List, Optional, Type
from dataclasses import dataclass


@dataclass
class TestResult:
    """单个测试结果"""
    name: str
    success: bool
    output: str
    error: Optional[str] = None


@dataclass
class ModuleTestReport:
    """模块测试报告"""
    success: bool
    results: List[TestResult]
    total_tests: int
    passed_tests: int
    failed_tests: int
    stdout: str
    stderr: str


class SafeModuleTester:
    """安全的模块测试器

    使用动态导入和反射机制，避免代码注入风险。
    """

    # 允许的模块路径前缀（白名单）
    ALLOWED_PATH_PREFIXES = [
        "custom.agents",
        "custom.envs",
        "agentsociety2",
    ]

    def __init__(self, workspace_path: str):
        """
        初始化测试器

        Args:
            workspace_path: 工作区路径
        """
        self.workspace_path = Path(workspace_path).resolve()

        # 确保工作区路径在 sys.path 中（用于加载自定义模块）
        workspace_str = str(self.workspace_path)
        if workspace_str not in sys.path:
            sys.path.insert(0, workspace_str)

    def _validate_module_path(self, module_path: str) -> bool:
        """
        验证模块路径是否在允许的白名单内

        Args:
            module_path: 模块路径

        Returns:
            是否安全
        """
        # 移除 .py 后缀
        clean_path = module_path.replace(".py", "").replace("/", ".")

        # 检查是否在白名单内
        for prefix in self.ALLOWED_PATH_PREFIXES:
            if clean_path.startswith(prefix):
                return True

        return False

    def _safe_import_class(self, module_path: str, class_name: str) -> Optional[Type]:
        """
        安全地导入类

        Args:
            module_path: 模块路径
            class_name: 类名

        Returns:
            类对象，失败返回 None
        """
        # 验证模块路径
        if not self._validate_module_path(module_path):
            raise ValueError(
                f"模块路径不在白名单内: {module_path}. "
                f"允许的前缀: {self.ALLOWED_PATH_PREFIXES}"
            )

        # 验证类名（只允许字母数字和下划线）
        if not class_name.replace("_", "").isalnum():
            raise ValueError(f"类名包含非法字符: {class_name}")

        try:
            # 转换路径格式
            module_import_path = module_path.replace(".py", "").replace("/", ".")

            # 使用 importlib 导入模块
            module = importlib.import_module(module_import_path)

            # 使用 getattr 获取类
            cls = getattr(module, class_name)

            # 验证是类对象
            if not inspect.isclass(cls):
                raise ValueError(f"{class_name} 不是一个类")

            return cls

        except ImportError as e:
            raise ImportError(f"无法导入模块 {module_import_path}: {e}")
        except AttributeError as e:
            raise AttributeError(f"模块中没有类 {class_name}: {e}")

    def _test_agent_class(self, cls: Type, class_name: str) -> TestResult:
        """
        测试 Agent 类

        Args:
            cls: Agent 类
            class_name: 类名

        Returns:
            测试结果
        """
        output_lines = [f"--- 测试 {class_name} ---"]

        try:
            # 检查必需的方法 (AgentBase 定义的抽象方法)
            required_methods = ["ask", "step", "dump", "load"]
            missing_methods = [
                m for m in required_methods if not hasattr(cls, m)
            ]

            if missing_methods:
                output_lines.append(f"✗ 缺少必需方法: {', '.join(missing_methods)}")
                return TestResult(
                    name=class_name,
                    success=False,
                    output="\n".join(output_lines),
                    error=f"缺少必需方法: {missing_methods}"
                )

            # 尝试创建实例
            try:
                agent = cls(id=0, profile={"name": "测试", "personality": "友好"})
                output_lines.append("✓ 创建成功")
            except Exception as e:
                output_lines.append(f"✗ 创建实例失败: {e}")
                return TestResult(
                    name=class_name,
                    success=False,
                    output="\n".join(output_lines),
                    error=str(e)
                )

            # 测试 mcp_description
            if hasattr(agent, "mcp_description"):
                try:
                    desc = agent.mcp_description()
                    output_lines.append(f"✓ mcp_description() 返回 {len(desc)} 字符")
                except Exception:
                    output_lines.append("! mcp_description() 调用失败")

            # 测试方法存在性 (step 是必需的，set_env 可选)
            for method in ["ask", "step", "dump", "load"]:
                if hasattr(agent, method):
                    output_lines.append(f"✓ {method}() 方法存在")

            # 可选方法
            if hasattr(agent, "set_env"):
                output_lines.append("✓ set_env() 方法存在")

            output_lines.append(f"✓ {class_name} 基本测试通过")

            return TestResult(
                name=class_name,
                success=True,
                output="\n".join(output_lines)
            )

        except Exception as e:
            output_lines.append(f"✗ 测试异常: {e}")
            return TestResult(
                name=class_name,
                success=False,
                output="\n".join(output_lines),
                error=str(e)
            )

    def _test_env_class(self, cls: Type, class_name: str) -> TestResult:
        """
        测试环境模块类

        Args:
            cls: 环境模块类
            class_name: 类名

        Returns:
            测试结果
        """
        output_lines = [f"--- 测试 {class_name} ---"]

        try:
            # 尝试创建实例
            try:
                env = cls()
                output_lines.append("✓ 创建成功")
            except Exception as e:
                output_lines.append(f"✗ 创建实例失败: {e}")
                return TestResult(
                    name=class_name,
                    success=False,
                    output="\n".join(output_lines),
                    error=str(e)
                )

            # 测试 mcp_description
            if hasattr(env, "mcp_description"):
                try:
                    desc = env.mcp_description()
                    output_lines.append(f"✓ mcp_description() 返回 {len(desc)} 字符")
                except Exception:
                    output_lines.append("! mcp_description() 调用失败")

            # 测试已注册工具
            if hasattr(env, "_registered_tools"):
                tools = env._registered_tools
                output_lines.append(f"✓ 已注册 {len(tools)} 个工具")
                for tool_name in list(tools)[:5]:  # 最多显示5个
                    output_lines.append(f"  - {tool_name}")

            # 测试必需方法
            for method in ["step", "observe"]:
                if hasattr(env, method):
                    output_lines.append(f"✓ {method}() 方法存在")

            output_lines.append(f"✓ {class_name} 基本测试通过")

            return TestResult(
                name=class_name,
                success=True,
                output="\n".join(output_lines)
            )

        except Exception as e:
            output_lines.append(f"✗ 测试异常: {e}")
            return TestResult(
                name=class_name,
                success=False,
                output="\n".join(output_lines),
                error=str(e)
            )

    def _test_integration(
        self,
        agent_cls: Type,
        agent_name: str,
        env_cls: Type,
        env_name: str
    ) -> TestResult:
        """
        测试 Agent 与环境模块的集成

        Args:
            agent_cls: Agent 类
            agent_name: Agent 类名
            env_cls: 环境模块类
            env_name: 环境模块类名

        Returns:
            测试结果
        """
        output_lines = ["--- 集成测试 ---"]

        try:
            # 创建环境路由 (WorldRouter)
            from agentsociety2.env import WorldRouter
            # 创建环境
            env = env_cls()
            router = WorldRouter([env])
            output_lines.append("✓ 环境路由创建成功")

            # 创建 Agent
            agent = agent_cls(
                id=0,
                profile={"name": "集成测试", "personality": "测试"}
            )
            output_lines.append("✓ Agent 创建成功")

            # 测试环境设置
            if hasattr(agent, "init"):
                try:
                    import asyncio
                    asyncio.run(agent.init(router))
                    output_lines.append("✓ Agent 环境初始化成功")
                except Exception as e:
                    output_lines.append(f"⚠ 环境初始化失败（可能需要 LLM 配置）: {e}")

            output_lines.append("✓ 集成测试通过")

            return TestResult(
                name=f"{agent_name}+{env_name}",
                success=True,
                output="\n".join(output_lines)
            )

        except Exception as e:
            output_lines.append(f"✗ 集成测试失败: {e}")
            return TestResult(
                name=f"{agent_name}+{env_name}",
                success=False,
                output="\n".join(output_lines),
                error=str(e)
            )

    async def run_test(self, scan_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行测试

        Args:
            scan_result: 扫描结果

        Returns:
            测试结果字典
        """
        agents = scan_result.get("agents", [])
        envs = scan_result.get("envs", [])

        if not agents and not envs:
            return {
                "success": False,
                "error": "未发现任何自定义模块",
                "stdout": "",
                "returncode": -1,
            }

        # 捕获输出
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        results = []
        all_output = []

        try:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                all_output.append("=" * 50)
                all_output.append("开始测试自定义模块")
                all_output.append("=" * 50)

                # 测试 Agents
                if agents:
                    all_output.append("\n测试 Agent")
                    all_output.append("-" * 30)

                    for agent_info in agents:
                        module_path = agent_info.get("module_path", "")
                        class_name = agent_info.get("class_name", "")

                        if not module_path or not class_name:
                            continue

                        try:
                            cls = self._safe_import_class(module_path, class_name)
                            if cls is None:
                                raise ValueError(f"无法导入类 {class_name}")
                            result = self._test_agent_class(cls, class_name)
                            results.append(result)
                            all_output.append(result.output)
                        except Exception as e:
                            all_output.append(f"✗ {class_name}: {e}")
                            results.append(TestResult(
                                name=class_name,
                                success=False,
                                output=f"✗ {class_name}",
                                error=str(e)
                            ))

                # 测试环境模块
                if envs:
                    all_output.append("\n测试环境模块")
                    all_output.append("-" * 30)

                    for env_info in envs:
                        module_path = env_info.get("module_path", "")
                        class_name = env_info.get("class_name", "")

                        if not module_path or not class_name:
                            continue

                        try:
                            cls = self._safe_import_class(module_path, class_name)
                            if cls is None:
                                raise ValueError(f"无法导入类 {class_name}")
                            result = self._test_env_class(cls, class_name)
                            results.append(result)
                            all_output.append(result.output)
                        except Exception as e:
                            all_output.append(f"✗ {class_name}: {e}")
                            results.append(TestResult(
                                name=class_name,
                                success=False,
                                output=f"✗ {class_name}",
                                error=str(e)
                            ))

                # 集成测试
                if agents and envs:
                    all_output.append("\n集成测试")
                    all_output.append("-" * 30)

                    try:
                        agent_info = agents[0]
                        env_info = envs[0]

                        agent_cls = self._safe_import_class(
                            agent_info.get("path", "") or agent_info.get("module_path", ""),
                            agent_info.get("class_name", "")
                        )
                        env_cls = self._safe_import_class(
                            env_info.get("path", "") or env_info.get("module_path", ""),
                            env_info.get("class_name", "")
                        )

                        if agent_cls is None:
                            raise ValueError(f"无法导入 Agent 类")
                        if env_cls is None:
                            raise ValueError(f"无法导入环境类")

                        result = self._test_integration(
                            agent_cls,
                            agent_info.get("class_name", ""),
                            env_cls,
                            env_info.get("class_name", "")
                        )
                        results.append(result)
                        all_output.append(result.output)

                    except Exception as e:
                        all_output.append(f"✗ 集成测试: {e}")

                all_output.append("\n" + "=" * 50)
                all_output.append("测试完成")
                all_output.append("=" * 50)

            stderr_content = stderr_buffer.getvalue()
            full_output = "\n".join(all_output)

            # 统计结果
            passed = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)

            return {
                "success": failed == 0,
                "stdout": full_output,
                "stderr": stderr_content,
                "returncode": 0 if failed == 0 else 1,
                "results": [
                    {
                        "name": r.name,
                        "success": r.success,
                        "output": r.output,
                        "error": r.error,
                    }
                    for r in results
                ],
                "total_tests": len(results),
                "passed_tests": passed,
                "failed_tests": failed,
                "error": None if failed == 0 else f"{failed} 个测试失败",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "\n".join(all_output),
                "stderr": stderr_buffer.getvalue(),
                "returncode": -1,
            }


# 保持向后兼容的别名
ScriptGenerator = SafeModuleTester
