from __future__ import annotations

import asyncio

from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
)
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol


class InProcessToolSandboxRunner:
    """
    最小 in-process sandbox runner。

    它不提供进程级隔离，但会统一经过 sandbox runner 通道，
    并应用工具安全画像中的 timeout 与审计 metadata。
    """

    async def execute(
        self,
        *,
        call: ToolCall,
        definition: ToolDefinition,
        executor: ToolExecutorProtocol,
        policy: ToolExecutionPolicy,
    ) -> ToolResult:
        timeout_seconds = definition.safety_profile.timeout_seconds
        try:
            if timeout_seconds is None:
                result = await executor.execute(call)
            else:
                result = await asyncio.wait_for(
                    executor.execute(call),
                    timeout=timeout_seconds,
                )
        except TimeoutError as exc:
            raise ToolExecutionError(
                f"Tool {definition.name} sandbox execution timed out",
                cause=exc,
            ) from exc

        return _with_sandbox_metadata(
            result,
            mode="in_process",
            definition=definition,
            policy=policy,
        )


def _with_sandbox_metadata(
    result: ToolResult,
    *,
    mode: str,
    definition: ToolDefinition,
    policy: ToolExecutionPolicy,
) -> ToolResult:
    return result.model_copy(
        update={
            "metadata": {
                **result.metadata,
                "sandbox": {
                    "mode": mode,
                    "tool_name": definition.name,
                    "sandbox_required": definition.safety_profile.sandbox_required,
                    "allow_sandbox_bypass": policy.allow_sandbox_bypass,
                },
            }
        }
    )
