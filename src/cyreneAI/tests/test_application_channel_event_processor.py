from __future__ import annotations

import asyncio
from datetime import timedelta

from cyreneAI.application.channels.event_processor import (
    ApplicationChannelEventsRequest,
    ChannelEventProcessor,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.bot import (
    BotAction,
    BotChannelDefinition,
    BotEvent,
    BotEventType,
    BotMessage,
)
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest, ChatResponse
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore


def _content(text: str) -> list[ContentPart]:
    return [
        ContentPart(
            type=ContentPartType.TEXT,
            text=text,
        )
    ]


def _event(
    event_id: str,
    text: str,
    *,
    session_id: str = "fake:user-1",
) -> BotEvent:
    return BotEvent(
        event_id=event_id,
        event_type=BotEventType.MESSAGE,
        channel_id="fake",
        session_id=session_id,
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
        text = request.messages[-1].content[0].text if request.messages[-1].content else ""
        return ChatResponse(
            provider_id=request.provider_id,
            model=request.model,
            message=Message(
                role=MessageRole.ASSISTANT,
                content=_content(f"reply:{text}"),
            ),
            finish_reason=ChatFinishReason.STOP,
        )

    async def close(self) -> None:
        pass


class FakeChannel:
    def __init__(self) -> None:
        self.actions: list[BotAction] = []

    async def send(self, action: BotAction) -> None:
        self.actions.append(action)


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
    channel: FakeChannel,
    session_manager: BotSessionManager | None = None,
) -> CyreneAIRuntime:
    registry = BotChannelRegistry()
    registry.register(
        BotChannelDefinition(
            channel_id="fake",
            name="Fake",
        ),
        channel,
    )
    return CyreneAIRuntime(
        provider_manager=await _build_provider_manager(provider),
        context_builder=ContextWindowBuilder(),
        bot_channel_registry=registry,
        bot_session_manager=session_manager,
    )


def test_channel_event_processor_dispatches_events_in_order() -> None:
    async def run() -> None:
        provider = FakeChatProvider()
        channel = FakeChannel()
        runtime = await _build_runtime(provider=provider, channel=channel)

        result = await ChannelEventProcessor(runtime).process(
            ApplicationChannelEventsRequest(
                events=[
                    _event("event-1", "one"),
                    _event("event-2", "two"),
                ],
                provider_id="provider-1",
                model="fake-model",
                metadata={"source": "polling"},
            )
        )

        assert len(result.dispatch_results) == 2
        assert result.metadata["channel_event_count"] == "2"
        assert [request.messages[-1].content for request in provider.requests] == [
            _content("one"),
            _content("two"),
        ]
        assert provider.requests[0].metadata["channel_event_count"] == "2"
        assert provider.requests[0].metadata["channel_event_index"] == "0"
        assert provider.requests[0].metadata["source"] == "polling"
        assert provider.requests[1].metadata["channel_event_index"] == "1"
        assert len(channel.actions) == 2
        assert channel.actions[0].message is not None
        assert channel.actions[0].message.content == _content("reply:one")
        assert channel.actions[1].message is not None
        assert channel.actions[1].message.content == _content("reply:two")

    asyncio.run(run())


def test_channel_event_processor_handles_empty_events() -> None:
    async def run() -> None:
        provider = FakeChatProvider()
        channel = FakeChannel()
        runtime = await _build_runtime(provider=provider, channel=channel)

        result = await ChannelEventProcessor(runtime).process(
            ApplicationChannelEventsRequest(
                events=[],
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert result.dispatch_results == []
        assert result.metadata["channel_event_count"] == "0"
        assert provider.requests == []
        assert channel.actions == []

    asyncio.run(run())


def test_channel_event_processor_updates_session_turns() -> None:
    async def run() -> None:
        provider = FakeChatProvider()
        channel = FakeChannel()
        session_store = InMemoryBotSessionStore()
        runtime = await _build_runtime(
            provider=provider,
            channel=channel,
            session_manager=BotSessionManager(session_store),
        )

        result = await ChannelEventProcessor(runtime).process(
            ApplicationChannelEventsRequest(
                events=[
                    _event("event-1", "one"),
                    _event("event-2", "two"),
                ],
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert result.dispatch_results[0].session_state is not None
        assert result.dispatch_results[0].session_state.turn_count == 1
        assert result.dispatch_results[1].session_state is not None
        assert result.dispatch_results[1].session_state.turn_count == 2
        state = await session_store.get_state("fake:user-1")
        assert state.turn_count == 2
        assert state.last_event_id == "event-2"

    asyncio.run(run())
