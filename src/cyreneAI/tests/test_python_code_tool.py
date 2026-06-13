from __future__ import annotations

import asyncio
import json

import pytest

from cyreneAI.core.errors.tool import ToolExecutionError, ToolInputError
from cyreneAI.core.schema.tool import ToolCall, ToolExecutionPolicy
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.infra.adapters.tools import python_code


def _manager(registry: ToolRegistry) -> ToolManager:
    return ToolManager(
        registry,
        default_policy=ToolExecutionPolicy(allow_sandbox_bypass=True),
    )


def _call(arguments: dict) -> ToolCall:
    return ToolCall(
        id="call-code",
        name="code_interpreter",
        arguments=json.dumps(arguments),
    )


def test_python_code_interpreter_returns_stdout_payload() -> None:
    async def run() -> None:
        registry = ToolRegistry()
        python_code.register_python_code_interpreter_tool(registry)
        manager = _manager(registry)

        result = await manager.execute(_call({"code": "print(40 + 2)"}))
        payload = json.loads(result.content or "{}")

        assert result.success is True
        assert result.error is None
        assert payload == {
            "exit_code": 0,
            "stdout": "42\n",
            "stderr": "",
        }

    asyncio.run(run())


def test_python_code_interpreter_reports_nonzero_exit() -> None:
    async def run() -> None:
        registry = ToolRegistry()
        python_code.register_python_code_interpreter_tool(registry)
        manager = _manager(registry)

        result = await manager.execute(
            _call(
                {
                    "code": (
                        "import sys; "
                        "print('bad', file=sys.stderr); "
                        "raise SystemExit(3)"
                    )
                }
            )
        )
        payload = json.loads(result.content or "{}")

        assert result.success is False
        assert result.error == "bad\n"
        assert payload["exit_code"] == 3
        assert payload["stderr"] == "bad\n"

    asyncio.run(run())


@pytest.mark.parametrize(
    "arguments, error_type, message",
    [
        ({}, ToolInputError, "arguments.code is required"),
        ({"code": "   "}, ToolExecutionError, "code is required"),
        ({"code": "x" * 20_001}, ToolExecutionError, "code is too large"),
    ],
)
def test_python_code_interpreter_validates_code(arguments, error_type, message) -> None:
    async def run() -> None:
        registry = ToolRegistry()
        python_code.register_python_code_interpreter_tool(registry)
        manager = _manager(registry)

        with pytest.raises(error_type, match=message):
            await manager.execute(_call(arguments))

    asyncio.run(run())


def test_python_code_interpreter_translates_start_failure(monkeypatch) -> None:
    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> object:
        raise OSError("no python")

    async def run() -> None:
        monkeypatch.setattr(
            python_code.asyncio,
            "create_subprocess_exec",
            fake_create_subprocess_exec,
        )
        executor = python_code._PythonCodeInterpreterExecutor(timeout_seconds=1)

        with pytest.raises(ToolExecutionError, match="failed to start"):
            await executor.execute(_call({"code": "print('never')"}))

    asyncio.run(run())


def test_python_code_interpreter_kills_timed_out_process(monkeypatch) -> None:
    class FakeProcess:
        returncode = None

        def __init__(self) -> None:
            self.killed = False
            self.waited = False

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(1)
            return b"", b""

        def kill(self) -> None:
            self.killed = True

        async def wait(self) -> int:
            self.waited = True
            return -9

    process = FakeProcess()

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> FakeProcess:
        return process

    async def run() -> None:
        monkeypatch.setattr(
            python_code.asyncio,
            "create_subprocess_exec",
            fake_create_subprocess_exec,
        )
        executor = python_code._PythonCodeInterpreterExecutor(timeout_seconds=0.01)

        with pytest.raises(ToolExecutionError, match="timed out"):
            await executor.execute(_call({"code": "while True: pass"}))

    asyncio.run(run())

    assert process.killed is True
    assert process.waited is True


def test_python_code_interpreter_rejects_oversized_output() -> None:
    async def run() -> None:
        executor = python_code._PythonCodeInterpreterExecutor(
            timeout_seconds=1,
            max_stdout_bytes=1,
        )

        with pytest.raises(ToolExecutionError, match="stdout exceeded"):
            await executor.execute(_call({"code": "print('abc')"}))

    asyncio.run(run())
