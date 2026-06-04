from __future__ import annotations

import asyncio
import json
import sys

from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.tool.tool_protocol import ToolRegistryProtocol
from cyreneAI.infra.adapters.tools.common import parse_tool_arguments


def register_python_code_interpreter_tool(
    registry: ToolRegistryProtocol,
    *,
    timeout_seconds: float = 10.0,
) -> None:
    """
    Register a sandbox-required Python code execution tool.
    """
    definition = ToolDefinition(
        name="code_interpreter",
        description=(
            "Execute a short Python snippet and return stdout, stderr, and exit code. "
            "Use only for computation or data transformation."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
            },
            "required": ["code"],
            "additionalProperties": False,
        },
        safety_profile=ToolSafetyProfile(
            risk_level=ToolRiskLevel.PROCESS,
            permissions=[ToolPermission.SUBPROCESS],
            sandbox_required=True,
            timeout_seconds=max(1, int(timeout_seconds)),
            max_output_chars=32768,
        ),
        metadata={"source": "builtin"},
    )
    if registry.exists(definition.name):
        return
    registry.register(
        definition,
        _PythonCodeInterpreterExecutor(timeout_seconds=timeout_seconds),
    )


class _PythonCodeInterpreterExecutor:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_code_chars: int = 20_000,
        max_stdout_bytes: int = 64_000,
        max_stderr_bytes: int = 64_000,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_code_chars = max_code_chars
        self._max_stdout_bytes = max_stdout_bytes
        self._max_stderr_bytes = max_stderr_bytes

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = parse_tool_arguments(call.arguments)
        code = arguments.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ToolExecutionError("code is required")
        if len(code) > self._max_code_chars:
            raise ToolExecutionError("code is too large")

        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-c",
                code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            if process is not None:
                process.kill()
                await process.wait()
            raise ToolExecutionError("code_interpreter timed out", cause=exc) from exc
        except OSError as exc:
            raise ToolExecutionError(
                "code_interpreter failed to start", cause=exc
            ) from exc

        if len(stdout) > self._max_stdout_bytes:
            raise ToolExecutionError("code_interpreter stdout exceeded maximum size")
        if len(stderr) > self._max_stderr_bytes:
            raise ToolExecutionError("code_interpreter stderr exceeded maximum size")

        payload = {
            "exit_code": process.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            success=process.returncode == 0,
            error=payload["stderr"] or None if process.returncode != 0 else None,
        )


__all__ = ["register_python_code_interpreter_tool"]
