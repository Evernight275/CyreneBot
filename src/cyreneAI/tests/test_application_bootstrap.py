from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.schema.bot import BotChannelDefinition
from cyreneAI.core.schema.skill import SkillSelectionRequest
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.schema.vector import VectorQuery, VectorRecord
from cyreneAI.infra.adapters.bot_polling_states.memory import (
    InMemoryBotPollingStateStore,
)
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore
from cyreneAI.infra.adapters.channels.memory import InMemoryBotChannel
from cyreneAI.infra.adapters.channels.qq import QQBotChannel
from cyreneAI.infra.adapters.channels.telegram import TelegramBotChannel
from cyreneAI.infra.adapters.plugins.filesystem import FileSystemPluginStorage
from cyreneAI.infra.adapters.vector_stores.memory.store import InMemoryVectorStore


async def _run_build_runtime(tmp_path) -> None:
    skill_path = tmp_path / "skills.json"
    skill_path.write_text(
        json.dumps(
            [
                {
                    "name": "memory",
                    "description": "Use memory.",
                    "instructions": "Prefer relevant memory.",
                    "triggers": ["memory"],
                }
            ]
        ),
        encoding="utf-8",
    )

    runtime = await build_cyrene_ai_runtime(
        context_database_path=tmp_path / "context.db",
        skill_path=skill_path,
        vector_store=InMemoryVectorStore(),
    )

    assert runtime.context_manager is not None
    assert runtime.vector_manager is not None
    assert runtime.skill_manager is not None
    assert runtime.plugin_manager is not None
    assert runtime.tool_registry is not None
    assert runtime.tool_manager is not None
    assert [command.name for command in runtime.plugin_manager.list_commands()] == [
        "start",
        "help",
        "ping",
        "echo",
        "session",
        "session current",
        "session status",
        "session ls",
        "session new",
        "session use",
        "session rename",
        "session clear",
        "session delete",
        "reset",
        "status",
        "agent runs",
        "agent run",
        "agent trace",
        "tool ls",
        "tool on",
        "tool off",
        "tool off_all",
        "provider ls",
        "provider catalog",
        "provider status",
        "provider models",
        "provider start",
        "provider stop",
        "provider reload",
        "provider check",
        "plugin ls",
        "plugin commands",
        "plugin status",
    ]

    bundle = runtime.skill_manager.build_instruction_bundle(
        SkillSelectionRequest(text="Use memory.")
    )
    assert [instruction.name for instruction in bundle.instructions] == ["memory"]

    runtime.tool_registry.register(
        ToolDefinition(
            name="lookup",
            description="Lookup a value.",
        ),
        _FakeToolExecutor(),
    )
    result = await runtime.tool_manager.execute(
        _tool_call("call-1", "lookup", '{"key":"value"}')
    )
    assert result.content == 'executed:{"key":"value"}'

    await runtime.vector_manager.upsert(
        [
            VectorRecord(
                record_id="record-1",
                vector=[1.0, 0.0],
                content="alpha",
            )
        ]
    )
    vector_result = await runtime.vector_manager.search(VectorQuery(vector=[1.0, 0.0]))
    assert vector_result.matches[0].record.content == "alpha"

    await runtime.close()


class _FakeToolExecutor:
    async def execute(self, call) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=f"executed:{call.arguments}",
        )


def _tool_call(call_id: str, name: str, arguments: str) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


def _sandboxed_definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Sandboxed tool.",
        safety_profile=ToolSafetyProfile(
            risk_level=ToolRiskLevel.PROCESS,
            permissions=[ToolPermission.SUBPROCESS],
            sandbox_required=True,
        ),
    )


def test_build_cyrene_ai_runtime_wires_context_skills_and_tools(tmp_path) -> None:
    asyncio.run(_run_build_runtime(tmp_path))


