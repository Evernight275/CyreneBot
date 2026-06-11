from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import AsyncIterator

from cyreneAI.application.chat.orchestrator import (
    ApplicationChatRequest,
    ChatOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.chat import (
    ChatFinishReason,
    ChatRequest,
    ChatStreamChunk,
    ChatStreamEventType,
    ToolCallDelta,
)
from cyreneAI.core.schema.context import ContextSnapshot
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition, ToolResult
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry


def _message(role: MessageRole, text: str) -> Message:
    return Message(
        role=role,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


class FakeContextStore:
    def __init__(self) -> None:
        self.snapshots: list[ContextSnapshot] = []

    async def save_snapshot(self, snapshot: ContextSnapshot) -> None:
        self.snapshots.append(snapshot)

    async def get_snapshot(self, snapshot_id: str) -> ContextSnapshot:
        for snapshot in self.snapshots:
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        raise KeyError(snapshot_id)

    async def list_snapshots(self, session_id: str) -> list[ContextSnapshot]:
        return [
            snapshot for snapshot in self.snapshots if snapshot.session_id == session_id
        ]

    async def delete_snapshot(self, snapshot_id: str) -> None:
        self.snapshots = [
            snapshot
            for snapshot in self.snapshots
            if snapshot.snapshot_id != snapshot_id
        ]

    async def delete_snapshots_for_session(self, session_id: str) -> int:
        deleted = [s for s in self.snapshots if s.session_id == session_id]
        self.snapshots = [s for s in self.snapshots if s.session_id != session_id]
        return len(deleted)


class StreamingFakeProvider:
    """按预设的 chunk 批次逐轮流式返回，支持工具轮次。"""

    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        name="fake-stream",
        description="Fake streaming provider.",
    )
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        timeout=timedelta(seconds=1),
    )

    def __init__(self, rounds: list[list[ChatStreamChunk]]) -> None:
        self._rounds = rounds
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest):  # pragma: no cover - 流式路径不会用到
        raise AssertionError("streaming provider should use chat_stream")

    async def chat_stream(
        self, request: ChatRequest
    ) -> AsyncIterator[ChatStreamChunk]:
        index = min(len(self.requests), len(self._rounds) - 1)
        self.requests.append(request)
        for chunk in self._rounds[index]:
            yield chunk

    async def close(self) -> None:
        pass


class NonStreamingFakeProvider:
    info = StreamingFakeProvider.info
    config = StreamingFakeProvider.config

    def __init__(self, text: str) -> None:
        self._text = text
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest):
        from cyreneAI.core.schema.chat import ChatResponse

        self.requests.append(request)
        return ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, self._text),
            finish_reason=ChatFinishReason.STOP,
        )

    async def close(self) -> None:
        pass


class RecordingToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=f"executed:{call.name}",
        )


async def _build_manager(provider) -> ProviderManager:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig):
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    manager = ProviderManager(factory)
    await manager.add(provider.config)
    return manager


def _text_chunk(text: str) -> ChatStreamChunk:
    return ChatStreamChunk(provider_id="provider-1", model="fake-model", delta_text=text)


async def _run_text_stream() -> None:
    provider = StreamingFakeProvider(
        [
            [
                _text_chunk("Hel"),
                _text_chunk("lo"),
                ChatStreamChunk(
                    provider_id="provider-1",
                    model="fake-model",
                    finish_reason=ChatFinishReason.STOP,
                ),
            ]
        ]
    )
    context_store = FakeContextStore()
    runtime = CyreneAIRuntime(
        provider_manager=await _build_manager(provider),
        context_builder=ContextWindowBuilder(),
        context_manager=ContextManager(context_store),
    )

    events = []
    async for event in ChatOrchestrator(runtime).chat_stream(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "hi")],
            stream=True,
        )
    ):
        events.append(event)

    deltas = [e.delta_text for e in events if e.type == ChatStreamEventType.DELTA]
    assert "".join(part or "" for part in deltas) == "Hello"

    done = [e for e in events if e.type == ChatStreamEventType.DONE]
    assert len(done) == 1
    assert done[0].content == "Hello"
    assert done[0].finish_reason == ChatFinishReason.STOP

    # 流式结束后落了一次上下文快照，供下一轮会话续接。
    assert len(context_store.snapshots) == 1
    assert context_store.snapshots[0].session_id == "session-1"


def test_chat_stream_streams_text_and_saves_snapshot() -> None:
    asyncio.run(_run_text_stream())


async def _run_tool_round_stream() -> None:
    tool_call_round = [
        ChatStreamChunk(
            provider_id="provider-1",
            model="fake-model",
            tool_call_deltas=[
                ToolCallDelta(index=0, id="call-1", name="lookup", arguments='{"k"'),
            ],
        ),
        ChatStreamChunk(
            provider_id="provider-1",
            model="fake-model",
            tool_call_deltas=[ToolCallDelta(index=0, arguments=':"v"}')],
            finish_reason=ChatFinishReason.TOOL_CALLS,
        ),
    ]
    final_round = [
        _text_chunk("done"),
        ChatStreamChunk(
            provider_id="provider-1",
            model="fake-model",
            finish_reason=ChatFinishReason.STOP,
        ),
    ]
    provider = StreamingFakeProvider([tool_call_round, final_round])

    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        RecordingToolExecutor(),
    )
    runtime = CyreneAIRuntime(
        provider_manager=await _build_manager(provider),
        context_builder=ContextWindowBuilder(),
        context_manager=ContextManager(FakeContextStore()),
        tool_registry=tool_registry,
        tool_manager=ToolManager(tool_registry),
    )

    events = []
    async for event in ChatOrchestrator(runtime).chat_stream(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "use lookup")],
            stream=True,
            max_tool_rounds=1,
        )
    ):
        events.append(event)

    tool_calls = [e for e in events if e.type == ChatStreamEventType.TOOL_CALL]
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_calls[0].name == "lookup"
    assert tool_calls[0].tool_calls[0].arguments == '{"k":"v"}'

    tool_results = [e for e in events if e.type == ChatStreamEventType.TOOL_RESULT]
    assert len(tool_results) == 1
    assert tool_results[0].tool_results[0].content == "executed:lookup"

    done = [e for e in events if e.type == ChatStreamEventType.DONE]
    assert len(done) == 1
    assert done[0].content == "done"
    # 两轮：工具轮 + 最终轮。
    assert len(provider.requests) == 2


def test_chat_stream_runs_tool_round_then_final_answer() -> None:
    asyncio.run(_run_tool_round_stream())


async def _run_non_streaming_fallback() -> None:
    provider = NonStreamingFakeProvider("plain answer")
    runtime = CyreneAIRuntime(
        provider_manager=await _build_manager(provider),
        context_builder=ContextWindowBuilder(),
        context_manager=ContextManager(FakeContextStore()),
    )

    events = []
    async for event in ChatOrchestrator(runtime).chat_stream(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "hi")],
            stream=True,
        )
    ):
        events.append(event)

    done = [e for e in events if e.type == ChatStreamEventType.DONE]
    assert len(done) == 1
    assert done[0].content == "plain answer"
    assert done[0].metadata.get("fallback") is True


def test_chat_stream_falls_back_when_provider_not_streaming() -> None:
    asyncio.run(_run_non_streaming_fallback())
