from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cyreneAI.application.bot.dispatcher import BotDispatcher
from cyreneAI.application.bot.orchestrator import ApplicationBotRequest
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.bot import BotStateError
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


def _event() -> BotEvent:
    return BotEvent(
        event_id="event-1",
        event_type=BotEventType.MESSAGE,
        channel_id="memory",
        session_id="memory:user-1",
        user_id="user-1",
        message=BotMessage(
            sender_id="user-1",
            content=_content("hello"),
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
) -> CyreneAIRuntime:
    return CyreneAIRuntime(
        provider_manager=await _build_provider_manager(provider),
        context_builder=ContextWindowBuilder(),
        bot_channel_registry=channel_registry,
        bot_session_manager=session_manager,
    )


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

    asyncio.run(run())
