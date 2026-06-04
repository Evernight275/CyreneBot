from __future__ import annotations

import asyncio
import logging
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
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.errors.base import NotFoundError
from cyreneAI.core.errors.bot import BotInputError, BotUnsupportedEventError
from cyreneAI.core.errors.plugin import PluginInputError
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.plugin.registry import PluginRegistry
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.agent import AgentPlanningConfig
from cyreneAI.core.schema.application import (
    BotAdminConfig,
    BotMessageResponseMode,
    BotMessageTriggerMode,
)
from cyreneAI.core.schema.bot import (
    BotAction,
    BotActionType,
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
        metadata={
            "qq_message_id": "message-1",
            "qq_channel_id": "thread-1",
        },
    )


def _telegram_event(
    text: str = "hello",
    *,
    chat_type: str = "private",
) -> BotEvent:
    event = _bot_event(text)
    message = event.message
    assert message is not None
    return event.model_copy(
        update={
            "channel_id": "telegram",
            "session_id": "telegram:99",
            "thread_id": "99",
            "message": message.model_copy(
                update={
                    "metadata": {
                        "telegram_chat_type": chat_type,
                    }
                }
            ),
            "metadata": {
                "telegram_chat_id": "99",
                "telegram_chat_type": chat_type,
            },
        }
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


class InputErrorPluginExecutor:
    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        raise PluginInputError("插件命令 search 缺少参数 query；用法: /search <query>")


class FailingPluginExecutor:
    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        raise RuntimeError("command failed")


class FakePluginEventExecutor:
    def __init__(self) -> None:
        self.calls: list[PluginEventRequest] = []

    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        self.calls.append(request)
        return PluginEventResult()


class FailingPluginEventExecutor:
    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        raise RuntimeError("event failed")


class MemoryProviderConfigStore:
    def __init__(self) -> None:
        self.configs: dict[str, ProviderConfig] = {}

    async def list_configs(self) -> list[ProviderConfig]:
        return list(self.configs.values())

    async def get_config(self, provider_id: str) -> ProviderConfig:
        config = self.configs.get(provider_id)
        if config is None:
            raise NotFoundError(f"Provider config not found: {provider_id}")
        return config

    async def upsert_config(self, config: ProviderConfig) -> ProviderConfig:
        self.configs[config.provider_id] = config
        return config

    async def delete_config(self, provider_id: str) -> None:
        self.configs.pop(provider_id, None)

    async def close(self) -> None:
        return None


async def _build_runtime(
    provider: FakeChatProvider,
    *,
    bot_admin_config: BotAdminConfig | None = None,
    provider_config_store: MemoryProviderConfigStore | None = None,
) -> CyreneAIRuntime:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig) -> FakeChatProvider:
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    provider_manager = ProviderManager(factory)
    await provider_manager.add(provider.config)
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
        provider_config_store=provider_config_store,
        bot_admin_config=bot_admin_config,
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
        assert action.metadata["qq_message_id"] == "message-1"
        assert action.metadata["qq_channel_id"] == "thread-1"
        assert result.chat_result is not None
        assert result.chat_result.response.finish_reason == ChatFinishReason.STOP

    asyncio.run(run())


def test_bot_orchestrator_uses_metadata_context_session_id() -> None:
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
                metadata={
                    "context_session_id": "test-channel:user-1:conversation:work",
                },
            )
        )

        assert provider.requests[0].metadata["session_id"] == (
            "test-channel:user-1:conversation:work"
        )
        assert result.chat_result is not None
        assert result.chat_result.context_snapshot.session_id == (
            "test-channel:user-1:conversation:work"
        )

    asyncio.run(run())


def test_bot_orchestrator_can_run_agent_for_direct_non_command_message() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_chat_message(MessageRole.ASSISTANT, "agent pong"),
                finish_reason=ChatFinishReason.STOP,
            )
        )
        runtime = await _build_runtime(provider)

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_telegram_event("hello agent"),
                provider_id="provider-1",
                model="fake-model",
                message_response_mode=BotMessageResponseMode.AGENT,
                message_trigger_mode=BotMessageTriggerMode.DIRECT,
                max_agent_tool_calls_per_step=2,
                max_agent_total_tool_calls=3,
                max_agent_tool_result_chars=256,
                agent_planning=AgentPlanningConfig(
                    enabled=True,
                    instructions="Answer through agent mode.",
                ),
            )
        )

        assert len(provider.requests) == 1
        assert provider.requests[0].messages[0].name == "agent_plan"
        assert provider.requests[0].messages[0].content is not None
        assert (
            "Answer through agent mode."
            in provider.requests[0].messages[0].content[0].text
        )
        assert provider.requests[0].metadata["max_tool_calls_per_step"] == 2
        assert provider.requests[0].metadata["max_total_tool_calls"] == 3
        assert provider.requests[0].metadata["max_tool_result_chars"] == 256
        assert provider.requests[0].metadata["agent_plan_mode"] == "planner_step"
        assert provider.requests[0].metadata["agent_plan_step_count"] >= 1
        assert provider.requests[0].messages[-1].content == _content("hello agent")
        assert result.chat_result is None
        assert result.agent_result is not None
        assert result.actions[0].message is not None
        assert result.actions[0].message.content == _content("agent pong")
        assert result.actions[0].metadata["agent_completed"] is True

    asyncio.run(run())


