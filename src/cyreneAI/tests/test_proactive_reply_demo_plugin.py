from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.application.channels.webhook_handler import ChannelWebhookHandler
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.application import (
    ApplicationChannelWebhookRequest,
    BotMessageTriggerMode,
)
from cyreneAI.core.schema.bot import (
    BotChannelDefinition,
    BotCommand,
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
    PluginCommandRequest,
    PluginEvent,
    PluginEventType,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition, ToolResult
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore
from cyreneAI.infra.adapters.channels.memory import InMemoryBotChannel
from cyreneAI.infra.adapters.channels.telegram import TelegramBotChannel
from cyreneAI.infra.adapters.plugins.filesystem import (
    FileSystemPluginAssets,
    FileSystemPluginLoader,
    FileSystemPluginStorage,
)


PROJECT_ROOT = Path(__file__).parents[3]
DEMO_PLUGIN_PATH = PROJECT_ROOT / "examples" / "plugins" / "proactive_reply_demo"


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

    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = responses
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        return self.responses[index]

    async def close(self) -> None:
        pass


class RecordingToolExecutor:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[ToolCall] = []

    async def execute(self, call: ToolCall) -> ToolResult:
        self.events.append(f"tool:{call.name}")
        self.calls.append(call)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content="tool says lunch noted",
        )


class RecordingTelegramClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.sent_messages: list[dict[str, object]] = []

    async def send_message(self, payload: dict[str, object]) -> dict[str, object]:
        self.events.append("telegram:send")
        self.sent_messages.append(payload)
        return {"ok": True, "result": payload}


async def _provider_manager(provider: FakeChatProvider) -> ProviderManager:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig) -> FakeChatProvider:
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    manager = ProviderManager(factory)
    await manager.add(provider.config)
    return manager


def _assistant_text(text: str) -> Message:
    return Message(
        role=MessageRole.ASSISTANT,
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=text,
            )
        ],
    )


def test_proactive_reply_demo_schedules_and_sends_follow_up(tmp_path) -> None:
    async def run() -> None:
        provider = FakeChatProvider(
            [
                ChatResponse(
                    provider_id="provider-1",
                    model="fake-model",
                    message=_assistant_text(
                        "刚刚你说「我去吃饭了」，我先记着。等你回来我们接着聊。"
                    ),
                    finish_reason=ChatFinishReason.STOP,
                )
            ]
        )
        channel = InMemoryBotChannel()
        channel_registry = BotChannelRegistry()
        channel_registry.register(
            BotChannelDefinition(
                channel_id="memory",
                name="Memory",
            ),
            channel,
        )
        session_manager = BotSessionManager(InMemoryBotSessionStore())
        bot_event = BotEvent(
            event_id="event-1",
            event_type=BotEventType.MESSAGE,
            channel_id="memory",
            session_id="memory:user-1",
            user_id="user-1",
            thread_id="thread-1",
            message=BotMessage(
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="我去吃饭了",
                    )
                ]
            ),
        )
        await session_manager.get_or_create(bot_event)

        plugin_assets = FileSystemPluginAssets()
        runtime = await build_cyrene_ai_runtime(
            provider_manager=await _provider_manager(provider),
            plugin_assets=plugin_assets,
            plugin_storage=FileSystemPluginStorage(tmp_path / "plugin_storage"),
            plugin_loaders=[
                FileSystemPluginLoader(
                    DEMO_PLUGIN_PATH,
                    plugin_assets=plugin_assets,
                )
            ],
            bot_channel_registry=channel_registry,
            bot_session_manager=session_manager,
            register_builtin_plugins=False,
            register_builtin_tools=False,
        )
        try:
            assert runtime.plugin_manager is not None
            plugins = runtime.plugin_manager.list_plugins()
            assert [plugin.plugin_id for plugin in plugins] == [
                "demo.proactive_reply"
            ]
            assert [command.name for command in runtime.plugin_manager.list_commands()] == [
                "proactive status"
            ]
            assert plugins[0].events[0].event_type == PluginEventType.MESSAGE
            assert plugins[0].tasks[0].name == "follow_up"

            await runtime.plugin_manager.dispatch_event(
                PluginEvent(
                    event_id="event-1",
                    event_type=PluginEventType.MESSAGE,
                    session_id="memory:user-1",
                    user_id="user-1",
                    thread_id="thread-1",
                    text="我去吃饭了",
                ),
                metadata={
                    "provider_id": "provider-1",
                    "model": "fake-model",
                    "follow_up_delay_seconds": 0.05,
                    "follow_up_cooldown_seconds": 0.2,
                },
            )

            for _ in range(20):
                if channel.actions:
                    break
                await asyncio.sleep(0.02)

            assert len(channel.actions) == 1
            action = channel.actions[0]
            assert action.channel_id == "memory"
            assert action.session_id == "memory:user-1"
            assert action.recipient_id == "user-1"
            assert action.thread_id == "thread-1"
            assert action.message is not None
            assert (
                action.message.content[0].text
                == "刚刚你说「我去吃饭了」，我先记着。等你回来我们接着聊。"
            )
            assert action.metadata["plugin_id"] == "demo.proactive_reply"
            assert action.metadata["kind"] == "proactive_follow_up"

            await runtime.plugin_manager.dispatch_event(
                PluginEvent(
                    event_id="event-2",
                    event_type=PluginEventType.MESSAGE,
                    session_id="memory:user-1",
                    user_id="user-1",
                    thread_id="thread-1",
                    text="/proactive status",
                ),
                metadata={
                    "provider_id": "provider-1",
                    "model": "fake-model",
                    "follow_up_delay_seconds": 0.05,
                    "follow_up_cooldown_seconds": 0.2,
                },
            )
            await asyncio.sleep(0.08)
            assert len(channel.actions) == 1

            await runtime.plugin_manager.dispatch_event(
                PluginEvent(
                    event_id="event-3",
                    event_type=PluginEventType.MESSAGE,
                    session_id="memory:user-1",
                    user_id="user-1",
                    thread_id="thread-1",
                    text="ok",
                ),
                metadata={
                    "provider_id": "provider-1",
                    "model": "fake-model",
                    "follow_up_delay_seconds": 0.05,
                    "follow_up_cooldown_seconds": 0.2,
                },
            )
            await asyncio.sleep(0.08)
            assert len(channel.actions) == 1

            status_result = await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/proactive status",
                        name="proactive status",
                    ),
                    event=bot_event,
                )
            )
            assert status_result.actions[0].message is not None
            assert (
                status_result.actions[0].message.content[0].text
                == "Proactive reply demo is running. Last message: 我去吃饭了"
            )
        finally:
            await runtime.close()

    asyncio.run(run())


