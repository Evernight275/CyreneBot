from __future__ import annotations

import asyncio
from typing import Any, cast

from cyreneAI.core.errors.tool import ToolExecutionError, ToolResultError
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
)
from cyreneAI.core.tool.policy import (
    build_tool_policy_audit_metadata,
    enforce_tool_execution_policy,
)
from cyreneAI.core.tool.tool_protocol import (
    ToolExecutorProtocol,
    ToolRegistryProtocol,
    ToolSandboxRunnerProtocol,
)
from cyreneAI.core.tool.validation import validate_tool_call_arguments


class ToolManager:
    """
    工具运行管理器
    """

    def __init__(
        self,
        registry: ToolRegistryProtocol,
        *,
        default_policy: ToolExecutionPolicy | None = None,
        sandbox_runner: ToolSandboxRunnerProtocol | None = None,
    ) -> None:
        self._registry = registry
        self._default_policy = default_policy or ToolExecutionPolicy()
        self._sandbox_runner = sandbox_runner

    async def execute(
        self,
        call: ToolCall,
        *,
        policy: ToolExecutionPolicy | None = None,
    ) -> ToolResult:
        """
        执行工具调用
        """
        definition = self._registry.get_definition(call.name)
        execution_policy = policy or self._default_policy
        sandbox_available = self._sandbox_runner is not None
        enforce_tool_execution_policy(
            definition=definition,
            policy=execution_policy,
            sandbox_available=sandbox_available,
        )
        validate_tool_call_arguments(definition=definition, call=call)
        executor = self._registry.get_executor(call.name)
        sandbox_used = (
            definition.safety_profile.sandbox_required
            and self._sandbox_runner is not None
            and not execution_policy.allow_sandbox_bypass
        )
        sandbox_mode: str | None = None
        if sandbox_used:
            assert self._sandbox_runner is not None
            result = await self._sandbox_runner.execute(
                call=call,
                definition=definition,
                executor=executor,
                policy=execution_policy,
            )
            sandbox_mode = _sandbox_mode(result)
        else:
            result = await _execute_with_timeout(
                call=call,
                definition=definition,
                executor=executor,
            )
        _validate_result_size(definition=definition, result=result)
        return _with_policy_metadata(
            result,
            definition=definition,
            policy=execution_policy,
            sandbox_used=sandbox_used,
            sandbox_mode=sandbox_mode,
        )

    def exists(self, name: str) -> bool:
        """
        判断工具是否存在
        """
        return self._registry.exists(name)


async def _execute_with_timeout(
    *,
    call: ToolCall,
    definition: ToolDefinition,
    executor: ToolExecutorProtocol,
) -> ToolResult:
    timeout_seconds = definition.safety_profile.timeout_seconds
    if timeout_seconds is None:
        return await executor.execute(call)
    try:
        return await asyncio.wait_for(
            executor.execute(call),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise ToolExecutionError(
            f"Tool {definition.name} timed out",
            cause=exc,
        ) from exc


def _validate_result_size(
    *,
    definition: ToolDefinition,
    result: ToolResult,
) -> None:
    max_output_chars = definition.safety_profile.max_output_chars
    if max_output_chars is None or result.content is None:
        return
    if len(result.content) > max_output_chars:
        raise ToolResultError(
            f"Tool {definition.name} output exceeded maximum size"
        )


def _with_policy_metadata(
    result: ToolResult,
    *,
    definition: ToolDefinition,
    policy: ToolExecutionPolicy,
    sandbox_used: bool,
    sandbox_mode: str | None,
) -> ToolResult:
    return result.model_copy(
        update={
            "metadata": {
                **result.metadata,
                "tool_policy": build_tool_policy_audit_metadata(
                    definition=definition,
                    policy=policy,
                    sandbox_used=sandbox_used,
                    sandbox_mode=sandbox_mode,
                ),
            }
        }
    )


def _sandbox_mode(result: ToolResult) -> str | None:
    sandbox_metadata = result.metadata.get("sandbox")
    if not isinstance(sandbox_metadata, dict):
        return None
    sandbox_metadata_dict = cast(dict[str, Any], sandbox_metadata)
    mode = sandbox_metadata_dict.get("mode")
    if isinstance(mode, str):
        return mode
    return None