async def _run_build_runtime_with_sqlite_vector_store(tmp_path) -> None:
    database_path = tmp_path / "vectors.db"

    runtime = await build_cyrene_ai_runtime(
        vector_database_path=database_path,
    )
    try:
        assert runtime.vector_manager is not None
        await runtime.vector_manager.upsert(
            [
                VectorRecord(
                    record_id="record-1",
                    vector=[1.0, 0.0],
                    content="alpha",
                )
            ]
        )
    finally:
        await runtime.close()

    next_runtime = await build_cyrene_ai_runtime(
        vector_database_path=database_path,
    )
    try:
        assert next_runtime.vector_manager is not None
        record = await next_runtime.vector_manager.get("record-1")
        assert record.content == "alpha"
    finally:
        await next_runtime.close()


def test_build_cyrene_ai_runtime_can_create_sqlite_vector_store(tmp_path) -> None:
    asyncio.run(_run_build_runtime_with_sqlite_vector_store(tmp_path))


async def _run_build_runtime_rejects_duplicate_vector_store_config(tmp_path) -> None:
    with pytest.raises(ValueError):
        await build_cyrene_ai_runtime(
            vector_store=InMemoryVectorStore(),
            vector_database_path=tmp_path / "vectors.db",
        )


def test_build_cyrene_ai_runtime_rejects_duplicate_vector_store_config(
    tmp_path,
) -> None:
    asyncio.run(_run_build_runtime_rejects_duplicate_vector_store_config(tmp_path))


async def _run_build_runtime_wires_in_process_tool_sandbox() -> None:
    runtime = await build_cyrene_ai_runtime(
        tool_sandbox_mode="in_process",
        register_builtin_plugins=False,
    )
    try:
        assert runtime.tool_registry is not None
        assert runtime.tool_manager is not None
        assert runtime.tool_sandbox_runner is not None

        runtime.tool_registry.register(
            _sandboxed_definition("sandboxed_lookup"),
            _FakeToolExecutor(),
        )
        result = await runtime.tool_manager.execute(
            _tool_call("call-1", "sandboxed_lookup", '{"key":"value"}')
        )

        assert result.metadata["sandbox"]["mode"] == "in_process"
        assert result.metadata["tool_policy"]["sandbox_used"] is True
        assert result.metadata["tool_policy"]["sandbox_mode"] == "in_process"
    finally:
        await runtime.close()


def test_build_cyrene_ai_runtime_wires_in_process_tool_sandbox() -> None:
    asyncio.run(_run_build_runtime_wires_in_process_tool_sandbox())


async def _run_build_runtime_wires_subprocess_tool_sandbox() -> None:
    code = (
        "import json, sys; "
        "payload = json.load(sys.stdin); "
        "print(json.dumps({'content': 'sandbox:' + payload['arguments']['key']}))"
    )
    runtime = await build_cyrene_ai_runtime(
        tool_sandbox_mode="subprocess",
        tool_sandbox_commands={
            "sandboxed_lookup": [sys.executable, "-c", code],
        },
        tool_sandbox_timeout_seconds=5,
        register_builtin_plugins=False,
    )
    try:
        assert runtime.tool_registry is not None
        assert runtime.tool_manager is not None
        assert runtime.tool_sandbox_runner is not None

        runtime.tool_registry.register(
            _sandboxed_definition("sandboxed_lookup"),
            _FakeToolExecutor(),
        )
        result = await runtime.tool_manager.execute(
            _tool_call("call-1", "sandboxed_lookup", '{"key":"value"}')
        )

        assert result.content == "sandbox:value"
        assert result.metadata["sandbox"]["mode"] == "subprocess"
        assert result.metadata["tool_policy"]["sandbox_used"] is True
        assert result.metadata["tool_policy"]["sandbox_mode"] == "subprocess"
    finally:
        await runtime.close()


def test_build_cyrene_ai_runtime_wires_subprocess_tool_sandbox() -> None:
    asyncio.run(_run_build_runtime_wires_subprocess_tool_sandbox())


