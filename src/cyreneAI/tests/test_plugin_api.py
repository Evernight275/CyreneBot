from __future__ import annotations

import asyncio

import pytest

from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginConfigurationError,
    PluginExecutionError,
)
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import (
    PluginCommandRequest,
    PluginCommandResult,
    PluginEventRequest,
    PluginEventResult,
    PluginEventType,
    PluginManifest,
    PluginTaskRequest,
    PluginTaskResult,
)
from cyreneAI.api import CyreneBot, CyreneRouter, Depends, text


def _event(text_value: str = "/hello") -> BotEvent:
    return BotEvent(
        event_id="event-1",
        event_type=BotEventType.COMMAND,
        channel_id="memory",
        session_id="memory:user-1",
        user_id="user-1",
        message=BotMessage(
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=text_value,
                )
            ]
        ),
    )


def test_cyrene_bot_requires_manifest_before_loader_configures_it() -> None:
    plugin = CyreneBot()

    with pytest.raises(PluginConfigurationError):
        _ = plugin.manifest

    manifest = PluginManifest(
        plugin_id="demo.hello",
        name="Hello",
        description="Hello plugin.",
        entrypoint="main.py",
    )
    plugin.configure(manifest)

    assert plugin.manifest is manifest


def test_cyrene_bot_command_decorator_records_local_route() -> None:
    plugin = CyreneBot()

    @plugin.command("/hello", aliases=["hi"], admin_required=True)
    async def hello(request, ctx):
        """Say hello."""
        return text(request, "hello")

    routes = plugin.routes

    assert len(routes) == 1
    assert routes[0].name == "hello"
    assert routes[0].description == "Say hello."
    assert routes[0].usage == "/hello"
    assert routes[0].aliases == ["hi"]
    assert routes[0].admin_required is True


def test_cyrene_bot_can_include_router_routes() -> None:
    plugin = CyreneBot()
    router = CyreneRouter(prefix="/sf", admin_required=True)

    @router.command("/ban", aliases=["b"])
    async def ban(request, ctx):
        """Ban a user."""
        return text(request, "banned")

    plugin.include_router(router)
    routes = plugin.routes

    assert len(routes) == 1
    assert routes[0].name == "sf ban"
    assert routes[0].description == "Ban a user."
    assert routes[0].usage == "/sf ban"
    assert routes[0].aliases == ["sf b"]
    assert routes[0].admin_required is True


def test_cyrene_bot_task_decorator_records_local_task() -> None:
    plugin = CyreneBot()

    @plugin.task("daily_greeting", daily_at="08:30", run_on_start=True)
    async def daily_greeting(request):
        """Generate greetings."""
        return PluginTaskResult(metadata={"task": request.task.name})

    tasks = plugin.tasks

    assert len(tasks) == 1
    assert tasks[0].name == "daily_greeting"
    assert tasks[0].description == "Generate greetings."
    assert tasks[0].daily_at == "08:30"
    assert tasks[0].run_on_start is True


def test_cyrene_bot_event_decorator_records_local_event() -> None:
    plugin = CyreneBot()

    @plugin.event("message")
    async def on_message(event):
        """Observe messages."""
        return PluginEventResult(metadata={"text": event.text})

    events = plugin.events

    assert len(events) == 1
    assert events[0].event_type == PluginEventType.MESSAGE
    assert events[0].description == "Observe messages."
    assert events[0].enabled is True


def test_cyrene_router_can_include_child_router() -> None:
    plugin = CyreneBot()
    admin_router = CyreneRouter(prefix="/admin", admin_required=True)
    users_router = CyreneRouter(prefix="/users")

    @users_router.command("/ban")
    async def ban(request, ctx):
        return text(request, "banned")

    admin_router.include_router(users_router)
    plugin.include_router(admin_router)

    assert plugin.routes[0].name == "admin users ban"
    assert plugin.routes[0].usage == "/admin users ban"
    assert plugin.routes[0].admin_required is True


def test_cyrene_router_can_include_child_router_tasks() -> None:
    plugin = CyreneBot()
    parent = CyreneRouter(prefix="/proactive")
    child = CyreneRouter(prefix="/conversation")

    @child.task("end")
    async def conversation_end(request):
        return None

    parent.include_router(child)
    plugin.include_router(parent)

    assert plugin.tasks[0].name == "proactive conversation end"


