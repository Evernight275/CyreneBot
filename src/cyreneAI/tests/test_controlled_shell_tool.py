from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from cyreneAI.core.errors.tool import ToolExecutionError, ToolInputError, ToolPolicyError
from cyreneAI.core.schema.tool import (
    ShellCommandDecision,
    ShellCommandPolicy,
    ShellCommandRule,
    ToolCall,
)
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.infra.adapters.tools.shell import register_controlled_shell_tool


def _call(arguments: dict) -> ToolCall:
    return ToolCall(
        id="call-shell",
        name="shell",
        arguments=json.dumps(arguments),
    )


def test_controlled_shell_allows_safe_builtin_commands(tmp_path) -> None:
    async def run() -> None:
        (tmp_path / "note.txt").write_text("hello\nworld\n", encoding="utf-8")
        registry = ToolRegistry()
        register_controlled_shell_tool(registry, cwd_root=tmp_path)
        manager = ToolManager(registry)

        result = await manager.execute(_call({"command": "cat note.txt"}))
        payload = json.loads(result.content or "{}")

        assert result.success is True
        assert payload["decision"] == "allow"
        assert payload["stdout"].splitlines() == ["hello", "world"]

        result = await manager.execute(_call({"command": "ls -la"}))
        payload = json.loads(result.content or "{}")

        assert result.success is True
        assert "note.txt" in payload["stdout"].splitlines()

    asyncio.run(run())


def test_controlled_shell_requires_review_for_review_commands(tmp_path) -> None:
    async def run() -> None:
        registry = ToolRegistry()
        register_controlled_shell_tool(registry, cwd_root=tmp_path)
        manager = ToolManager(registry)

        result = await manager.execute(
            _call({"command": ["python", "-c", "print('unsafe without review')"]})
        )
        payload = json.loads(result.content or "{}")

        assert result.success is False
        assert result.error == "Command requires review: python"
        assert payload["requires_review"] is True
        assert payload["decision"] == "review"

    asyncio.run(run())


def test_controlled_shell_denies_blocked_commands(tmp_path) -> None:
    async def run() -> None:
        registry = ToolRegistry()
        register_controlled_shell_tool(registry, cwd_root=tmp_path)
        manager = ToolManager(registry)

        with pytest.raises(ToolPolicyError):
            await manager.execute(_call({"command": "rm note.txt"}))

    asyncio.run(run())


def test_controlled_shell_denies_shell_control_tokens(tmp_path) -> None:
    async def run() -> None:
        registry = ToolRegistry()
        register_controlled_shell_tool(registry, cwd_root=tmp_path)
        manager = ToolManager(registry)

        with pytest.raises(ToolPolicyError):
            await manager.execute(_call({"command": "pwd && ls"}))

    asyncio.run(run())


def test_controlled_shell_supports_cwd_head_tail_and_pwd(tmp_path) -> None:
    async def run() -> None:
        workdir = tmp_path / "work"
        workdir.mkdir()
        (workdir / "note.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
        registry = ToolRegistry()
        register_controlled_shell_tool(registry, cwd_root=tmp_path)
        manager = ToolManager(registry)

        pwd_result = await manager.execute(_call({"command": "pwd", "cwd": "work"}))
        pwd_payload = json.loads(pwd_result.content or "{}")
        assert pwd_payload["stdout"] == str(workdir)

        head_result = await manager.execute(
            _call({"command": "head -n 2 note.txt", "cwd": "work"})
        )
        head_payload = json.loads(head_result.content or "{}")
        assert head_payload["stdout"] == "one\ntwo"

        tail_result = await manager.execute(
            _call({"command": ["tail", "-n", "1", "note.txt"], "cwd": "work"})
        )
        tail_payload = json.loads(tail_result.content or "{}")
        assert tail_payload["stdout"] == "three"

    asyncio.run(run())


@pytest.mark.parametrize(
    "arguments, error_type, message",
    [
        ({"command": ""}, ToolExecutionError, "command is required"),
        ({"command": ["ls", ""]}, ToolExecutionError, "non-empty strings"),
        ({"command": 123}, ToolExecutionError, "string or string array"),
        ({"command": "ls", "cwd": ""}, ToolExecutionError, "cwd must be"),
        (
            {"command": "ls", "review_approved": "yes"},
            ToolInputError,
            "arguments.review_approved has invalid type",
        ),
        ({"command": "ls --color"}, ToolExecutionError, "unsupported ls option"),
        ({"command": "ls foo bar"}, ToolExecutionError, "at most one path"),
        ({"command": "head -n nope missing.txt"}, ToolExecutionError, "integer"),
        ({"command": "tail -n 0 missing.txt"}, ToolExecutionError, "between 1 and 500"),
        ({"command": "cat"}, ToolExecutionError, "requires a path"),
        ({"command": "cat missing.txt"}, ToolExecutionError, "path does not exist"),
        ({"command": "ls", "cwd": "../"}, ToolPolicyError, "cwd cannot escape"),
    ],
)
def test_controlled_shell_rejects_invalid_arguments(
    tmp_path,
    arguments,
    error_type,
    message,
) -> None:
    async def run() -> None:
        registry = ToolRegistry()
        register_controlled_shell_tool(registry, cwd_root=tmp_path)
        manager = ToolManager(registry)

        with pytest.raises(error_type, match=message):
            await manager.execute(_call(arguments))

    asyncio.run(run())


def test_controlled_shell_runs_review_command_after_approval(tmp_path) -> None:
    async def run() -> None:
        python_name = Path(sys.executable).name
        policy = ShellCommandPolicy(
            rules=[
                ShellCommandRule(
                    command=python_name,
                    decision=ShellCommandDecision.REVIEW,
                )
            ]
        )
        registry = ToolRegistry()
        register_controlled_shell_tool(
            registry,
            policy=policy,
            cwd_root=tmp_path,
        )
        manager = ToolManager(registry)

        result = await manager.execute(
            _call(
                {
                    "command": [sys.executable, "-c", "print('approved')"],
                    "review_approved": True,
                }
            )
        )
        payload = json.loads(result.content or "{}")

        assert result.success is True
        assert payload["decision"] == "review"
        assert payload["requires_review"] is False
        assert payload["stdout"] == "approved\n"

    asyncio.run(run())


def test_controlled_shell_rejects_oversized_subprocess_output(tmp_path) -> None:
    async def run() -> None:
        python_name = Path(sys.executable).name
        policy = ShellCommandPolicy(
            rules=[
                ShellCommandRule(
                    command=python_name,
                    decision=ShellCommandDecision.ALLOW,
                )
            ]
        )
        registry = ToolRegistry()
        register_controlled_shell_tool(
            registry,
            policy=policy,
            cwd_root=tmp_path,
            max_stdout_bytes=1,
        )
        manager = ToolManager(registry)

        with pytest.raises(ToolExecutionError, match="stdout exceeded"):
            await manager.execute(
                _call({"command": [sys.executable, "-c", "print('too long')"]})
            )

    asyncio.run(run())