def test_bot_orchestrator_skips_send_action_for_empty_chat_response() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=[],
                ),
                finish_reason=ChatFinishReason.STOP,
            )
        )
        runtime = await _build_runtime(provider)

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event(),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert len(provider.requests) == 1
        assert result.actions == []
        assert result.chat_result is not None

    asyncio.run(run())


def test_bot_orchestrator_skips_send_action_for_empty_agent_response() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=[],
                ),
                finish_reason=ChatFinishReason.STOP,
            )
        )
        runtime = await _build_runtime(provider)

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_telegram_event("hello agent"),
                provider_id="provider-1",
                model="fake-model",
                message_response_mode=BotMessageResponseMode.AGENT,
                message_trigger_mode=BotMessageTriggerMode.DIRECT,
            )
        )

        assert len(provider.requests) == 1
        assert result.actions == []
        assert result.agent_result is not None

    asyncio.run(run())


def test_bot_orchestrator_skips_group_message_when_direct_trigger_required() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
                finish_reason=ChatFinishReason.STOP,
            )
        )
        runtime = await _build_runtime(provider)

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_telegram_event("group noise", chat_type="group"),
                provider_id="provider-1",
                model="fake-model",
                message_trigger_mode=BotMessageTriggerMode.DIRECT,
            )
        )

        assert provider.requests == []
        assert result.actions == []
        assert result.metadata["message_triggered"] is False
        assert result.metadata["message_trigger_mode"] == "direct"

    asyncio.run(run())


def test_bot_orchestrator_triggers_keyword_message_without_slash() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_chat_message(MessageRole.ASSISTANT, "keyword pong"),
                finish_reason=ChatFinishReason.STOP,
            )
        )
        runtime = await _build_runtime(provider)

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_telegram_event("cyrene please help", chat_type="group"),
                provider_id="provider-1",
                model="fake-model",
                message_trigger_mode=BotMessageTriggerMode.KEYWORD,
                message_trigger_keywords=["cyrene"],
            )
        )

        assert len(provider.requests) == 1
        assert result.actions[0].message is not None
        assert result.actions[0].message.content == _content("keyword pong")

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
                    "Built-in:",
                    "/start - Start the bot.",
                    "/help - Show available commands.",
                    "/ping - Check whether the bot is responsive.",
                    "/echo <text> - Echo text back.",
                    "/session - Show current session.",
                    "/session current - Show current session.",
                    "/session status <name> - Show session status.",
                    "/session ls - List sessions.",
                    "/session new <name> - Create and select a session.",
                    "/session use <name> - Select a session.",
                    "/session rename <old> <new> - Rename a session.",
                    "/session clear <name> - Clear session context.",
                    "/session delete <name> - Delete a session.",
                    "/reset [session] - Reset current session context.",
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


def test_bot_orchestrator_runs_status_command_for_whitelisted_user() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
            )
        )
        runtime = await _build_runtime(
            provider,
            bot_admin_config=BotAdminConfig(user_ids=["user-1"]),
        )

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
        assert result.metadata["is_admin"] is True

    asyncio.run(run())


def test_bot_orchestrator_rejects_status_command_for_non_whitelisted_user() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
            )
        )
        runtime = await _build_runtime(
            provider,
            bot_admin_config=BotAdminConfig(user_ids=["another-user"]),
        )

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
        assert "is_admin" not in result.metadata

    asyncio.run(run())


def test_bot_orchestrator_returns_plugin_input_error_as_command_reply() -> None:
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
                plugin_id="thirdparty.search",
                name="Search",
                description="Search plugin.",
                commands=[
                    PluginCommandDefinition(
                        name="search",
                        description="Search.",
                    )
                ],
            ),
            InputErrorPluginExecutor(),
        )

        result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("/search"),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert provider.requests == []
        assert result.actions[0].message is not None
        assert result.actions[0].message.content == _content(
            "插件命令 search 缺少参数 query；用法: /search <query>"
        )
        assert result.metadata["command"] == "search"

    asyncio.run(run())


