from __future__ import annotations

import asyncio
import json
import sys

import pytest

from cyreneAI.core.errors.tool import ToolConfigurationError, ToolExecutionError
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.infra.adapters.tools.sandbox import (
    InProcessToolSandboxRunner,
    SubprocessToolSandboxRunner,
)


class _FakeToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=f"in-process:{call.name}",
        )


class _SlowToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        await asyncio.sleep(10)
        return ToolResult(call_id=call.id, name=call.name, content="late")


def _sandboxed_definition(
    name: str = "lookup",
    *,
    timeout_seconds: int | None = 5,
    max_output_chars: int | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Sandboxed tool.",
        safety_profile=ToolSafetyProfile(
            risk_level=ToolRiskLevel.PROCESS,
            permissions=[ToolPermission.SUBPROCESS],
            sandbox_required=True,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
        ),
    )


async def _run_in_process_sandbox_runner() -> None:
    registry = ToolRegistry()
    registry.register(_sandboxed_definition(), _FakeToolExecutor())
    manager = ToolManager(
        registry,
        sandbox_runner=InProcessToolSandboxRunner(),
    )

    result = await manager.execute(ToolCall(id="call-1", name="lookup"))

    assert result.content == "in-process:lookup"
    assert result.metadata["sandbox"]["mode"] == "in_process"
    assert result.metadata["tool_policy"]["sandbox_used"] is True
    assert result.metadata["tool_policy"]["sandbox_mode"] == "in_process"


def test_in_process_sandbox_runner_executes_sandbox_required_tool() -> None:
    asyncio.run(_run_in_process_sandbox_runner())


async def _run_in_process_sandbox_runner_timeout() -> None:
    registry = ToolRegistry()
    registry.register(
        _sandboxed_definition(timeout_seconds=1),
        _SlowToolExecutor(),
    )
    manager = ToolManager(
        registry,
        sandbox_runner=InProcessToolSandboxRunner(),
    )

    await manager.execute(ToolCall(id="call-1", name="lookup"))


def test_in_process_sandbox_runner_translates_timeout() -> None:
    with pytest.raises(ToolExecutionError):
        asyncio.run(_run_in_process_sandbox_runner_timeout())


async def _run_subprocess_sandbox_runner() -> None:
    code = (
        "import json, sys; "
        "payload = json.load(sys.stdin); "
        "print(json.dumps({"
        "'content': 'subprocess:' + payload['arguments']['key'], "
        "'metadata': {'seen_sandbox': payload['sandbox']['mode']}"
        "}))"
    )
    registry = ToolRegistry()
    registry.register(_sandboxed_definition(), _FakeToolExecutor())
    manager = ToolManager(
        registry,
        sandbox_runner=SubprocessToolSandboxRunner(
            {"lookup": [sys.executable, "-c", code]}
        ),
    )

    result = await manager.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments=json.dumps({"key": "answer"}),
        )
    )

    assert result.content == "subprocess:answer"
    assert result.metadata["seen_sandbox"] == "subprocess"
    assert result.metadata["sandbox"]["mode"] == "subprocess"
    assert result.metadata["tool_policy"]["sandbox_mode"] == "subprocess"


def test_subprocess_sandbox_runner_executes_command() -> None:
    asyncio.run(_run_subprocess_sandbox_runner())


async def _run_subprocess_sandbox_runner_missing_command() -> None:
    registry = ToolRegistry()
    registry.register(_sandboxed_definition(), _FakeToolExecutor())
    manager = ToolManager(
        registry,
        sandbox_runner=SubprocessToolSandboxRunner({}),
    )

    await manager.execute(ToolCall(id="call-1", name="lookup"))


def test_subprocess_sandbox_runner_requires_command() -> None:
    with pytest.raises(ToolConfigurationError):
        asyncio.run(_run_subprocess_sandbox_runner_missing_command())


def test_subprocess_sandbox_runner_rejects_empty_command() -> None:
    with pytest.raises(ToolConfigurationError):
        SubprocessToolSandboxRunner({"lookup": []})


async def _execute_subprocess_runner(
    command: list[str],
    *,
    definition: ToolDefinition | None = None,
    max_stdout_bytes: int = 1_048_576,
    max_stderr_bytes: int = 65_536,
    max_error_message_chars: int = 1_000,
) -> ToolResult:
    runner = SubprocessToolSandboxRunner(
        {"lookup": command},
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
        max_error_message_chars=max_error_message_chars,
    )
    return await runner.execute(
        call=ToolCall(
            id="call-1",
            name="lookup",
            arguments=json.dumps({"key": "answer"}),
        ),
        definition=definition or _sandboxed_definition(),
        executor=_FakeToolExecutor(),
        policy=ToolExecutionPolicy(),
    )


def test_subprocess_sandbox_runner_translates_start_failure() -> None:
    async def run() -> None:
        with pytest.raises(ToolExecutionError, match="failed to start"):
            await _execute_subprocess_runner(["definitely-not-a-cyrene-command"])

    asyncio.run(run())


def test_subprocess_sandbox_runner_kills_timed_out_process() -> None:
    async def run() -> None:
        with pytest.raises(ToolExecutionError, match="timed out"):
            await _execute_subprocess_runner(
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(5)",
                ],
                definition=_sandboxed_definition(timeout_seconds=1),
            )

    asyncio.run(run())


def test_subprocess_sandbox_runner_rejects_oversized_stdout_and_stderr() -> None:
    async def run() -> None:
        with pytest.raises(ToolExecutionError, match="stdout exceeded"):
            await _execute_subprocess_runner(
                [sys.executable, "-c", "print('abcdef')"],
                max_stdout_bytes=3,
            )

        with pytest.raises(ToolExecutionError, match="stderr exceeded"):
            await _execute_subprocess_runner(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stderr.write('abcdef')",
                ],
                max_stderr_bytes=3,
            )

    asyncio.run(run())


def test_subprocess_sandbox_runner_reports_nonzero_exit_with_truncated_stderr() -> None:
    async def run() -> None:
        with pytest.raises(ToolExecutionError) as caught:
            await _execute_subprocess_runner(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stderr.write('abcdef'); raise SystemExit(5)",
                ],
                max_error_message_chars=3,
            )

        assert str(caught.value) == (
            "Tool lookup subprocess sandbox exited with code 5: abc..."
        )

    asyncio.run(run())


def test_subprocess_sandbox_runner_can_disable_output_size_limits() -> None:
    async def run() -> None:
        result = await _execute_subprocess_runner(
            [
                sys.executable,
                "-c",
                "import json; print(json.dumps({'content': 'ok'}))",
            ],
            max_stdout_bytes=-1,
            max_stderr_bytes=-1,
        )

        assert result.content == "ok"
        assert result.metadata["sandbox"]["allow_sandbox_bypass"] is False

    asyncio.run(run())
