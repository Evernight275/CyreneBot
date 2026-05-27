from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from cyreneAI.application.channel_webhook_handler import (
    ApplicationChannelWebhookRequest,
    ChannelWebhookHandler,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.base import UnsupportedError
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
from cyreneAI.infra.adapters.channels.memory import InMemoryBotChannel
from cyreneAI.infra.adapters.channels.telegram import TelegramBotChannel


def _content(text: str) -> list[ContentPart]:
    return [
        ContentPart(
            type=ContentPartType.TEXT,
            text=text,
        )
    ]


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


class FakeWebhookChannel:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.actions: list[BotAction] = []

    def map_update(self, update: dict[str, Any]) -> BotEvent:
        self.payloads.append(update)
        return BotEvent(
            event_id=str(update["event_id"]),
            event_type=BotEventType.MESSAGE,
            channel_id="fake",
            session_id="fake:user-1",
            user_id="user-1",
            message=BotMessage(
                sender_id="user-1",
                content=_content(str(update["text"])),
            ),
        )

    async def send(self, action: BotAction) -> None:
        self.actions.append(action)


class FakeTelegramClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def send_message(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"message_id": 1}


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
    registry: BotChannelRegistry,
) -> CyreneAIRuntime:
    return CyreneAIRuntime(
        provider_manager=await _build_provider_manager(provider),
        context_builder=ContextWindowBuilder(),
        bot_channel_registry=registry,
    )


def test_channel_webhook_handler_dispatches_mapped_event() -> None:
    async def run() -> None:
        provider = FakeChatProvider()
        channel = FakeWebhookChannel()
        registry = BotChannelRegistry()
        registry.register(
            BotChannelDefinition(
                channel_id="fake",
                name="Fake",
            ),
            channel,
        )
        runtime = await _build_runtime(provider=provider, registry=registry)

        result = await ChannelWebhookHandler(runtime).handle(
            ApplicationChannelWebhookRequest(
                channel_id="fake",
                payload={
                    "event_id": "event-1",
                    "text": "hello",
                },
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert channel.payloads == [{"event_id": "event-1", "text": "hello"}]
        assert len(channel.actions) == 1
        assert result.sent_actions == channel.actions
        assert provider.requests[0].messages[-1].content == _content("hello")
        assert provider.requests[0].metadata["webhook_channel_id"] == "fake"

    asyncio.run(run())


def test_channel_webhook_handler_rejects_channel_without_mapper() -> None:
    async def run() -> None:
        registry = BotChannelRegistry()
        registry.register(
            BotChannelDefinition(
                channel_id="memory",
                name="Memory",
            ),
            InMemoryBotChannel(),
        )
        runtime = await _build_runtime(
            provider=FakeChatProvider(),
            registry=registry,
        )

        with pytest.raises(UnsupportedError):
            await ChannelWebhookHandler(runtime).handle(
                ApplicationChannelWebhookRequest(
                    channel_id="memory",
                    payload={},
                    provider_id="provider-1",
                    model="fake-model",
                )
            )

    asyncio.run(run())


def test_channel_webhook_handler_handles_telegram_update() -> None:
    async def run() -> None:
        provider = FakeChatProvider()
        telegram_client = FakeTelegramClient()
        telegram_channel = TelegramBotChannel(bot_client=telegram_client)
        registry = BotChannelRegistry()
        registry.register(
            BotChannelDefinition(
                channel_id="telegram",
                name="Telegram",
            ),
            telegram_channel,
        )
        runtime = await _build_runtime(provider=provider, registry=registry)

        await ChannelWebhookHandler(runtime).handle(
            ApplicationChannelWebhookRequest(
                channel_id="telegram",
                payload={
                    "update_id": 1000,
                    "message": {
                        "message_id": 10,
                        "from": {"id": 42},
                        "chat": {"id": 99, "type": "private"},
                        "text": "hello",
                    },
                },
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert provider.requests[0].messages[-1].content == _content("hello")
        assert telegram_client.payloads == [
            {
                "chat_id": "99",
                "text": "pong",
            }
        ]

    asyncio.run(run())
