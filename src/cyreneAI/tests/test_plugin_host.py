from __future__ import annotations

import asyncio

import pytest

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.bot.session_manager import BotSessionManager
from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginConfigurationError,
    PluginStateError,
)
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
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
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.core.schema.plugin import (
    PluginCapability,
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginEvent,
    PluginEventResult,
    PluginEventType,
    PluginLifecycleStatus,
    PluginManifest,
    PluginPermission,
)
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition, ToolResult
from cyreneAI.infra.adapters.bot_sessions.memory import InMemoryBotSessionStore
from cyreneAI.infra.adapters.channels.memory import InMemoryBotChannel
from cyreneAI.api import CyreneBot, Depends


class _HelloExecutor:
    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        return PluginCommandResult(
            metadata={
                "command": request.command.name,
                "args": list(request.command.args),
            }
        )


class _FakeToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content="ok",
        )


class _FakeLLMProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        name="fake",
        description="Fake LLM provider.",
    )
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
    )

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        prompt = ""
        if request.messages and request.messages[-1].content:
            prompt = request.messages[-1].content[0].text or ""
        return ChatResponse(
            provider_id=request.provider_id,
            model=request.model,
            message=Message(
                role=MessageRole.ASSISTANT,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=f"llm:{prompt}",
                    )
                ]
            ),
            finish_reason=ChatFinishReason.STOP,
        )

    async def close(self) -> None:
        pass


class _FakePluginStorage:
    def __init__(self) -> None:
        self.namespaces: dict[str, _FakePluginStorageNamespace] = {}

    def namespace(self, plugin_id: str) -> "_FakePluginStorageNamespace":
        namespace = self.namespaces.get(plugin_id)
        if namespace is None:
            namespace = _FakePluginStorageNamespace()
            self.namespaces[plugin_id] = namespace
        return namespace

    async def close(self) -> None:
        pass


class _FakePluginStorageNamespace:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def get(self, key: str, default=None):
        return self.values.get(key, default)

    async def set(self, key: str, value) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def update(self, key: str, updater, default=None):
        current = self.values.get(key, default)
        updated = updater(current)
        self.values[key] = updated
        return updated


class _FakePluginAssets:
    def __init__(self) -> None:
        self.namespaces: dict[str, _FakePluginAssetsNamespace] = {}

    def namespace(self, plugin_id: str) -> "_FakePluginAssetsNamespace":
        namespace = self.namespaces.get(plugin_id)
        if namespace is None:
            namespace = _FakePluginAssetsNamespace()
            self.namespaces[plugin_id] = namespace
        return namespace

    async def close(self) -> None:
        pass


class _FakePluginAssetsNamespace:
    async def read_text(self, path: str) -> str:
        return f"text:{path}"

    async def read_bytes(self, path: str) -> bytes:
        return f"bytes:{path}".encode()

    async def exists(self, path: str) -> bool:
        return path == "prompts/hello.txt"

    async def list(self, path: str = "") -> list[str]:
        return [path or "prompts"]


class _FakePluginLoader:
    def __init__(self, *modules: object) -> None:
        self._modules = list(modules)

    def load(self) -> list[object]:
        return self._modules


async def _build_memory_plugin_runtime(plugin: object):
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
    runtime = await build_cyrene_ai_runtime(
        plugin_loaders=[_FakePluginLoader(plugin)],
        bot_channel_registry=channel_registry,
        bot_session_manager=session_manager,
        register_builtin_plugins=False,
    )
    event = BotEvent(
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
                    text="hello",
                )
            ]
        ),
    )
    await session_manager.get_or_create(event)
    return runtime, channel


class _HelloPlugin:
    manifest = PluginManifest(
        plugin_id="thirdparty.hello",
        name="Hello",
        description="Third-party hello plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND],
        commands=[
            PluginCommandDefinition(
                name="hello",
                description="Say hello.",
                aliases=["hi"],
            )
        ],
    )

    def __init__(self) -> None:
        self.runtime_context = None

    def setup(self, context) -> None:
        self.runtime_context = context.runtime
        context.register_command(
            PluginCommandDefinition(
                name="hello",
                description="Say hello.",
                aliases=["hi"],
            ),
            _HelloExecutor(),
        )


