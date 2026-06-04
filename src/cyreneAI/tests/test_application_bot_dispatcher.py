from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cyreneAI.application.bot.dispatcher import BotDispatcher
from cyreneAI.application.bot.orchestrator import ApplicationBotRequest
from cyreneAI.application.plugins.builtin_bot_commands import (
    register_builtin_bot_command_plugins,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.errors.bot import BotActionError, BotStateError
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.plugin.registry import PluginRegistry
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.bot import (
    BotActionType,
    BotChannelDefinition,
    BotEvent,
    BotEventType,
    BotMessage,
)
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest, ChatResponse
from cyreneAI.core.schema.context import ContextSnapshot
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore
from cyreneAI.infra.adapters.channels.memory import InMemoryBotChannel


def _content(text: str) -> list[ContentPart]:
    return [
        ContentPart(
            type=ContentPartType.TEXT,
            text=text,
        )
    ]


def _event(text: str = "hello", *, event_id: str = "event-1") -> BotEvent:
    return BotEvent(
        event_id=event_id,
        event_type=BotEventType.MESSAGE,
        channel_id="memory",
        session_id="memory:user-1",
        user_id="user-1",
        message=BotMessage(
            sender_id="user-1",
            content=_content(text),
        ),
    )


class FakeChatProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        name="fake",
        description="Fake chat provider.",
    )
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        timeout=timedelta(seconds=1),
    )

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            provider_id=request.provider_id,
            model=request.model,
            message=Message(
                role=MessageRole.ASSISTANT,
                content=_content("pong"),
            ),
            finish_reason=ChatFinishReason.STOP,
        )

    async def close(self) -> None:
        pass


class FailingChannel:
    async def send(self, action) -> None:
        raise BotActionError("send failed")


class FakeContextStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, ContextSnapshot] = {}

    async def save_snapshot(self, snapshot: ContextSnapshot) -> None:
        self.snapshots[snapshot.snapshot_id] = snapshot

    async def get_snapshot(self, snapshot_id: str) -> ContextSnapshot:
        return self.snapshots[snapshot_id]

    async def list_snapshots(self, session_id: str) -> list[ContextSnapshot]:
        return [
            snapshot
            for snapshot in self.snapshots.values()
            if snapshot.session_id == session_id
        ]

    async def delete_snapshot(self, snapshot_id: str) -> None:
        self.snapshots.pop(snapshot_id, None)

    async def delete_snapshots_for_session(self, session_id: str) -> int:
        snapshot_ids = [
            snapshot.snapshot_id
            for snapshot in self.snapshots.values()
            if snapshot.session_id == session_id
        ]
        for snapshot_id in snapshot_ids:
            self.snapshots.pop(snapshot_id, None)
        return len(snapshot_ids)


async def _build_provider_manager(provider: FakeChatProvider) -> ProviderManager:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig) -> FakeChatProvider:
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    manager = ProviderManager(factory)
    await manager.add(provider.config)
    return manager


async def _build_runtime(
    *,
    provider: FakeChatProvider,
    channel_registry: BotChannelRegistry | None,
    session_manager: BotSessionManager | None = None,
    context_manager: ContextManager | None = None,
    register_builtin_commands: bool = False,
) -> CyreneAIRuntime:
    runtime = CyreneAIRuntime(
        provider_manager=await _build_provider_manager(provider),
        context_builder=ContextWindowBuilder(),
        context_manager=context_manager,
        bot_channel_registry=channel_registry,
        bot_session_manager=session_manager,
    )
    if register_builtin_commands:
        plugin_registry = PluginRegistry()
        runtime.plugin_manager = PluginManager(plugin_registry)
        register_builtin_bot_command_plugins(plugin_registry, runtime)
    return runtime