async def _run_build_runtime_registers_controlled_shell_tool(tmp_path) -> None:
    runtime = await build_cyrene_ai_runtime(
        controlled_shell_enabled=True,
        shell_cwd_root_path=tmp_path,
        register_builtin_plugins=False,
    )
    try:
        assert runtime.tool_registry is not None
        assert runtime.tool_manager is not None
        assert runtime.tool_registry.exists("shell")

        result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-shell",
                name="shell",
                arguments=json.dumps({"command": "pwd"}),
            )
        )
        payload = json.loads(result.content or "{}")

        assert result.success is True
        assert payload["exit_code"] == 0
        assert payload["decision"] == "allow"
        assert payload["stdout"] == str(tmp_path.resolve())
    finally:
        await runtime.close()


def test_build_cyrene_ai_runtime_registers_controlled_shell_tool(tmp_path) -> None:
    asyncio.run(_run_build_runtime_registers_controlled_shell_tool(tmp_path))


async def _run_build_runtime_rejects_duplicate_tool_sandbox_config() -> None:
    runtime = await build_cyrene_ai_runtime(
        tool_sandbox_mode="in_process",
        register_builtin_plugins=False,
    )
    try:
        with pytest.raises(ValueError):
            await build_cyrene_ai_runtime(
                tool_sandbox_runner=runtime.tool_sandbox_runner,
                tool_sandbox_mode="in_process",
                register_builtin_plugins=False,
            )
    finally:
        await runtime.close()


def test_build_cyrene_ai_runtime_rejects_duplicate_tool_sandbox_config() -> None:
    asyncio.run(_run_build_runtime_rejects_duplicate_tool_sandbox_config())


async def _run_build_runtime_rejects_subprocess_sandbox_without_commands() -> None:
    with pytest.raises(ValueError):
        await build_cyrene_ai_runtime(
            tool_sandbox_mode="subprocess",
            register_builtin_plugins=False,
        )


def test_build_cyrene_ai_runtime_rejects_subprocess_sandbox_without_commands() -> None:
    asyncio.run(_run_build_runtime_rejects_subprocess_sandbox_without_commands())


async def _run_build_runtime_wires_bot_channel_registry() -> None:
    channel_registry = BotChannelRegistry()
    channel = InMemoryBotChannel()
    channel_registry.register(
        BotChannelDefinition(
            channel_id="memory",
            name="Memory",
        ),
        channel,
    )

    runtime = await build_cyrene_ai_runtime(
        bot_channel_registry=channel_registry,
    )

    assert runtime.bot_channel_registry is channel_registry
    assert runtime.bot_channel_registry.get_channel("memory") is channel

    await runtime.close()


def test_build_cyrene_ai_runtime_wires_bot_channel_registry() -> None:
    asyncio.run(_run_build_runtime_wires_bot_channel_registry())


async def _run_build_runtime_can_enable_memory_bot_channel() -> None:
    runtime = await build_cyrene_ai_runtime(
        enable_memory_bot_channel=True,
    )

    assert runtime.bot_channel_registry is not None
    assert runtime.bot_channel_registry.exists("memory")
    assert runtime.bot_session_manager is not None
    assert isinstance(
        runtime.bot_channel_registry.get_channel("memory"),
        InMemoryBotChannel,
    )

    await runtime.close()


def test_build_cyrene_ai_runtime_can_enable_memory_bot_channel() -> None:
    asyncio.run(_run_build_runtime_can_enable_memory_bot_channel())


async def _run_build_runtime_can_enable_telegram_bot_channel() -> None:
    runtime = await build_cyrene_ai_runtime(
        telegram_bot_token="telegram-token",
    )

    assert runtime.bot_channel_registry is not None
    assert runtime.bot_channel_registry.exists("telegram")
    assert runtime.bot_session_manager is not None
    assert isinstance(
        runtime.bot_channel_registry.get_channel("telegram"),
        TelegramBotChannel,
    )

    await runtime.close()


def test_build_cyrene_ai_runtime_can_enable_telegram_bot_channel() -> None:
    asyncio.run(_run_build_runtime_can_enable_telegram_bot_channel())


