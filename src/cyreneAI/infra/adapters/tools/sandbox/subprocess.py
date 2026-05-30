from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

from cyreneAI.core.errors.tool import ToolConfigurationError, ToolExecutionError
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
)
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol
from cyreneAI.infra.adapters.tools.common import (
    make_tool_payload,
    map_json_text_tool_result,
    parse_tool_arguments,
)


class SubprocessToolSandboxRunner:
    """
    最小 subprocess sandbox runner。

    每个工具名映射到一个命令，runner 将标准 tool payload 写入 stdin，
    并从 stdout 读取 ToolResult 兼容 JSON。
    """

    def __init__(
        self,
        commands: Mapping[str, Sequence[str]],
        *,
        default_timeout: float = 30.0,
        cwd: str | None = None,
        environment: dict[str, str] | None = None,
        max_stdout_bytes: int = 1_048_576,
        max_stderr_bytes: int = 65_536,
        max_error_message_chars: int = 1_000,
    ) -> None:
        self._commands = {
            name: tuple(command)
            for name, command in commands.items()
        }
        for name, command in self._commands.items():
            if not command:
                raise ToolConfigurationError(
                    f"Subprocess sandbox command for {name} cannot be empty"
                )
        self._default_timeout = default_timeout
        self._cwd = cwd
        self._environment = environment
        self._max_stdout_bytes = max_stdout_bytes
        self._max_stderr_bytes = max_stderr_bytes
        self._max_error_message_chars = max_error_message_chars

    async def execute(
        self,
        *,
        call: ToolCall,
        definition: ToolDefinition,
        executor: ToolExecutorProtocol,
        policy: ToolExecutionPolicy,
    ) -> ToolResult:
        command = self._commands.get(definition.name)
        if command is None:
            raise ToolConfigurationError(
                f"Tool {definition.name} has no subprocess sandbox command"
            )

        arguments = parse_tool_arguments(call.arguments)
        payload: dict[str, Any] = {
            **make_tool_payload(call, arguments),
            "sandbox": {
                "mode": "subprocess",
                "tool_name": definition.name,
                "sandbox_required": definition.safety_profile.sandbox_required,
                "allow_sandbox_bypass": policy.allow_sandbox_bypass,
            },
        }
        input_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        process: asyncio.subprocess.Process | None = None
        timeout = definition.safety_profile.timeout_seconds or self._default_timeout

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
                env=self._environment,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input_data),
                timeout=timeout,
            )
        except TimeoutError as exc:
            if process is not None:
                process.kill()
                await process.wait()
            raise ToolExecutionError(
                f"Tool {definition.name} subprocess sandbox timed out",
                cause=exc,
            ) from exc
        except OSError as exc:
            raise ToolExecutionError(
                f"Tool {definition.name} subprocess sandbox failed to start",
                cause=exc,
            ) from exc

        _validate_output_size(
            call=call,
            stdout=stdout,
            stderr=stderr,
            max_stdout_bytes=self._max_stdout_bytes,
            max_stderr_bytes=self._max_stderr_bytes,
        )
        if process.returncode != 0:
            stderr_text = _truncate_text(
                stderr.decode("utf-8", errors="replace").strip(),
                max_chars=self._max_error_message_chars,
            )
            raise ToolExecutionError(
                f"Tool {definition.name} subprocess sandbox exited with "
                f"code {process.returncode}: {stderr_text}"
            )

        result = map_json_text_tool_result(
            call,
            stdout.decode("utf-8", errors="replace"),
        )
        return _with_sandbox_metadata(
            result,
            definition=definition,
            policy=policy,
        )


def _validate_output_size(
    *,
    call: ToolCall,
    stdout: bytes,
    stderr: bytes,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> None:
    if max_stdout_bytes >= 0 and len(stdout) > max_stdout_bytes:
        raise ToolExecutionError(
            f"Tool {call.name} subprocess sandbox stdout exceeded maximum size"
        )
    if max_stderr_bytes >= 0 and len(stderr) > max_stderr_bytes:
        raise ToolExecutionError(
            f"Tool {call.name} subprocess sandbox stderr exceeded maximum size"
        )


def _with_sandbox_metadata(
    result: ToolResult,
    *,
    definition: ToolDefinition,
    policy: ToolExecutionPolicy,
) -> ToolResult:
    return result.model_copy(
        update={
            "metadata": {
                **result.metadata,
                "sandbox": {
                    "mode": "subprocess",
                    "tool_name": definition.name,
                    "sandbox_required": definition.safety_profile.sandbox_required,
                    "allow_sandbox_bypass": policy.allow_sandbox_bypass,
                },
            }
        }
    )


def _truncate_text(text: str, *, max_chars: int) -> str:
    if max_chars < 0 or len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."
