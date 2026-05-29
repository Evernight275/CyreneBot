from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cyreneAI.application.bot.orchestrator import (
    ApplicationBotRequest,
    BotOrchestrator,
)
from cyreneAI.application.plugins.builtin_bot_commands import (
    register_builtin_bot_command_plugins,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.plugin.registry import PluginRegistry
from cyreneAI.core.schema.bot import (
    BotAction,
    BotActionType,
    BotEvent,
    BotEventType,
    BotMessage,
)
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
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginEventDefinition,
    PluginEventRequest,
    PluginEventResult,
    PluginEventType,
)


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


class FakePluginExecutor:
    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        return PluginCommandResult(
            actions=[
                BotAction(
                    action_type=BotActionType.SEND_MESSAGE,
                    channel_id=request.event.channel_id if request.event else "memory",
                    session_id=request.event.session_id if request.event else "session",
                    recipient_id=request.event.user_id if request.event else None,
                    message=BotMessage(
                        sender_id="bot",
                        content=_content(
                            f"{request.command.name}:{request.command.args_text}"
                        ),
                    ),
                )
            ]
        )


class FakePluginEventExecutor:
    def __init__(self) -> None:
        self.calls: list[PluginEventRequest] = []

    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        self.calls.append(request)
        return PluginEventResult()


class FailingPluginEventExecutor:
    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        raise RuntimeError("event failed")


async def _build_runtime(provider: FakeChatProvider) -> CyreneAIRuntime:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig) -> FakeChatProvider:
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    provider_manager = ProviderManager(factory)
    await provider_manager.add(provider.config)
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
    )
    plugin_registry = PluginRegistry()
    runtime.plugin_manager = PluginManager(plugin_registry)
    register_builtin_bot_command_plugins(plugin_registry, runtime)
    return runtime


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


def test_bot_orchestrator_dispatches_narrow_plugin_message_event() -> None:
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
        assert runtime.plugin_manager is not None
        registry = runtime.plugin_manager._registry
        event_executor = FakePluginEventExecutor()
        registry.register(
            PluginDefinition(
                plugin_id="thirdparty.listener",
                name="Listener",
                description="Observe messages.",
                events=[
                    PluginEventDefinition(
                        event_type=PluginEventType.MESSAGE,
                        description="Observe messages.",
                    )
                ],
            ),
            event_executor=event_executor,
        )

        await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("hello listener"),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert len(event_executor.calls) == 1
        plugin_event = event_executor.calls[0].event
        assert plugin_event.event_id == "event-1"
        assert plugin_event.event_type == PluginEventType.MESSAGE
        assert plugin_event.session_id == "test-channel:user-1"
        assert plugin_event.user_id == "user-1"
        assert plugin_event.thread_id == "thread-1"
        assert plugin_event.message_id == "message-1"
        assert plugin_event.text == "hello listener"
        assert not hasattr(plugin_event, "channel_id")
        assert not hasattr(plugin_event, "metadata")

    asyncio.run(run())


def test_bot_orchestrator_continues_chat_when_plugin_event_fails() -> None:
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
        assert runtime.plugin_manager is not None
        registry = runtime.plugin_manager._registry
        registry.register(
            PluginDefinition(
                plugin_id="thirdparty.failing_listener",
                name="Failing Listener",
                description="Breaks during message events.",
                events=[
                    PluginEventDefinition(
                        event_type=PluginEventType.MESSAGE,
                        description="Observe messages.",
                    )
                ],
            ),
            event_executor=FailingPluginEventExecutor(),
        )

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("hello after failure"),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert len(provider.requests) == 1
        assert provider.requests[0].messages[-1].content == _content(
            "hello after failure"
        )
        assert len(result.actions) == 1
        assert result.actions[0].message is not None
        assert result.actions[0].message.content == _content("pong")

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


def test_bot_orchestrator_returns_command_result_without_provider_call() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
            )
        )
        runtime = await _build_runtime(provider)
        event = _bot_event('/echo "hello world" --limit 3')
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
        assert action.message.content == _content("hello world --limit 3")
        assert action.metadata["command"] == "echo"
        assert action.metadata["command_args"] == ["hello world", "--limit", "3"]
        assert result.metadata["command"] == "echo"

    asyncio.run(run())


def test_bot_orchestrator_executes_multi_segment_plugin_command() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
            )
        )
        runtime = await _build_runtime(provider)
        assert runtime.plugin_manager is not None
        registry = runtime.plugin_manager._registry
        registry.register(
            PluginDefinition(
                plugin_id="thirdparty.smart_filter",
                name="Smart Filter",
                description="Smart filter plugin.",
                commands=[
                    PluginCommandDefinition(
                        name="sf ban",
                        description="Ban user.",
                        aliases=["sf b"],
                    )
                ],
            ),
            FakePluginExecutor(),
        )

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("/sf ban user-1 PT1H"),
                provider_id="provider-1",
                model="fake-model",
                metadata={"is_admin": True},
            )
        )

        assert provider.requests == []
        assert result.actions[0].message is not None
        assert result.actions[0].message.content == _content("sf ban:user-1 PT1H")
        assert result.metadata["command"] == "sf ban"
        assert result.metadata["command_args"] == ["user-1", "PT1H"]

    asyncio.run(run())


def test_bot_orchestrator_executes_multi_segment_plugin_command_alias() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
            )
        )
        runtime = await _build_runtime(provider)
        assert runtime.plugin_manager is not None
        registry = runtime.plugin_manager._registry
        registry.register(
            PluginDefinition(
                plugin_id="thirdparty.smart_filter",
                name="Smart Filter",
                description="Smart filter plugin.",
                commands=[
                    PluginCommandDefinition(
                        name="sf ban",
                        description="Ban user.",
                        aliases=["sf b"],
                    )
                ],
            ),
            FakePluginExecutor(),
        )

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("/sf b user-1"),
                provider_id="provider-1",
                model="fake-model",
                metadata={"is_admin": True},
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content == _content("sf b:user-1")
        assert result.metadata["command"] == "sf b"
        assert result.metadata["command_args"] == ["user-1"]

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
                    "Available commands:",
                    "/start - Start the bot.",
                        "/help - Show available commands.",
                        "/ping - Check whether the bot is responsive.",
                        "/echo <text> - Echo text back.",
                    ]
                )
            )

    asyncio.run(run())


def test_bot_orchestrator_rejects_status_command_without_admin() -> None:
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
                event=_bot_event("/status"),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert provider.requests == []
        assert result.actions[0].message is not None
        assert result.actions[0].message.content == _content(
            "Command /status requires admin permission."
        )

    asyncio.run(run())


def test_bot_orchestrator_runs_status_command_for_admin() -> None:
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
                event=_bot_event("/status"),
                provider_id="provider-1",
                model="fake-model",
                metadata={"is_admin": True},
            )
        )

        assert provider.requests == []
        assert result.actions[0].message is not None
        assert result.actions[0].message.content == _content(
            "\n".join(
                [
                    "CyreneAI status:",
                    "providers: 1",
                    "bot_channels: 0",
                    "skills: disabled",
                    "tools: disabled",
                    "polling_state: disabled",
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