async def _run_build_runtime_can_enable_qq_bot_channel() -> None:
    runtime = await build_cyrene_ai_runtime(
        qq_bot_app_id="app-id",
        qq_bot_app_secret="app-secret",
    )

    assert runtime.bot_channel_registry is not None
    assert runtime.bot_channel_registry.exists("qq")
    assert runtime.bot_session_manager is not None
    assert isinstance(
        runtime.bot_channel_registry.get_channel("qq"),
        QQBotChannel,
    )

    await runtime.close()


def test_build_cyrene_ai_runtime_can_enable_qq_bot_channel() -> None:
    asyncio.run(_run_build_runtime_can_enable_qq_bot_channel())


async def _run_build_runtime_wires_bot_session_store() -> None:
    store = InMemoryBotSessionStore()

    runtime = await build_cyrene_ai_runtime(
        bot_session_store=store,
    )

    assert runtime.bot_session_manager is not None
    assert isinstance(runtime.bot_session_manager, BotSessionManager)

    await runtime.close()


def test_build_cyrene_ai_runtime_wires_bot_session_store() -> None:
    asyncio.run(_run_build_runtime_wires_bot_session_store())


async def _run_build_runtime_can_create_bot_polling_state_store(tmp_path) -> None:
    database_path = tmp_path / "bot_polling.db"

    runtime = await build_cyrene_ai_runtime(
        bot_polling_state_database_path=database_path,
    )
    try:
        assert runtime.bot_polling_state_store is not None
        await runtime.bot_polling_state_store.save_offset("telegram", 1001)
    finally:
        await runtime.close()

    next_runtime = await build_cyrene_ai_runtime(
        bot_polling_state_database_path=database_path,
    )
    try:
        assert next_runtime.bot_polling_state_store is not None
        assert await next_runtime.bot_polling_state_store.get_offset("telegram") == 1001
    finally:
        await next_runtime.close()


def test_build_cyrene_ai_runtime_can_create_bot_polling_state_store(tmp_path) -> None:
    asyncio.run(_run_build_runtime_can_create_bot_polling_state_store(tmp_path))


async def _run_build_runtime_can_create_plugin_storage(tmp_path) -> None:
    runtime = await build_cyrene_ai_runtime(
        plugin_storage_path=tmp_path / "plugin_storage",
    )
    try:
        assert runtime.plugin_storage is not None
        namespace = runtime.plugin_storage.namespace("demo.hello")
        await namespace.set("state", {"ready": True})
    finally:
        await runtime.close()

    next_runtime = await build_cyrene_ai_runtime(
        plugin_storage_path=tmp_path / "plugin_storage",
    )
    try:
        assert next_runtime.plugin_storage is not None
        namespace = next_runtime.plugin_storage.namespace("demo.hello")
        assert await namespace.get("state") == {"ready": True}
    finally:
        await next_runtime.close()


def test_build_cyrene_ai_runtime_can_create_plugin_storage(tmp_path) -> None:
    asyncio.run(_run_build_runtime_can_create_plugin_storage(tmp_path))


async def _run_build_runtime_passes_plugin_task_scheduler_config(tmp_path) -> None:
    runtime = await build_cyrene_ai_runtime(
        plugin_task_database_path=tmp_path / "plugin_tasks.db",
        plugin_task_max_concurrent_tasks=3,
        plugin_task_lease_owner="worker-test",
        plugin_task_lease_seconds=12.5,
        register_builtin_plugins=False,
    )
    try:
        assert runtime.plugin_task_scheduler is not None
        assert runtime.plugin_task_scheduler._lease_owner == "worker-test"
        assert runtime.plugin_task_scheduler._lease_seconds == 12.5
        global_semaphore = runtime.plugin_task_scheduler._global_semaphore
        assert global_semaphore._value == 3
    finally:
        await runtime.close()


def test_build_runtime_passes_plugin_task_scheduler_config(tmp_path) -> None:
    asyncio.run(_run_build_runtime_passes_plugin_task_scheduler_config(tmp_path))