def test_plugin_host_loads_third_party_command_from_loader() -> None:
    async def run() -> None:
        plugin = _HelloPlugin()
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            assert runtime.plugin_host is not None
            assert [item.plugin_id for item in runtime.plugin_manager.list_plugins()] == [
                "thirdparty.hello"
            ]
            assert [item.name for item in runtime.plugin_manager.list_commands()] == [
                "hello"
            ]

            result = await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/hi world",
                        name="hi",
                        args=("world",),
                        args_text="world",
                    )
                )
            )

            assert result.metadata == {
                "command": "hi",
                "args": ["world"],
            }
            assert plugin.runtime_context is not None
            assert not hasattr(plugin.runtime_context, "provider_manager")
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_requires_declared_permission() -> None:
    async def run() -> None:
        plugin = _HelloPlugin()
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            register_builtin_plugins=False,
        )
        try:
            assert plugin.runtime_context is not None
            with pytest.raises(PluginAuthorizationError):
                plugin.runtime_context.list_providers()
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_allows_declared_permission() -> None:
    class ProviderReadPlugin(_HelloPlugin):
        manifest = _HelloPlugin.manifest.model_copy(
            update={
                "plugin_id": "thirdparty.providers",
                "permissions": [PluginPermission.PROVIDER_READ],
            }
        )

    async def run() -> None:
        plugin = ProviderReadPlugin()
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            register_builtin_plugins=False,
        )
        try:
            assert plugin.runtime_context is not None
            assert plugin.runtime_context.list_providers() == []
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_injects_llm_dependency_with_bot_defaults() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.llm",
        name="LLM",
        description="LLM plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND],
        permissions=[PluginPermission.LLM],
    )
    plugin = CyreneBot(manifest)

    @plugin.command("/ask")
    async def ask(request, llm=Depends("llm")):
        return await llm.chat(request.command.args_text or "hello")

    async def run() -> None:
        provider = _FakeLLMProvider()
        factory = ProviderFactory()

        async def build_provider(config: ProviderConfig) -> _FakeLLMProvider:
            return provider

        factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
        provider_manager = ProviderManager(factory)
        await provider_manager.add(provider.config)
        runtime = await build_cyrene_ai_runtime(
            provider_manager=provider_manager,
            plugin_loaders=[_FakePluginLoader(plugin)],
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            result = await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/ask ping",
                        name="ask",
                        args=("ping",),
                        args_text="ping",
                    ),
                    event=BotEvent(
                        event_id="event-1",
                        event_type=BotEventType.COMMAND,
                        channel_id="memory",
                        session_id="memory:user-1",
                        user_id="user-1",
                    ),
                    metadata={
                        "provider_id": "provider-1",
                        "model": "chat-model",
                    },
                )
            )

            assert result.actions[0].message is not None
            assert result.actions[0].message.content[0].text == "llm:ping"
            assert provider.requests[0].provider_id == "provider-1"
            assert provider.requests[0].model == "chat-model"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_requires_llm_permission() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.llm",
        name="LLM",
        description="LLM plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND],
    )
    plugin = CyreneBot(manifest)

    @plugin.command("/ask")
    async def ask(request, llm=Depends("llm")):
        return await llm.chat("hello")

    async def run() -> None:
        with pytest.raises(PluginAuthorizationError):
            await build_cyrene_ai_runtime(
                plugin_loaders=[_FakePluginLoader(plugin)],
                register_builtin_plugins=False,
            )

    asyncio.run(run())


