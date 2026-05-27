from __future__ import annotations

import asyncio
import json

import pytest

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.schema.bot import BotChannelDefinition
from cyreneAI.core.schema.skill import SkillSelectionRequest
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition, ToolResult
from cyreneAI.core.schema.vector import VectorQuery, VectorRecord
from cyreneAI.infra.adapters.channels.memory import InMemoryBotChannel
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore
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
    assert runtime.tool_registry is not None
    assert runtime.tool_manager is not None

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
        _tool_call("call-1", "lookup", "{\"key\":\"value\"}")
    )
    assert result.content == "executed:{\"key\":\"value\"}"

    await runtime.vector_manager.upsert(
        [
            VectorRecord(
                record_id="record-1",
                vector=[1.0, 0.0],
                content="alpha",
            )
        ]
    )
    vector_result = await runtime.vector_manager.search(
        VectorQuery(vector=[1.0, 0.0])
    )
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
    assert isinstance(
        runtime.bot_channel_registry.get_channel("memory"),
        InMemoryBotChannel,
    )

    await runtime.close()


def test_build_cyrene_ai_runtime_can_enable_memory_bot_channel() -> None:
    asyncio.run(_run_build_runtime_can_enable_memory_bot_channel())


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


async def _run_build_runtime_rejects_duplicate_bot_session_config() -> None:
    with pytest.raises(ValueError):
        await build_cyrene_ai_runtime(
            bot_session_store=InMemoryBotSessionStore(),
            bot_session_manager=BotSessionManager(InMemoryBotSessionStore()),
        )


def test_build_cyrene_ai_runtime_rejects_duplicate_bot_session_config() -> None:
    asyncio.run(_run_build_runtime_rejects_duplicate_bot_session_config())
