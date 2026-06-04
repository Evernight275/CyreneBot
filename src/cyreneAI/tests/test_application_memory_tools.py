from __future__ import annotations

import asyncio
import json

from cyreneAI.application.tools.execution_context import use_tool_execution_context
from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.schema.tool import ToolCall
from cyreneAI.infra.adapters.vector_stores.memory.store import InMemoryVectorStore


async def _run_memory_tools_round_trip() -> None:
    runtime = await build_cyrene_ai_runtime(
        vector_store=InMemoryVectorStore(),
        register_builtin_plugins=False,
    )
    try:
        assert runtime.tool_registry is not None
        assert runtime.tool_manager is not None

        tool_names = {
            definition.name for definition in runtime.tool_registry.list_definitions()
        }
        assert {
            "remember_fact",
            "search_memory",
            "get_memory",
            "forget_memory",
        }.issubset(tool_names)

        with use_tool_execution_context(
            session_id="session-1",
            provider_id="provider-1",
            model="model-1",
        ):
            remember_result = await runtime.tool_manager.execute(
                ToolCall(
                    id="call-1",
                    name="remember_fact",
                    arguments=json.dumps(
                        {
                            "content": "The user prefers concise Chinese replies.",
                            "tags": ["preference"],
                        }
                    ),
                )
            )
        remember_payload = json.loads(remember_result.content or "{}")
        memory_id = remember_payload["memory_id"]
        assert remember_payload["namespace"] == "session-1"

        search_result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-2",
                name="search_memory",
                arguments=json.dumps(
                    {
                        "query": "concise Chinese replies",
                        "namespace": "session-1",
                        "top_k": 3,
                    }
                ),
            )
        )
        search_payload = json.loads(search_result.content or "{}")
        assert search_payload["matches"][0]["memory_id"] == memory_id
        assert "concise Chinese" in search_payload["matches"][0]["content"]

        get_result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-3",
                name="get_memory",
                arguments=json.dumps({"memory_id": memory_id}),
            )
        )
        get_payload = json.loads(get_result.content or "{}")
        assert get_payload["metadata"]["kind"] == "agent_memory"
        assert get_payload["metadata"]["session_id"] == "session-1"

        forget_result = await runtime.tool_manager.execute(
            ToolCall(
                id="call-4",
                name="forget_memory",
                arguments=json.dumps({"memory_id": memory_id}),
            )
        )
        forget_payload = json.loads(forget_result.content or "{}")
        assert forget_payload == {
            "deleted": True,
            "memory_id": memory_id,
        }
    finally:
        await runtime.close()


def test_memory_tools_round_trip() -> None:
    asyncio.run(_run_memory_tools_round_trip())


async def _run_memory_tools_are_skipped_without_vector_store() -> None:
    runtime = await build_cyrene_ai_runtime(register_builtin_plugins=False)
    try:
        assert runtime.tool_registry is not None
        tool_names = {
            definition.name for definition in runtime.tool_registry.list_definitions()
        }
        assert "remember_fact" not in tool_names
        assert "search_memory" not in tool_names
    finally:
        await runtime.close()


def test_memory_tools_are_skipped_without_vector_store() -> None:
    asyncio.run(_run_memory_tools_are_skipped_without_vector_store())
