from __future__ import annotations

import asyncio
import sys

import pytest

from cyreneAI.core.errors.tool import ToolConfigurationError, ToolExecutionError
from cyreneAI.core.schema.tool import ToolCall
from cyreneAI.infra.adapters.tools.subprocess.executor import SubprocessToolExecutor


async def _run_subprocess_tool() -> None:
    code = (
        "import json, sys; "
        "payload = json.load(sys.stdin); "
        "print(json.dumps({"
        "'content': 'value:' + payload['arguments']['key'], "
        "'metadata': {'tool': payload['name']}"
        "}))"
    )
    executor = SubprocessToolExecutor([sys.executable, "-c", code])
    result = await executor.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments='{"key":"answer"}',
        )
    )

    assert result.call_id == "call-1"
    assert result.name == "lookup"
    assert result.content == "value:answer"
    assert result.metadata == {"tool": "lookup"}


def test_subprocess_tool_executor_maps_json_stdout_result() -> None:
    asyncio.run(_run_subprocess_tool())


async def _run_failing_subprocess_tool() -> None:
    code = "import sys; print('boom', file=sys.stderr); sys.exit(2)"
    executor = SubprocessToolExecutor([sys.executable, "-c", code])
    await executor.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments="{}",
        )
    )


def test_subprocess_tool_executor_translates_nonzero_exit() -> None:
    with pytest.raises(ToolExecutionError):
        asyncio.run(_run_failing_subprocess_tool())


async def _run_failing_subprocess_tool_with_long_stderr() -> None:
    code = "import sys; print('abcdef', file=sys.stderr); sys.exit(2)"
    executor = SubprocessToolExecutor(
        [sys.executable, "-c", code],
        max_error_message_chars=3,
    )
    await executor.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments="{}",
        )
    )


def test_subprocess_tool_executor_truncates_nonzero_stderr() -> None:
    with pytest.raises(ToolExecutionError) as caught:
        asyncio.run(_run_failing_subprocess_tool_with_long_stderr())

    message = str(caught.value)
    assert "abc..." in message
    assert "abcdef" not in message


async def _run_subprocess_tool_with_oversized_stdout() -> None:
    code = "print('abcdef')"
    executor = SubprocessToolExecutor(
        [sys.executable, "-c", code],
        max_stdout_bytes=5,
    )
    await executor.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments="{}",
        )
    )


def test_subprocess_tool_executor_rejects_oversized_stdout() -> None:
    with pytest.raises(ToolExecutionError):
        asyncio.run(_run_subprocess_tool_with_oversized_stdout())


def test_subprocess_tool_executor_rejects_empty_command() -> None:
    with pytest.raises(ToolConfigurationError):
        SubprocessToolExecutor([])


async def _run_missing_subprocess_tool() -> None:
    executor = SubprocessToolExecutor(["cyreneai-missing-command-for-test"])
    await executor.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments="{}",
        )
    )


def test_subprocess_tool_executor_translates_start_failure() -> None:
    with pytest.raises(ToolExecutionError) as caught:
        asyncio.run(_run_missing_subprocess_tool())

    assert isinstance(caught.value.cause, OSError)


async def _run_timing_out_subprocess_tool() -> None:
    code = "import time; time.sleep(10)"
    executor = SubprocessToolExecutor([sys.executable, "-c", code], timeout=0.01)
    await executor.execute(
        ToolCall(
            id="call-1",
            name="lookup",
            arguments="{}",
        )
    )


def test_subprocess_tool_executor_translates_timeout() -> None:
    with pytest.raises(ToolExecutionError) as caught:
        asyncio.run(_run_timing_out_subprocess_tool())

    assert isinstance(caught.value.cause, TimeoutError)