def test_plugin_runtime_context_injects_storage_dependency() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.storage",
        name="Storage",
        description="Storage plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND],
        permissions=[PluginPermission.STORAGE],
    )
    plugin = CyreneBot(manifest)

    @plugin.command("/count")
    async def count(request, store=Depends("storage")):
        updated = await store.update(
            "state",
            lambda current: {"count": current["count"] + 1},
            default={"count": 0},
        )
        return PluginCommandResult(metadata=updated)

    async def run() -> None:
        storage = _FakePluginStorage()
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            plugin_storage=storage,
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            result = await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(raw_text="/count", name="count")
                )
            )

            assert result.metadata == {"count": 1}
            assert await storage.namespace("thirdparty.storage").get("state") == {
                "count": 1
            }
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_requires_configured_storage() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.storage",
        name="Storage",
        description="Storage plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND],
        permissions=[PluginPermission.STORAGE],
    )
    plugin = CyreneBot(manifest)

    @plugin.command("/count")
    async def count(request, store=Depends("storage")):
        return PluginCommandResult(metadata={"store": store})

    async def run() -> None:
        with pytest.raises(PluginStateError):
            await build_cyrene_ai_runtime(
                plugin_loaders=[_FakePluginLoader(plugin)],
                register_builtin_plugins=False,
            )

    asyncio.run(run())


def test_plugin_runtime_context_injects_assets_dependency() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.assets",
        name="Assets",
        description="Assets plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND],
        permissions=[PluginPermission.ASSETS],
    )
    plugin = CyreneBot(manifest)

    @plugin.command("/asset")
    async def asset(request, assets=Depends("assets")):
        content = await assets.read_text("prompts/hello.txt")
        return PluginCommandResult(metadata={"content": content})

    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            plugin_assets=_FakePluginAssets(),
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            result = await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(raw_text="/asset", name="asset")
                )
            )

            assert result.metadata == {"content": "text:prompts/hello.txt"}
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_schedules_one_shot_task() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.tasks",
        name="Tasks",
        description="Tasks plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND, PluginCapability.TASK],
        permissions=[PluginPermission.TASK],
    )
    plugin = CyreneBot(manifest)
    called = asyncio.Event()
    payloads = []

    @plugin.task("conversation_end")
    async def conversation_end(request):
        payloads.append(request.payload)
        called.set()

    @plugin.command("/schedule")
    async def schedule(request, tasks=Depends("tasks")):
        task_id = await tasks.schedule_once(
            "conversation_end",
            delay_seconds=0.01,
            payload={"user_id": "user-1"},
            key="user-1",
        )
        return PluginCommandResult(metadata={"task_id": task_id})

    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            result = await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(raw_text="/schedule", name="schedule")
                )
            )

            assert result.metadata["task_id"].startswith(
                "thirdparty.tasks:conversation_end:"
            )
            await asyncio.wait_for(called.wait(), timeout=1)
            assert payloads == [{"user_id": "user-1"}]
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_declared_interval_task_runs_on_start() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.interval",
        name="Interval",
        description="Interval plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.TASK],
    )
    plugin = CyreneBot(manifest)
    called = asyncio.Event()

    @plugin.task("tick", interval_seconds=60, run_on_start=True)
    async def tick(request):
        called.set()

    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            register_builtin_plugins=False,
        )
        try:
            await asyncio.wait_for(called.wait(), timeout=1)
            assert runtime.plugin_manager is not None
            definition = runtime.plugin_manager.list_plugins()[0]
            assert definition.tasks[0].name == "tick"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_requires_task_permission() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.tasks",
        name="Tasks",
        description="Tasks plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND],
    )
    plugin = CyreneBot(manifest)

    @plugin.command("/schedule")
    async def schedule(request, tasks=Depends("tasks")):
        return PluginCommandResult(metadata={"tasks": tasks})

    async def run() -> None:
        with pytest.raises(PluginAuthorizationError):
            await build_cyrene_ai_runtime(
                plugin_loaders=[_FakePluginLoader(plugin)],
                register_builtin_plugins=False,
            )

    asyncio.run(run())