def test_cyrene_router_can_include_child_router_events() -> None:
    plugin = CyreneBot()
    parent = CyreneRouter(prefix="/proactive", metadata={"scope": "parent"})
    child = CyreneRouter(metadata={"scope": "child"})

    @child.event("message")
    async def on_message(event):
        return None

    parent.include_router(child)
    plugin.include_router(parent)

    assert plugin.events[0].event_type == PluginEventType.MESSAGE
    assert plugin.events[0].metadata == {"scope": "child"}


def test_text_helper_builds_standard_bot_action() -> None:
    result = text(
        PluginCommandRequest(
            command=BotCommand(raw_text="/hello", name="hello"),
            event=_event(),
        ),
        "Hello!",
    )

    assert len(result.actions) == 1
    action = result.actions[0]
    assert action.channel_id == "memory"
    assert action.session_id == "memory:user-1"
    assert action.recipient_id == "user-1"
    assert action.message is not None
    assert action.message.content[0].text == "Hello!"


def test_cyrene_bot_command_executor_accepts_string_reply() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.string_reply",
                name="String Reply",
                description="String reply plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/hello")
        async def hello(request, ctx):
            return "hello"

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        context = Context()
        plugin.setup(context)

        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(raw_text="/hello", name="hello"),
                event=_event("/hello"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "hello"

    asyncio.run(run())


def test_cyrene_bot_command_executor_accepts_async_yielded_string_replies() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.yield_reply",
                name="Yield Reply",
                description="Yield reply plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/hello")
        async def hello(request, ctx):
            yield "hello"
            yield "world"

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        context = Context()
        plugin.setup(context)

        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(raw_text="/hello", name="hello"),
                event=_event("/hello"),
            )
        )

        assert len(result.actions) == 2
        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "hello"
        assert result.actions[1].message is not None
        assert result.actions[1].message.content[0].text == "world"

    asyncio.run(run())


def test_cyrene_bot_command_executor_accepts_sync_yielded_results() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.sync_yield_reply",
                name="Sync Yield Reply",
                description="Sync yield reply plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/hello")
        def hello(request, ctx):
            yield text(request, "hello")
            yield PluginCommandResult(metadata={"done": True})

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        context = Context()
        plugin.setup(context)

        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(raw_text="/hello", name="hello"),
                event=_event("/hello"),
            )
        )

        assert len(result.actions) == 1
        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "hello"
        assert result.metadata == {"done": True}

    asyncio.run(run())


def test_cyrene_bot_command_executor_rejects_non_string_shortcut_result() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.bad",
                name="Bad",
                description="Bad plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/bad")
        async def bad(request, ctx):
            return {"bad": True}

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        context = Context()
        plugin.setup(context)

        with pytest.raises(PluginExecutionError):
            await context.executor.execute(
                PluginCommandRequest(
                    command=BotCommand(raw_text="/bad", name="bad"),
                    event=_event("/bad"),
                )
            )

    asyncio.run(run())


def test_cyrene_bot_task_executor_accepts_none_result() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.task",
                name="Task",
                description="Task plugin.",
                entrypoint="main.py",
                capabilities=["task"],
            )
        )
        calls = []

        @plugin.task("cleanup")
        async def cleanup(request):
            calls.append(request.task.name)

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                raise AssertionError

            def register_task(self, definition, executor):
                self.definition = definition
                self.executor = executor

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginTaskRequest(task=context.definition)
        )

        assert calls == ["cleanup"]
        assert result == PluginTaskResult()

    asyncio.run(run())


def test_cyrene_bot_event_executor_injects_narrow_event_and_dependency() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.event",
                name="Event",
                description="Event plugin.",
                entrypoint="main.py",
                capabilities=["event"],
            )
        )
        calls = []

        @plugin.event("message")
        async def on_message(event, ctx=Depends("runtime")):
            calls.append((event.text, ctx.value))

        class RuntimeContext:
            value = "runtime"

            def require_permission(self, permission):
                raise AssertionError

        class Context:
            runtime = RuntimeContext()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                raise AssertionError

            def register_task(self, definition, executor):
                raise AssertionError

            def register_event(self, definition, executor):
                self.definition = definition
                self.executor = executor

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginEventRequest(
                route=context.definition,
                event={
                    "event_id": "event-1",
                    "event_type": "message",
                    "session_id": "session-1",
                    "text": "hello",
                },
            )
        )

        assert calls == [("hello", "runtime")]
        assert result == PluginEventResult()

    asyncio.run(run())