def test_bot_dispatcher_sends_actions_to_registered_channel() -> None:
    async def run() -> None:
        provider = FakeChatProvider()
        memory_channel = InMemoryBotChannel()
        channel_registry = BotChannelRegistry()
        channel_registry.register(
            BotChannelDefinition(
                channel_id="memory",
                name="Memory",
            ),
            memory_channel,
        )
        runtime = await _build_runtime(
            provider=provider,
            channel_registry=channel_registry,
        )

        result = await BotDispatcher(runtime).dispatch(
            ApplicationBotRequest(
                event=_event(),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert len(result.sent_actions) == 1
        assert result.sent_actions[0].action_type == BotActionType.SEND_MESSAGE
        assert memory_channel.list_actions() == result.sent_actions
        assert memory_channel.actions[0].message is not None
        assert memory_channel.actions[0].message.content == _content("pong")
        assert len(provider.requests) == 1

    asyncio.run(run())


def test_bot_dispatcher_requires_channel_registry() -> None:
    async def run() -> None:
        runtime = await _build_runtime(
            provider=FakeChatProvider(),
            channel_registry=None,
        )

        with pytest.raises(BotStateError):
            await BotDispatcher(runtime).dispatch(
                ApplicationBotRequest(
                    event=_event(),
                    provider_id="provider-1",
                    model="fake-model",
                )
            )

    asyncio.run(run())


def test_bot_dispatcher_updates_session_state_when_configured() -> None:
    async def run() -> None:
        provider = FakeChatProvider()
        memory_channel = InMemoryBotChannel()
        channel_registry = BotChannelRegistry()
        channel_registry.register(
            BotChannelDefinition(
                channel_id="memory",
                name="Memory",
            ),
            memory_channel,
        )
        store = InMemoryBotSessionStore()
        runtime = await _build_runtime(
            provider=provider,
            channel_registry=channel_registry,
            session_manager=BotSessionManager(store),
        )

        result = await BotDispatcher(runtime).dispatch(
            ApplicationBotRequest(
                event=_event(),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert result.session_state is not None
        assert result.session_state.session.session_id == "memory:user-1"
        assert result.session_state.turn_count == 1
        assert result.session_state.last_event_id == "event-1"
        assert (await store.get_state("memory:user-1")) == result.session_state
        assert provider.requests[0].metadata["bot_session_id"] == "memory:user-1"
        assert provider.requests[0].metadata["bot_turn_count"] == "1"
        assert (
            provider.requests[0].metadata["session_id"]
            == "memory:user-1:conversation:default"
        )
        assert (
            provider.requests[0].metadata["context_session_id"]
            == "memory:user-1:conversation:default"
        )
        assert (
            result.bot_result.chat_result is not None
            and result.bot_result.chat_result.context_snapshot.session_id
            == "memory:user-1:conversation:default"
        )
        assert (
            result.session_state.metadata["context_session_id"]
            == "memory:user-1:conversation:default"
        )

    asyncio.run(run())


def test_bot_dispatcher_routes_context_by_active_conversation() -> None:
    async def run() -> None:
        provider = FakeChatProvider()
        memory_channel = InMemoryBotChannel()
        channel_registry = BotChannelRegistry()
        channel_registry.register(
            BotChannelDefinition(
                channel_id="memory",
                name="Memory",
            ),
            memory_channel,
        )
        session_store = InMemoryBotSessionStore()
        context_store = FakeContextStore()
        runtime = await _build_runtime(
            provider=provider,
            channel_registry=channel_registry,
            session_manager=BotSessionManager(session_store),
            context_manager=ContextManager(context_store),
            register_builtin_commands=True,
        )
        dispatcher = BotDispatcher(runtime)

        await dispatcher.dispatch(
            ApplicationBotRequest(
                event=_event("default hello", event_id="event-1"),
                provider_id="provider-1",
                model="fake-model",
            )
        )
        await dispatcher.dispatch(
            ApplicationBotRequest(
                event=_event("/session new work", event_id="event-2"),
                provider_id="provider-1",
                model="fake-model",
            )
        )
        await dispatcher.dispatch(
            ApplicationBotRequest(
                event=_event("work hello", event_id="event-3"),
                provider_id="provider-1",
                model="fake-model",
            )
        )
        await dispatcher.dispatch(
            ApplicationBotRequest(
                event=_event("/session use default", event_id="event-4"),
                provider_id="provider-1",
                model="fake-model",
            )
        )
        await dispatcher.dispatch(
            ApplicationBotRequest(
                event=_event("default again", event_id="event-5"),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        default_context_id = "memory:user-1:conversation:default"
        work_context_id = "memory:user-1:conversation:work"
        assert [request.metadata["session_id"] for request in provider.requests] == [
            default_context_id,
            work_context_id,
            default_context_id,
        ]
        assert len(provider.requests[0].messages) == 1
        assert len(provider.requests[1].messages) == 1
        assert len(provider.requests[2].messages) == 3
        assert provider.requests[2].messages[0].content == _content("default hello")
        assert provider.requests[2].messages[-1].content == _content("default again")
        assert len(await context_store.list_snapshots(default_context_id)) == 2
        assert len(await context_store.list_snapshots(work_context_id)) == 1

    asyncio.run(run())


def test_bot_dispatcher_isolates_action_send_failure() -> None:
    async def run() -> None:
        provider = FakeChatProvider()
        channel_registry = BotChannelRegistry()
        channel_registry.register(
            BotChannelDefinition(
                channel_id="memory",
                name="Memory",
            ),
            FailingChannel(),
        )
        runtime = await _build_runtime(
            provider=provider,
            channel_registry=channel_registry,
        )

        result = await BotDispatcher(runtime).dispatch(
            ApplicationBotRequest(
                event=_event(),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert len(provider.requests) == 1
        assert result.bot_result.actions[0].message is not None
        assert result.bot_result.actions[0].message.content == _content("pong")
        assert result.sent_actions == []

    asyncio.run(run())