def test_plugin_host_registers_event_router() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.event",
        name="Event",
        description="Event plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.EVENT],
    )
    plugin = CyreneBot(manifest)
    seen = []

    @plugin.event("message")
    async def on_message(event):
        seen.append((event.session_id, event.text))
        return PluginEventResult(metadata={"handled": True})

    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            definition = runtime.plugin_manager.list_plugins()[0]
            assert definition.events[0].event_type == PluginEventType.MESSAGE

            results = await runtime.plugin_manager.dispatch_event(
                PluginEvent(
                    event_id="event-1",
                    event_type=PluginEventType.MESSAGE,
                    session_id="session-1",
                    text="hello",
                )
            )

            assert seen == [("session-1", "hello")]
            assert results[0].metadata == {"handled": True}
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_host_requires_event_capability() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.event",
        name="Event",
        description="Event plugin.",
        entrypoint="plugin.py",
        capabilities=[],
    )
    plugin = CyreneBot(manifest)

    @plugin.event("message")
    async def on_message(event):
        return None

    async def run() -> None:
        with pytest.raises(PluginConfigurationError):
            await build_cyrene_ai_runtime(
                plugin_loaders=[_FakePluginLoader(plugin)],
                register_builtin_plugins=False,
            )

    asyncio.run(run())


def test_plugin_runtime_context_injects_messages_dependency() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.messages",
        name="Messages",
        description="Messages plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.EVENT],
        permissions=[PluginPermission.MESSAGE_SEND],
    )
    plugin = CyreneBot(manifest)

    @plugin.event("message")
    async def on_message(event, messages=Depends("messages")):
        receipt = await messages.send(
            event.session_id,
            text=f"seen: {event.text}",
            metadata={"kind": "event"},
        )
        return PluginEventResult(metadata={"receipt_session": receipt.session_id})

    async def run() -> None:
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
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            bot_channel_registry=channel_registry,
            bot_session_manager=session_manager,
            register_builtin_plugins=False,
        )
        try:
            event = BotEvent(
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
                            text="hello",
                        )
                    ]
                ),
            )
            await session_manager.get_or_create(event)
            assert runtime.plugin_manager is not None

            results = await runtime.plugin_manager.dispatch_event(
                PluginEvent(
                    event_id="event-1",
                    event_type=PluginEventType.MESSAGE,
                    session_id="memory:user-1",
                    user_id="user-1",
                    thread_id="thread-1",
                    text="hello",
                )
            )

            assert results[0].metadata == {"receipt_session": "memory:user-1"}
            assert len(channel.actions) == 1
            action = channel.actions[0]
            assert action.channel_id == "memory"
            assert action.session_id == "memory:user-1"
            assert action.recipient_id == "user-1"
            assert action.thread_id == "thread-1"
            assert action.message is not None
            assert action.message.content[0].text == "seen: hello"
            assert action.metadata["plugin_id"] == "thirdparty.messages"
            assert action.metadata["kind"] == "event"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_outbox_bypass_request_still_requires_unlimited_permission() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.messages",
        name="Messages",
        description="Messages plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.EVENT],
        permissions=[PluginPermission.MESSAGE_SEND],
    )
    plugin = CyreneBot(manifest)

    @plugin.event("message")
    async def on_message(event, messages=Depends("messages")):
        receipt = await messages.send(
            event.session_id,
            text=f"seen: {event.text}",
            bypass_rate_limit=True,
        )
        return PluginEventResult(
            metadata={
                "accepted": receipt.accepted,
                "reason": receipt.metadata.get("reason"),
                "bypassed": receipt.metadata.get("rate_limit_bypassed", False),
            }
        )

    async def run() -> None:
        runtime, channel = await _build_memory_plugin_runtime(plugin)
        try:
            assert runtime.plugin_manager is not None
            event = PluginEvent(
                event_id="event-1",
                event_type=PluginEventType.MESSAGE,
                session_id="memory:user-1",
                text="hello",
            )

            first = await runtime.plugin_manager.dispatch_event(event)
            second = await runtime.plugin_manager.dispatch_event(
                event.model_copy(update={"event_id": "event-2"})
            )

            assert first[0].metadata == {
                "accepted": True,
                "reason": None,
                "bypassed": False,
            }
            assert second[0].metadata == {
                "accepted": False,
                "reason": "min_interval",
                "bypassed": False,
            }
            assert len(channel.actions) == 1
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_outbox_bypass_permission_allows_explicit_unlimited_send() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.messages",
        name="Messages",
        description="Messages plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.EVENT],
        permissions=[
            PluginPermission.MESSAGE_SEND,
            PluginPermission.MESSAGE_SEND_UNLIMITED,
        ],
    )
    plugin = CyreneBot(manifest)

    @plugin.event("message")
    async def on_message(event, messages=Depends("messages")):
        receipt = await messages.send(
            event.session_id,
            text=f"seen: {event.text}",
            bypass_rate_limit=True,
        )
        return PluginEventResult(
            metadata={
                "accepted": receipt.accepted,
                "bypassed": receipt.metadata.get("rate_limit_bypassed", False),
            }
        )

    async def run() -> None:
        runtime, channel = await _build_memory_plugin_runtime(plugin)
        try:
            assert runtime.plugin_manager is not None
            event = PluginEvent(
                event_id="event-1",
                event_type=PluginEventType.MESSAGE,
                session_id="memory:user-1",
                text="hello",
            )

            first = await runtime.plugin_manager.dispatch_event(event)
            second = await runtime.plugin_manager.dispatch_event(
                event.model_copy(update={"event_id": "event-2"})
            )

            assert first[0].metadata == {
                "accepted": True,
                "bypassed": True,
            }
            assert second[0].metadata == {
                "accepted": True,
                "bypassed": True,
            }
            assert len(channel.actions) == 2
            assert channel.actions[0].metadata["rate_limit_bypassed"] is True
            assert channel.actions[1].metadata["rate_limit_bypassed"] is True
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_requires_message_send_permission() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.messages",
        name="Messages",
        description="Messages plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.EVENT],
    )
    plugin = CyreneBot(manifest)

    @plugin.event("message")
    async def on_message(event, messages=Depends("messages")):
        return PluginEventResult(metadata={"messages": messages})

    async def run() -> None:
        with pytest.raises(PluginAuthorizationError):
            await build_cyrene_ai_runtime(
                plugin_loaders=[_FakePluginLoader(plugin)],
                register_builtin_plugins=False,
            )

    asyncio.run(run())