def test_bot_orchestrator_returns_safe_reply_when_plugin_command_fails(caplog) -> None:
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
                plugin_id="thirdparty.broken",
                name="Broken",
                description="Broken plugin.",
                commands=[
                    PluginCommandDefinition(
                        name="broken",
                        description="Breaks.",
                    )
                ],
            ),
            FailingPluginExecutor(),
        )

        with caplog.at_level(
            logging.ERROR, logger="cyreneAI.application.bot.orchestrator"
        ):
            result = await BotOrchestrator(runtime).handle(
                ApplicationBotRequest(
                    event=_bot_event("/broken"),
                    provider_id="provider-1",
                    model="fake-model",
                )
            )

        assert provider.requests == []
        assert result.actions[0].message is not None
        assert result.actions[0].message.content == _content("Command /broken failed.")
        assert "Plugin command execution failed: command=broken" in caplog.text

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


def test_bot_orchestrator_runs_provider_admin_commands() -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            ChatResponse(
                provider_id="provider-1",
                message=_chat_message(MessageRole.ASSISTANT, "unused"),
            )
        )
        store = MemoryProviderConfigStore()
        await store.upsert_config(
            provider.config.model_copy(
                update={
                    "api_key": "secret-key",
                    "enabled": True,
                }
            )
        )
        await store.upsert_config(
            provider.config.model_copy(
                update={
                    "provider_id": "provider-2",
                    "enabled": False,
                }
            )
        )
        runtime = await _build_runtime(
            provider,
            bot_admin_config=BotAdminConfig(user_ids=["user-1"]),
            provider_config_store=store,
        )
        registry = ProviderRegistry()
        registry.register_provider(provider.info)
        runtime.provider_registry = registry

        list_result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("/provider ls"),
                provider_id="provider-1",
                model="fake-model",
            )
        )
        status_result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("/provider status provider-1"),
                provider_id="provider-1",
                model="fake-model",
            )
        )
        stopped_status_result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("/provider status provider-2"),
                provider_id="provider-1",
                model="fake-model",
            )
        )
        catalog_result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("/provider catalog"),
                provider_id="provider-1",
                model="fake-model",
            )
        )
        stop_result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("/provider stop provider-1"),
                provider_id="provider-1",
                model="fake-model",
            )
        )

        assert list_result.actions[0].message is not None
        assert list_result.actions[0].message.content == _content(
            "\n".join(
                [
                    "Providers:",
                    (
                        "- provider-1 type=openai_compatible status=running "
                        "enabled=true configured=true api_key=set"
                    ),
                    (
                        "- provider-2 type=openai_compatible status=stopped "
                        "enabled=false configured=true api_key=missing"
                    ),
                ]
            )
        )
        assert status_result.actions[0].message is not None
        assert status_result.actions[0].message.content == _content(
            "\n".join(
                [
                    "Provider provider-1:",
                    "status: running",
                    "type: openai_compatible",
                    "configured: true",
                    "running: true",
                    "enabled: true",
                    "api_key: set",
                    "timeout_seconds: 1",
                ]
            )
        )
        assert stopped_status_result.actions[0].message is not None
        assert stopped_status_result.actions[0].message.content == _content(
            "\n".join(
                [
                    "Provider provider-2:",
                    "status: stopped",
                    "type: openai_compatible",
                    "configured: true",
                    "running: false",
                    "enabled: false",
                    "api_key: missing",
                    "timeout_seconds: 1",
                ]
            )
        )
        assert catalog_result.actions[0].message is not None
        assert catalog_result.actions[0].message.content == _content(
            "\n".join(
                [
                    "Provider catalog:",
                    "- openai_compatible name=fake",
                ]
            )
        )
        assert stop_result.actions[0].message is not None
        assert stop_result.actions[0].message.content == _content(
            "Provider provider-1 stopped."
        )
        assert not runtime.provider_manager.exists("provider-1")
        assert (await store.get_config("provider-1")).enabled is False
        start_result = await BotOrchestrator(runtime).handle(
            ApplicationBotRequest(
                event=_bot_event("/provider start provider-1"),
                provider_id="provider-1",
                model="fake-model",
            )
        )
        assert start_result.actions[0].message is not None
        assert start_result.actions[0].message.content == _content(
            "Provider provider-1 started."
        )
        assert runtime.provider_manager.exists("provider-1")
        assert (await store.get_config("provider-1")).enabled is True

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
