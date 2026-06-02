from __future__ import annotations

import asyncio
import json

import pytest

from cyreneAI.core.errors.tool import ToolPolicyError
from cyreneAI.core.schema.tool import ToolCall
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