def test_plugin_task_can_send_via_outbox_dependency() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.task_messages",
        name="Task Messages",
        description="Task messages plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.TASK],
        permissions=[PluginPermission.MESSAGE_SEND],
    )
    plugin = CyreneBot(manifest)
    sent = asyncio.Event()

    @plugin.task("wake")
    async def wake(request, outbox=Depends("outbox")):
        await outbox.send(request.payload["session_id"], text="wake up")
        sent.set()

    async def run() -> None:
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
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            bot_channel_registry=channel_registry,
            bot_session_manager=session_manager,
            register_builtin_plugins=False,
        )
        try:
            event = BotEvent(
                event_id="event-1",
                event_type=BotEventType.MESSAGE,
                channel_id="memory",
                session_id="memory:user-1",
                user_id="user-1",
            )
            await session_manager.get_or_create(event)
            assert runtime.plugin_task_scheduler is not None

            await runtime.plugin_task_scheduler.namespace(
                "thirdparty.task_messages"
            ).schedule_once(
                "wake",
                delay_seconds=0.01,
                payload={"session_id": "memory:user-1"},
            )

            await asyncio.wait_for(sent.wait(), timeout=1)
            assert len(channel.actions) == 1
            assert channel.actions[0].message is not None
            assert channel.actions[0].message.content[0].text == "wake up"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_runtime_context_requires_configured_assets() -> None:
    manifest = PluginManifest(
        plugin_id="thirdparty.assets",
        name="Assets",
        description="Assets plugin.",
        entrypoint="plugin.py",
        capabilities=[PluginCapability.BOT_COMMAND],
        permissions=[PluginPermission.ASSETS],
    )
    plugin = CyreneBot(manifest)

    @plugin.command("/asset")
    async def asset(request, assets=Depends("assets")):
        return PluginCommandResult(metadata={"assets": assets})

    async def run() -> None:
        with pytest.raises(PluginStateError):
            await build_cyrene_ai_runtime(
                plugin_loaders=[_FakePluginLoader(plugin)],
                register_builtin_plugins=False,
            )

    asyncio.run(run())


