from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cyreneAI.application.bot.orchestrator import (
    ApplicationBotRequest,
    BotOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.schema.bot import BotActionType, BotEvent, BotEventType, BotMessage
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.bot import BotInputError, BotUnsupportedEventError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest, ChatResponse
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType


def _content(text: str) -> list[ContentPart]:
    return [
        ContentPart(
            type=ContentPartType.TEXT,
            text=text,
        )
    ]


def _chat_message(role: MessageRole, text: str) -> Message:
    return Message(
        role=role,
        content=_content(text),
    )


def _bot_event(text: str = "hello") -> BotEvent:
    return BotEvent(
        event_id="event-1",
        event_type=BotEventType.MESSAGE,
        channel_id="test-channel",
        session_id="test-channel:user-1",
        user_id="user-1",
        thread_id="thread-1",
        message=BotMessage(
            message_id="message-1",
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

    def __init__(self, response: ChatResponse) -> None:
        self.response = response
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return self.response

    async def close(self) -> None:
        pass


async def _build_runtime(provider: FakeChatProvider) -> CyreneAIRuntime:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig) -> FakeChatProvider:
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    provider_manager = ProviderManager(factory)
    await provider_manager.add(provider.config)
    return CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
    )


def test_bot_orchestrator_turns_message_event_into_send_action() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_chat_message(MessageRole.ASSISTANT, "pong"),
                finish_reason=ChatFinishReason.STOP,
            )
        )
        runtime = await _build_runtime(provider)

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event(),
                provider_id="provider-1",
                model="fake-model",
                temperature=0,
                max_tokens=32,
            )
        )

        assert len(provider.requests) == 1
        provider_request = provider.requests[0]
        assert provider_request.provider_id == "provider-1"
        assert provider_request.model == "fake-model"
        assert provider_request.temperature == 0
        assert provider_request.max_tokens == 32
        assert provider_request.metadata["bot_event_id"] == "event-1"
        assert provider_request.messages[-1].role == MessageRole.USER
        assert provider_request.messages[-1].content == _content("hello")

        assert len(result.actions) == 1
        action = result.actions[0]
        assert action.action_type == BotActionType.SEND_MESSAGE
        assert action.channel_id == "test-channel"
        assert action.session_id == "test-channel:user-1"
        assert action.recipient_id == "user-1"
        assert action.thread_id == "thread-1"
        assert action.message is not None
        assert action.message.content == _content("pong")
        assert result.chat_result is not None
        assert result.chat_result.response.finish_reason == ChatFinishReason.STOP

    asyncio.run(run())


def test_bot_orchestrator_rejects_unsupported_event_type() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
            )
        )
        runtime = await _build_runtime(provider)
        event = _bot_event()
        event = event.model_copy(update={"event_type": BotEventType.MEMBER_JOINED})

        with pytest.raises(BotUnsupportedEventError):
            await BotOrchestrator(runtime).handle(
                ApplicationBotRequest(
                    event=event,
                    provider_id="provider-1",
                    model="fake-model",
                )
            )

    asyncio.run(run())


def test_bot_orchestrator_returns_command_parse_result_without_provider_call() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
            )
        )
        runtime = await _build_runtime(provider)
        event = _bot_event('/search "hello world" --limit 3')
        event = event.model_copy(update={"event_type": BotEventType.COMMAND})

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=event,
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert provider.requests == []
        assert result.chat_result is None
        assert len(result.actions) == 1
        action = result.actions[0]
        assert action.action_type == BotActionType.SEND_MESSAGE
        assert action.message is not None
        assert action.message.content == _content(
            "\n".join(
                [
                    "command: search",
                    "args: hello world, --limit, 3",
                    "args_text: hello world --limit 3",
                ]
            )
        )
        assert action.metadata["command"] == "search"
        assert action.metadata["command_args"] == ["hello world", "--limit", "3"]
        assert result.metadata["command"] == "search"

    asyncio.run(run())


def test_bot_orchestrator_treats_slash_message_as_command() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
            )
        )
        runtime = await _build_runtime(provider)

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("/help"),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert provider.requests == []
        assert result.actions[0].message is not None
        assert result.actions[0].message.content == _content(
            "\n".join(
                [
                    "command: help",
                    "args: (none)",
                    "args_text: (empty)",
                ]
            )
        )

    asyncio.run(run())


def test_bot_orchestrator_requires_message_content() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
            )
        )
        runtime = await _build_runtime(provider)
        event = _bot_event()
        event = event.model_copy(update={"message": None})

        with pytest.raises(BotInputError):
            await BotOrchestrator(runtime).handle(
                ApplicationBotRequest(
                    event=event,
                    provider_id="provider-1",
                    model="fake-model",
                )
            )

    asyncio.run(run())