def test_cyrene_bot_command_executor_injects_declared_dependency() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.providers",
                name="Providers",
                description="Provider plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
                permissions=["provider_read"],
            )
        )

        @plugin.command("/providers")
        async def providers(request, list_providers=Depends("providers")):
            return PluginCommandResult(
                metadata={
                    "providers": list_providers(),
                    "command": request.command.name,
                }
            )

        class RuntimeContext:
            def require_permission(self, permission):
                assert permission == "provider_read"

            def list_providers(self):
                return ["provider-1"]

        class Context:
            runtime = RuntimeContext()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(raw_text="/providers", name="providers"),
                event=_event("/providers"),
            )
        )

        assert result.metadata == {
            "providers": ["provider-1"],
            "command": "providers",
        }

    asyncio.run(run())


def test_cyrene_bot_event_executor_injects_messages_dependency() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.messages",
                name="Messages",
                description="Messages plugin.",
                entrypoint="main.py",
                capabilities=["event"],
                permissions=["message_send"],
            )
        )

        @plugin.event("message")
        async def on_message(event, messages=Depends("messages")):
            receipt = await messages.send(event.session_id, text="hello")
            return PluginEventResult(metadata={"session_id": receipt.session_id})

        class Messages:
            async def send(self, session_id, *, text, metadata=None):
                assert session_id == "session-1"
                assert text == "hello"

                class Receipt:
                    session_id = "session-1"

                return Receipt()

        class RuntimeContext:
            def require_permission(self, permission):
                assert permission == "message_send"

            @property
            def messages(self):
                return Messages()

        class Context:
            runtime = RuntimeContext()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                raise AssertionError

            def register_task(self, definition, executor):
                raise AssertionError

            def register_event(self, definition, executor):
                self.definition = definition
                self.executor = executor

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginEventRequest(
                route=context.definition,
                event={
                    "event_id": "event-1",
                    "event_type": "message",
                    "session_id": "session-1",
                    "text": "ping",
                },
            )
        )

        assert result.metadata == {"session_id": "session-1"}

    asyncio.run(run())


def test_cyrene_bot_command_executor_rejects_undeclared_dependency_permission() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.providers",
                name="Providers",
                description="Provider plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/providers")
        async def providers(request, list_providers=Depends("providers")):
            return PluginCommandResult(metadata={"providers": list_providers()})

        class RuntimeContext:
            def require_permission(self, permission):
                raise PluginAuthorizationError(f"missing {permission}")

            def list_providers(self):
                raise AssertionError

        class Context:
            runtime = RuntimeContext()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        with pytest.raises(PluginAuthorizationError):
            plugin.setup(Context())

    asyncio.run(run())


def test_cyrene_bot_command_executor_rejects_unknown_dependency() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.unknown",
                name="Unknown",
                description="Unknown dependency plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/unknown")
        async def unknown(request, dep=Depends("missing")):
            return PluginCommandResult(metadata={"dep": dep})

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        with pytest.raises(PluginConfigurationError):
            plugin.setup(Context())

    asyncio.run(run())


def test_cyrene_bot_command_executor_rejects_chat_dependency_name() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.chat",
                name="Chat",
                description="Chat dependency plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
                permissions=["llm"],
            )
        )

        @plugin.command("/chat")
        async def chat(request, chat=Depends("chat")):
            return await chat(request.command.args_text)

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self, definition):
                raise AssertionError

        with pytest.raises(PluginConfigurationError):
            plugin.setup(Context())

    asyncio.run(run())


def test_cyrene_bot_command_executor_rejects_uninjectable_required_parameter() -> None:
    plugin = CyreneBot(
        PluginManifest(
            plugin_id="demo.bad_signature",
            name="Bad Signature",
            description="Bad signature plugin.",
            entrypoint="main.py",
            capabilities=["bot_command"],
        )
    )

    @plugin.command("/bad")
    async def bad(request, ctx, extra):
        return PluginCommandResult(metadata={"extra": extra})

    class Context:
        runtime = object()
        manifest = plugin.manifest

        def register_command(self, definition, executor):
            self.executor = executor

        def register_task(self, definition, executor):
            raise AssertionError

        def register_tool(self, definition, executor):
            raise AssertionError

        def register_skill(self, definition):
            raise AssertionError

    with pytest.raises(PluginConfigurationError):
        plugin.setup(Context())