async def _run_build_runtime_loads_plugin_paths(tmp_path) -> None:
    plugin_path = tmp_path / "plugins" / "demo_hello"
    plugin_path.mkdir(parents=True)
    (plugin_path / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "demo.hello",
                "name": "Demo Hello",
                "description": "Demo plugin.",
                "entrypoint": "main.py",
                "capabilities": ["bot_command"],
            }
        ),
        encoding="utf-8",
    )
    (plugin_path / "main.py").write_text(
        "\n".join(
            [
                "from cyreneAI.api import CyreneBot",
                "",
                "plugin = CyreneBot()",
                "",
                "@plugin.command",
                "def hello(name: str = 'world'):",
                "    return f'Hello, {name}!'",
                "",
            ]
        ),
        encoding="utf-8",
    )

    runtime = await build_cyrene_ai_runtime(
        plugin_paths=[plugin_path],
        register_builtin_plugins=False,
    )
    try:
        assert runtime.plugin_assets is not None
        assert runtime.plugin_manager is not None
        assert [
            plugin.plugin_id for plugin in runtime.plugin_manager.list_plugins()
        ] == ["demo.hello"]
        assert [command.name for command in runtime.plugin_manager.list_commands()] == [
            "hello"
        ]
    finally:
        await runtime.close()


def test_build_cyrene_ai_runtime_loads_plugin_paths(tmp_path) -> None:
    asyncio.run(_run_build_runtime_loads_plugin_paths(tmp_path))


async def _run_build_runtime_resolves_project_relative_plugin_paths(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runtime = await build_cyrene_ai_runtime(
        plugin_paths=["examples/plugins/demo_hello"],
        register_builtin_plugins=False,
    )
    try:
        assert runtime.plugin_manager is not None
        assert [
            plugin.plugin_id for plugin in runtime.plugin_manager.list_plugins()
        ] == ["demo.hello"]
    finally:
        await runtime.close()


def test_build_runtime_resolves_project_relative_plugin_paths(
    tmp_path,
    monkeypatch,
) -> None:
    project_path = Path("examples/plugins/demo_hello")
    if not project_path.exists():
        pytest.skip("example plugin project is not available")

    asyncio.run(
        _run_build_runtime_resolves_project_relative_plugin_paths(
            tmp_path,
            monkeypatch,
        )
    )


async def _run_build_runtime_rejects_duplicate_plugin_storage_config(tmp_path) -> None:
    with pytest.raises(ValueError):
        await build_cyrene_ai_runtime(
            plugin_storage=FileSystemPluginStorage(tmp_path / "storage"),
            plugin_storage_path=tmp_path / "plugin_storage",
        )


def test_build_cyrene_ai_runtime_rejects_duplicate_plugin_storage_config(
    tmp_path,
) -> None:
    asyncio.run(_run_build_runtime_rejects_duplicate_plugin_storage_config(tmp_path))


async def _run_build_runtime_rejects_duplicate_bot_polling_state_config(
    tmp_path,
) -> None:
    with pytest.raises(ValueError):
        await build_cyrene_ai_runtime(
            bot_polling_state_store=InMemoryBotPollingStateStore(),
            bot_polling_state_database_path=tmp_path / "bot_polling.db",
        )


def test_build_cyrene_ai_runtime_rejects_duplicate_bot_polling_state_config(
    tmp_path,
) -> None:
    asyncio.run(_run_build_runtime_rejects_duplicate_bot_polling_state_config(tmp_path))


async def _run_build_runtime_rejects_duplicate_bot_session_config() -> None:
    with pytest.raises(ValueError):
        await build_cyrene_ai_runtime(
            bot_session_store=InMemoryBotSessionStore(),
            bot_session_manager=BotSessionManager(InMemoryBotSessionStore()),
        )


def test_build_cyrene_ai_runtime_rejects_duplicate_bot_session_config() -> None:
    asyncio.run(_run_build_runtime_rejects_duplicate_bot_session_config())
