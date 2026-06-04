from __future__ import annotations

import asyncio
from datetime import timedelta

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.registry import BotChannelRegistry
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
from cyreneAI.server.channel_websocket import ChannelWebSocketRunner


def _content(text: str) -> list[ContentPart]:
    return [
        ContentPart(
            type=ContentPartType.TEXT,
            text=text,
        )
    ]


class FakeWebSocketProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        name="fake",
        description="Fake websocket provider.",
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


class FakeWebSocketChannel:
    def __init__(self) -> None:
        self.actions: list[BotAction] = []
        self.handler = None
        self.closed = False

    def map_update(self, update: dict) -> BotEvent:
        data = update["d"]
        return BotEvent(
            event_id=str(data["id"]),
            event_type=BotEventType.MESSAGE,
            channel_id="qq",
            session_id=f"qq:channel:{data['channel_id']}",
            user_id=data["author"]["id"],
            thread_id=data["channel_id"],
            message=BotMessage(
                sender_id=data["author"]["id"],
                content=_content(str(data["content"])),
            ),
        )

    async def run_websocket(self, handler) -> None:
        self.handler = handler
        await handler(
            {
                "id": "event-1",
                "t": "AT_MESSAGE_CREATE",
                "d": {
                    "id": "message-1",
                    "channel_id": "channel-1",
                    "author": {"id": "user-1"},
                    "content": "ping",
                },
            }
        )

    async def close_websocket(self) -> None:
        self.closed = True

    async def send(self, action: BotAction) -> None:
        self.actions.append(action)


async def _build_runtime(
    provider: FakeWebSocketProvider,
    channel: FakeWebSocketChannel,
) -> CyreneAIRuntime:
    registry = BotChannelRegistry()
    registry.register(
        BotChannelDefinition(
            channel_id="qq",
            name="QQ",
        ),
        channel,
    )
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig) -> FakeWebSocketProvider:
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    manager = ProviderManager(factory)
    await manager.add(provider.config)
    return CyreneAIRuntime(
        provider_manager=manager,
        context_builder=ContextWindowBuilder(),
        bot_channel_registry=registry,
    )


def test_channel_websocket_runner_processes_updates() -> None:
    async def run() -> None:
        provider = FakeWebSocketProvider()
        channel = FakeWebSocketChannel()
        runtime = await _build_runtime(provider, channel)
        runner = ChannelWebSocketRunner(
            runtime=runtime,
            channel_id="qq",
            provider_id="provider-1",
            model="chat-model",
            metadata={"source": "test"},
        )

        await runner.run_until_closed()

        assert len(provider.requests) == 1
        assert provider.requests[0].messages[-1].content == _content("ping")
        assert provider.requests[0].metadata["websocket_channel_id"] == "qq"
        assert provider.requests[0].metadata["source"] == "test"
        assert len(channel.actions) == 1
        assert channel.actions[0].message is not None
        assert channel.actions[0].message.content == _content("reply:ping")
        await runtime.close()

    asyncio.run(run())


def test_channel_websocket_runner_closes_channel_source() -> None:
    async def run() -> None:
        provider = FakeWebSocketProvider()
        channel = FakeWebSocketChannel()
        runtime = await _build_runtime(provider, channel)
        runner = ChannelWebSocketRunner(
            runtime=runtime,
            channel_id="qq",
            provider_id="provider-1",
            model="chat-model",
        )

        await runner.stop()

        assert channel.closed is True
        await runtime.close()

    asyncio.run(run())
