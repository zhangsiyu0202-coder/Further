"""
WorldRouter: Default router for LLM-driven virtual world simulation.

职责：
- 继承 RouterBase，作为新系统的默认路由
- 使用结构化工具调用（JSON schema + function calling）处理 Agent 指令
- 明确禁止生成/执行 Python 代码
- 支持 observation → tool selection → tool call → summary 流程
"""

import json
from typing import Tuple, Dict, Any, List, Optional, Literal
from litellm import AllMessageValues
from openai.types.chat import ChatCompletionToolParam

from agentsociety2.logger import get_logger
from agentsociety2.env.base import EnvBase
from agentsociety2.env.router_base import RouterBase

__all__ = ["WorldRouter"]


class WorldRouter(RouterBase):
    """
    WorldRouter: Default router for pure LLM-driven virtual world simulation.

    工作流程：
    1. 收集所有环境模块的工具信息（仅结构化调用，禁止代码生成）
    2. 使用 LLM function calling 选择并调用工具
    3. 汇总工具执行结果，生成自然语言答案

    禁止：
    - 生成 Python 代码
    - eval/exec 任意代码
    """

    def __init__(
        self,
        env_modules: list[EnvBase],
        router_role: Literal["agent", "operator"] = "agent",
        max_steps: int = 10,
        max_llm_call_retry: int = 10,
    ):
        super().__init__(
            env_modules=env_modules,
            max_steps=max_steps,
            max_llm_call_retry=max_llm_call_retry,
        )
        self.router_role = router_role

        self._all_tools: List[ChatCompletionToolParam] = []
        self._all_readonly_tools: List[ChatCompletionToolParam] = []
        self._tool_name_to_module: Dict[str, EnvBase] = {}
        self._tool_name_to_tool_obj: Dict[str, Any] = {}

        self._collect_all_tools()
        self._set_status_tool_schema = self._create_set_status_tool_schema()

    def _classify_tool_error(self, tool_name: str, error: Exception) -> str:
        """Classify tool errors to control UI exposure and routing severity."""
        error_text = str(error).lower()

        if (
            "no posts found" in error_text
            or "no data found" in error_text
            or "not found for topic" in error_text
            or "no messages found" in error_text
            or "no feed items" in error_text
        ):
            return "expected_empty"

        if (
            "not found" in error_text
            or "invalid json arguments" in error_text
            or "readonly mode is enabled" in error_text
        ):
            return "soft_fail"

        return "hard_fail"

    def _collect_all_tools(self) -> None:
        """收集所有环境模块的结构化工具"""
        for module in self.env_modules:
            registered_tools = getattr(module.__class__, "_registered_tools", {})
            for tool_name, tool_obj in registered_tools.items():
                tool_schema: Optional[ChatCompletionToolParam] = None
                for llm_tool in module._llm_tools:
                    if llm_tool["function"]["name"] == tool_name:
                        tool_schema = llm_tool
                        break
                if tool_schema:
                    self._all_tools.append(tool_schema)
                    self._tool_name_to_module[tool_name] = module
                    self._tool_name_to_tool_obj[tool_name] = tool_obj

                    readonly_tools = getattr(module.__class__, "_readonly_tools", {})
                    if readonly_tools.get(tool_name, False):
                        self._all_readonly_tools.append(tool_schema)

    def _create_set_status_tool_schema(self) -> ChatCompletionToolParam:
        """创建 set_status 控制工具的 schema"""
        return {
            "type": "function",
            "function": {
                "name": "set_status",
                "description": (
                    "Set the execution status for the current task. "
                    "Call this when you have completed the task or determined the outcome."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["success", "in_progress", "fail", "error"],
                            "description": (
                                "success: completed; in_progress: still running; "
                                "fail: cannot complete; error: exception occurred"
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": "Optional explanation for fail/error status",
                        },
                    },
                    "required": ["status"],
                },
            },
        }

    async def ask(
        self,
        ctx: dict,
        instruction: str,
        readonly: bool = False,
        template_mode: bool = False,
    ) -> Tuple[dict, str]:
        """
        主入口：使用结构化工具调用处理 Agent 指令。

        Args:
            ctx: 上下文字典（包含 world state 相关信息）
            instruction: Agent 指令字符串
            readonly: 是否只读模式
            template_mode: 是否模板模式（变量替换）

        Returns:
            (ctx, answer) 元组
        """
        self._add_current_time_to_ctx(ctx)

        if template_mode:
            variables = ctx.get("variables", {})
            try:
                instruction = instruction.format(**variables)
            except KeyError as e:
                get_logger().warning(f"WorldRouter: template variable missing: {e}")

        get_logger().info(
            f"WorldRouter: Processing instruction: {instruction[:100]!r}, readonly={readonly}"
        )

        if not self.env_modules:
            return (
                {"status": "fail", "reason": "No environment modules available"},
                "No environment modules available to handle the request.",
            )

        available_tools = self._all_readonly_tools if readonly else self._all_tools

        if not available_tools:
            return (
                {"status": "fail", "reason": "No available tools"},
                "No available tools to handle the request.",
            )

        initial_prompt = self._build_initial_prompt(instruction, ctx, readonly)
        dialog: List[AllMessageValues] = [{"role": "user", "content": initial_prompt}]
        tools_with_status = available_tools + [self._set_status_tool_schema]

        step_count = 0
        results: dict = {}
        execution_log: List[Dict[str, Any]] = []
        status = "success"
        error: Optional[str] = None

        while step_count < self.max_steps:
            step_count += 1
            get_logger().debug(f"WorldRouter: Step {step_count}/{self.max_steps}")

            try:
                tools_for_call = tools_with_status if step_count == 1 else None
                call_kwargs: dict = {
                    "model": "coder",
                    "messages": dialog,
                }
                if tools_for_call:
                    call_kwargs["tools"] = tools_for_call
                    call_kwargs["tool_choice"] = "auto"

                response = await self.acompletion_with_system_prompt(**call_kwargs)
            except Exception as e:
                get_logger().error(f"WorldRouter: LLM call failed: {e}")
                status = "error"
                error_msg = str(e)
                results["status"] = status
                results["error"] = error_msg
                process_text = json.dumps(execution_log, indent=2, default=str)
                final_answer, determined_status = await self.generate_final_answer(
                    ctx, instruction, results, process_text, status, error_msg
                )
                results["status"] = determined_status
                return results, final_answer

            message = response.choices[0].message  # type: ignore
            tool_calls = getattr(message, "tool_calls", None) or []
            assistant_content = message.content or ""

            execution_log.append(
                {
                    "step": step_count,
                    "type": "assistant_response",
                    "content": assistant_content,
                    "tool_calls_count": len(tool_calls),
                }
            )

            dialog.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ]
                    if tool_calls
                    else None,
                }
            )

            if not tool_calls:
                get_logger().info(f"WorldRouter: Task complete after {step_count} steps")
                process_text = json.dumps(execution_log, indent=2, default=str)
                final_answer, determined_status = await self.generate_final_answer(
                    ctx, instruction, results, process_text, status, error
                )
                results["status"] = determined_status
                if error:
                    results["error"] = error
                return results, final_answer

            tool_results = []
            step_tool_calls = []
            for tool_call in tool_calls:
                func_name = tool_call.function.name
                func_args_str = tool_call.function.arguments

                try:
                    func_args = json.loads(func_args_str)
                except json.JSONDecodeError as e:
                    error_result = {"error": f"Invalid JSON arguments: {e}"}
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": func_name,
                            "content": json.dumps(error_result),
                        }
                    )
                    step_tool_calls.append(
                        {
                            "tool": func_name,
                            "arguments": func_args_str,
                            "result": error_result,
                            "success": False,
                        }
                    )
                    continue

                if func_name == "set_status":
                    status = func_args.get("status", "unknown")
                    reason = func_args.get("reason", "")
                    results["status"] = status
                    if reason:
                        results["reason"] = reason
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": func_name,
                            "content": json.dumps(
                                {"status": status, "message": "Status set successfully"}
                            ),
                        }
                    )
                    step_tool_calls.append(
                        {
                            "tool": func_name,
                            "arguments": func_args,
                            "result": {"status": status},
                            "success": True,
                        }
                    )
                    get_logger().info(f"WorldRouter: Status set to {status}")
                    continue

                try:
                    result = await self._execute_tool(func_name, func_args, readonly)
                    result_str = json.dumps(result, default=str)
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": func_name,
                            "content": result_str,
                        }
                    )
                    results[func_name] = result
                    step_tool_calls.append(
                        {
                            "tool": func_name,
                            "arguments": func_args,
                            "result": result,
                            "success": True,
                        }
                    )
                    get_logger().debug(
                        f"WorldRouter: Tool {func_name} returned: {result_str[:200]}"
                    )
                except Exception as e:
                    error_msg = f"Error executing {func_name}: {e}"
                    error_class = self._classify_tool_error(func_name, e)
                    log_fn = (
                        get_logger().warning
                        if error_class in {"expected_empty", "soft_fail"}
                        else get_logger().error
                    )
                    log_fn(f"WorldRouter: {error_msg} [class={error_class}]")
                    error_result = {
                        "error": f"Tool '{func_name}' execution failed",
                        "error_class": error_class,
                    }
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": func_name,
                            "content": json.dumps(error_result),
                        }
                    )
                    step_tool_calls.append(
                        {
                            "tool": func_name,
                            "arguments": func_args,
                            "result": {"error": "suppressed_in_ui", "error_class": error_class},
                            "success": False,
                        }
                    )
                    if error_class == "hard_fail":
                        status = "fail"
                        error = f"Tool '{func_name}' execution failed"

            execution_log.append(
                {
                    "step": step_count,
                    "type": "tool_execution",
                    "tool_calls": step_tool_calls,
                }
            )
            dialog.extend(tool_results)

        get_logger().warning(f"WorldRouter: Reached max steps ({self.max_steps})")
        process_text = json.dumps(execution_log, indent=2, default=str)
        final_answer, determined_status = await self.generate_final_answer(
            ctx, instruction, results, process_text, status, error
        )
        results["status"] = determined_status
        if error:
            results["error"] = error
        return results, final_answer

    async def _execute_tool(
        self, tool_name: str, args: dict, readonly: bool
    ) -> Any:
        """执行工具调用（结构化参数，禁止代码生成）"""
        module = self._tool_name_to_module.get(tool_name)
        if not module:
            raise ValueError(f"Tool '{tool_name}' not found")

        readonly_tools = getattr(module.__class__, "_readonly_tools", {})
        if readonly and not readonly_tools.get(tool_name, False):
            raise ValueError(
                f"Tool '{tool_name}' is not readonly but readonly mode is enabled"
            )

        tool_obj = self._tool_name_to_tool_obj.get(tool_name)
        if not tool_obj:
            raise ValueError(f"Tool object for '{tool_name}' not found")

        tool_func = tool_obj.fn
        if not tool_func:
            raise ValueError(f"Tool function for '{tool_name}' not found")

        import inspect

        if inspect.iscoroutinefunction(tool_func):
            result = await tool_func(module, **args)
        else:
            result = tool_func(module, **args)

        return result

    def _build_initial_prompt(
        self, instruction: str, ctx: dict, readonly: bool
    ) -> str:
        """构建基于角色的初始 prompt。"""
        readonly_note = (
            " (READONLY MODE — only use read-only observation tools)" if readonly else ""
        )
        context_repr = json.dumps(ctx, default=str, ensure_ascii=False, indent=2)
        tool_scope_summary = self._build_tool_scope_summary(readonly=readonly)

        if self.router_role == "operator":
            return self._build_operator_prompt(
                instruction=instruction,
                context_repr=context_repr,
                readonly_note=readonly_note,
                tool_scope_summary=tool_scope_summary,
            )

        return self._build_agent_prompt(
            instruction=instruction,
            context_repr=context_repr,
            readonly_note=readonly_note,
            tool_scope_summary=tool_scope_summary,
        )

    def _build_tool_scope_summary(self, readonly: bool) -> str:
        """Summarize currently exposed tool modules for prompt grounding."""
        module_lines: List[str] = []
        for module in self.env_modules:
            registered_tools = getattr(module.__class__, "_registered_tools", {})
            readonly_tools = getattr(module.__class__, "_readonly_tools", {})
            tool_names = [
                name
                for name in registered_tools.keys()
                if not readonly or readonly_tools.get(name, False)
            ]
            if not tool_names:
                continue
            module_lines.append(
                f"- {module.name}: {', '.join(sorted(tool_names))}"
            )
        return "\n".join(module_lines) or "- (no tools available)"

    def _build_agent_prompt(
        self,
        instruction: str,
        context_repr: str,
        readonly_note: str,
        tool_scope_summary: str,
    ) -> str:
        """Prompt for simulated agents acting inside the world."""
        return f"""You are an AI agent operating inside a virtual world simulation.
Your role is to act or gather information on behalf of a simulated entity inside the world.

## Instruction{readonly_note}

<instruction>{instruction}</instruction>

## World Context

```json
{context_repr}
```

## Tool Scope

You only have access to agent-side world tools. These tools represent what an in-world agent can perceive or do.

{tool_scope_summary}

## Rules

1. Use the provided tools to accomplish the instruction from the perspective of an in-world agent.
2. Do NOT behave like an external administrator, analyst, or intervention controller.
3. Do NOT generate or execute Python code — use tools only.
4. Call `set_status` when done:
   - `success`: task completed
   - `in_progress`: more steps needed
   - `fail`: cannot complete
   - `error`: exception occurred
5. Be concise and focused.

Begin now."""

    def _build_operator_prompt(
        self,
        instruction: str,
        context_repr: str,
        readonly_note: str,
        tool_scope_summary: str,
    ) -> str:
        """Prompt for external operators using privileged world tools."""
        return f"""You are an external operator interacting with a virtual world simulation.
Your role is to inspect the world, generate reports, or apply privileged interventions from outside the simulation.

## Instruction{readonly_note}

<instruction>{instruction}</instruction>

## World Context

```json
{context_repr}
```

## Tool Scope

You only have access to operator-side tools. These tools are privileged and are not normal agent abilities.

{tool_scope_summary}

## Rules

1. Use the provided tools to inspect the world or apply explicit operator actions.
2. Do NOT role-play as an in-world agent.
3. Do NOT generate or execute Python code — use tools only.
4. Call `set_status` when done:
   - `success`: task completed
   - `in_progress`: more steps needed
   - `fail`: cannot complete
   - `error`: exception occurred
5. Be concise and explicit about intervention/report outcomes.

Begin now."""