def test_plugin_setup_context_requires_tool_permission() -> None:
    class ToolPlugin:
        manifest = PluginManifest(
            plugin_id="thirdparty.tool",
            name="Tool",
            description="Tool plugin.",
            entrypoint="plugin.py",
            capabilities=[PluginCapability.TOOL],
        )

        def setup(self, context) -> None:
            context.register_tool(
                ToolDefinition(name="lookup", description="Lookup value."),
                _FakeToolExecutor(),
            )

    async def run() -> None:
        with pytest.raises(PluginAuthorizationError):
            await build_cyrene_ai_runtime(
                plugin_loaders=[_FakePluginLoader(ToolPlugin())],
                register_builtin_plugins=False,
            )

    asyncio.run(run())


def test_plugin_host_wraps_loader_errors() -> None:
    class BrokenLoader:
        def load(self) -> list[object]:
            raise RuntimeError("boom")

    async def run() -> None:
        with pytest.raises(PluginConfigurationError) as caught:
            await build_cyrene_ai_runtime(
                plugin_loaders=[BrokenLoader()],
                register_builtin_plugins=False,
            )

        assert isinstance(caught.value.cause, RuntimeError)

    asyncio.run(run())


def test_plugin_host_rejects_manifest_command_without_executor() -> None:
    class MissingExecutorPlugin:
        manifest = PluginManifest(
            plugin_id="thirdparty.missing_executor",
            name="Missing Executor",
            description="Broken plugin.",
            entrypoint="plugin.py",
            capabilities=[PluginCapability.BOT_COMMAND],
            commands=[
                PluginCommandDefinition(
                    name="broken",
                    description="Broken command.",
                )
            ],
        )

        def setup(self, context) -> None:
            return None

    async def run() -> None:
        with pytest.raises(PluginConfigurationError):
            await build_cyrene_ai_runtime(
                plugin_loaders=[_FakePluginLoader(MissingExecutorPlugin())],
                register_builtin_plugins=False,
            )

    asyncio.run(run())


def test_plugin_host_can_disable_plugin_by_config() -> None:
    async def run() -> None:
        plugin = _HelloPlugin()
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(plugin)],
            disabled_plugin_ids=["thirdparty.hello"],
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            plugins = runtime.plugin_manager.list_plugins()
            statuses = runtime.plugin_manager.list_statuses()

            assert plugins[0].enabled is False
            assert runtime.plugin_manager.list_commands() == []
            assert statuses[0].plugin_id == "thirdparty.hello"
            assert statuses[0].status == PluginLifecycleStatus.DISABLED
            assert statuses[0].reason == "disabled_by_config"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_plugin_host_can_record_setup_failure_without_fail_fast() -> None:
    class BrokenPlugin:
        manifest = PluginManifest(
            plugin_id="thirdparty.broken",
            name="Broken",
            description="Broken plugin.",
            entrypoint="plugin.py",
            capabilities=[PluginCapability.BOT_COMMAND],
        )

        def setup(self, context) -> None:
            raise RuntimeError("boom")

    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[_FakePluginLoader(BrokenPlugin())],
            plugin_fail_fast=False,
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            assert runtime.plugin_manager.list_plugins() == []
            statuses = runtime.plugin_manager.list_statuses()
            assert statuses[0].plugin_id == "thirdparty.broken"
            assert statuses[0].status == PluginLifecycleStatus.FAILED
            assert statuses[0].reason == "setup_failed"
            assert statuses[0].error == "boom"
        finally:
            await runtime.close()

    asyncio.run(run())