def test_proactive_reply_demo_telegram_follow_up_calls_tool_before_send(
    tmp_path,
) -> None:
    async def run() -> None:
        events: list[str] = []
        tool_call = ToolCall(
            id="call-1",
            name="lookup_lunch_context",
            arguments="{\"topic\":\"lunch\"}",
        )
        provider = FakeChatProvider(
            [
                ChatResponse(
                    provider_id="provider-1",
                    model="fake-model",
                    message=Message(
                        role=MessageRole.ASSISTANT,
                        tool_calls=[tool_call],
                    ),
                    tool_calls=[tool_call],
                    finish_reason=ChatFinishReason.TOOL_CALLS,
                ),
                ChatResponse(
                    provider_id="provider-1",
                    model="fake-model",
                    message=_assistant_text("Tool checked: enjoy lunch."),
                    finish_reason=ChatFinishReason.STOP,
                ),
            ]
        )
        telegram_client = RecordingTelegramClient(events)
        telegram_channel = TelegramBotChannel(bot_client=telegram_client)
        channel_registry = BotChannelRegistry()
        channel_registry.register(
            BotChannelDefinition(
                channel_id="telegram",
                name="Telegram",
            ),
            telegram_channel,
        )
        tool_registry = ToolRegistry()
        tool_executor = RecordingToolExecutor(events)
        tool_registry.register(
            ToolDefinition(
                name="lookup_lunch_context",
                description="Lookup lunch context.",
            ),
            tool_executor,
        )

        plugin_assets = FileSystemPluginAssets()
        runtime = await build_cyrene_ai_runtime(
            provider_manager=await _provider_manager(provider),
            plugin_assets=plugin_assets,
            plugin_storage=FileSystemPluginStorage(tmp_path / "plugin_storage"),
            plugin_loaders=[
                FileSystemPluginLoader(
                    DEMO_PLUGIN_PATH,
                    plugin_assets=plugin_assets,
                )
            ],
            tool_registry=tool_registry,
            bot_channel_registry=channel_registry,
            bot_session_manager=BotSessionManager(InMemoryBotSessionStore()),
            register_builtin_plugins=False,
            register_builtin_tools=False,
        )
        try:
            await ChannelWebhookHandler(runtime).handle(
                ApplicationChannelWebhookRequest(
                    channel_id="telegram",
                    payload={
                        "update_id": 1001,
                        "message": {
                            "message_id": 7,
                            "from": {"id": 42},
                            "chat": {"id": 99, "type": "private"},
                            "text": "我去吃饭了",
                        },
                    },
                    provider_id="provider-1",
                    model="fake-model",
                    message_trigger_mode=BotMessageTriggerMode.NEVER,
                    metadata={
                        "follow_up_delay_seconds": 0.05,
                        "follow_up_cooldown_seconds": 0.2,
                    },
                )
            )

            for _ in range(30):
                if telegram_client.sent_messages:
                    break
                await asyncio.sleep(0.02)

            assert events == ["tool:lookup_lunch_context", "telegram:send"]
            assert tool_executor.calls == [tool_call]
            assert len(provider.requests) == 2
            assert provider.requests[0].tools is not None
            assert [tool.name for tool in provider.requests[0].tools] == [
                "lookup_lunch_context"
            ]
            feedback_request = provider.requests[1]
            assert feedback_request.messages[-2].tool_calls == [tool_call]
            assert feedback_request.messages[-1].tool_call_id == "call-1"
            assert telegram_client.sent_messages == [
                {
                    "chat_id": "99",
                    "text": "Tool checked: enjoy lunch.",
                }
            ]
        finally:
            await runtime.close()

    asyncio.run(run())
