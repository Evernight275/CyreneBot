from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

from cyreneAI.core.errors.tool import ToolConfigurationError, ToolExecutionError
from cyreneAI.core.schema.tool import ToolCall, ToolResult
from cyreneAI.infra.adapters.tools.common import (
    make_tool_payload,
    map_json_text_tool_result,
    parse_tool_arguments,
)


class SubprocessToolExecutor:
    """
    子进程工具执行器
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout: float = 30.0,
        cwd: str | None = None,
        environment: dict[str, str] | None = None,
        max_stdout_bytes: int = 1_048_576,
        max_stderr_bytes: int = 65_536,
        max_error_message_chars: int = 1_000,
    ) -> None:
        if not command:
            raise ToolConfigurationError("Subprocess tool command cannot be empty")

        self._command = tuple(command)
        self._timeout = timeout
        self._cwd = cwd
        self._environment = environment
        self._max_stdout_bytes = max_stdout_bytes
        self._max_stderr_bytes = max_stderr_bytes
        self._max_error_message_chars = max_error_message_chars

    async def execute(self, call: ToolCall) -> ToolResult:
        """
        执行子进程工具
        """
        arguments = parse_tool_arguments(call.arguments)
        payload = make_tool_payload(call, arguments)
        input_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        process: asyncio.subprocess.Process | None = None

        try:
            process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
                env=self._environment,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input_data),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            if process is not None:
                process.kill()
                await process.wait()
            raise ToolExecutionError(
                f"Tool {call.name} subprocess timed out",
                cause=exc,
            ) from exc
        except OSError as exc:
            raise ToolExecutionError(
                f"Tool {call.name} subprocess failed to start",
                cause=exc,
            ) from exc

        self._validate_output_size(call=call, stdout=stdout, stderr=stderr)
        if process.returncode != 0:
            stderr_text = _truncate_text(
                stderr.decode("utf-8", errors="replace").strip(),
                max_chars=self._max_error_message_chars,
            )
            raise ToolExecutionError(
                f"Tool {call.name} subprocess exited with "
                f"code {process.returncode}: {stderr_text}"
            )

        stdout_text = stdout.decode("utf-8", errors="replace")
        return map_json_text_tool_result(call, stdout_text)

    def _validate_output_size(
        self,
        *,
        call: ToolCall,
        stdout: bytes,
        stderr: bytes,
    ) -> None:
        if self._max_stdout_bytes >= 0 and len(stdout) > self._max_stdout_bytes:
            raise ToolExecutionError(
                f"Tool {call.name} subprocess stdout exceeded maximum size"
            )
        if self._max_stderr_bytes >= 0 and len(stderr) > self._max_stderr_bytes:
            raise ToolExecutionError(
                f"Tool {call.name} subprocess stderr exceeded maximum size"
            )


def _truncate_text(text: str, *, max_chars: int) -> str:
    if max_chars < 0 or len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."
