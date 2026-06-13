from __future__ import annotations

import asyncio
from typing import Annotated

import pytest

from cyreneAI.api import (
    Arg,
    Choice,
    CyreneBot,
    CyreneRouter,
    Depends,
    Flag,
    Option,
    Rest,
    text,
)
from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginConfigurationError,
    PluginExecutionError,
    PluginInputError,
)
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import (
    PluginCapability,
    PluginCommandRequest,
    PluginCommandResult,
    PluginEventRequest,
    PluginEventResult,
    PluginEventType,
    PluginManifest,
    PluginMiddlewareType,
    PluginPermission,
    PluginTaskRequest,
    PluginTaskResult,
)
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition


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


def test_cyrene_bot_command_decorator_can_infer_path_from_function_name() -> None:
    plugin = CyreneBot()

    @plugin.command
    async def hello_world(name="Cyrene"):
        """Say hello."""
        return f"Hello, {name}!"

    routes = plugin.routes

    assert len(routes) == 1
    assert routes[0].name == "hello world"
    assert routes[0].description == "Say hello."
    assert routes[0].usage == "/hello world [name=Cyrene]"


def test_cyrene_bot_command_decorator_can_infer_path_with_parentheses() -> None:
    plugin = CyreneBot()

    @plugin.command()
    async def repeat(word, count=1):
        return " ".join([word] * count)

    route = plugin.routes[0]

    assert route.name == "repeat"
    assert route.usage == "/repeat <word> [count:int=1]"


def test_cyrene_bot_tool_decorator_registers_tool_executor() -> None:
    plugin = CyreneBot(
        PluginManifest(
            plugin_id="demo.tools",
            name="Tools",
            description="Tool plugin.",
            entrypoint="main.py",
            capabilities=[PluginCapability.TOOL],
            permissions=[PluginPermission.TOOL],
        )
    )

    @plugin.tool("lookup")
    async def lookup(key: str):
        """Lookup a value."""
        return {"value": key}

    class FakeRuntime:
        def require_permission(self, permission):
            assert permission == PluginPermission.TOOL

    class FakeSetupContext:
        manifest = plugin.manifest
        runtime = FakeRuntime()

        def __init__(self) -> None:
            self.tools: list[tuple[ToolDefinition, object]] = []

        def register_tool(self, definition, executor):
            self.tools.append((definition, executor))

    context = FakeSetupContext()
    plugin.setup(context)

    definition, executor = context.tools[0]
    assert definition.name == "lookup"
    assert definition.description == "Lookup a value."
    assert definition.parameters_schema == {
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "additionalProperties": False,
        "required": ["key"],
    }

    result = asyncio.run(
        executor.execute(
            ToolCall(
                id="call-1",
                name="lookup",
                arguments='{"key":"answer"}',
            )
        )
    )
    assert result.content == '{"value": "answer"}'


def test_cyrene_bot_command_decorator_records_argument_schema_and_usage() -> None:
    plugin = CyreneBot()

    @plugin.command("/repeat")
    async def repeat(word, count=1, excited: bool = False):
        return " ".join([word] * count) + ("!" if excited else ".")

    route = plugin.routes[0]

    assert route.usage == "/repeat <word> [count:int=1] [excited:bool=false]"
    assert [argument.model_dump(exclude_none=True) for argument in route.arguments] == [
        {
            "name": "word",
            "type": "str",
            "kind": "positional",
            "required": True,
            "aliases": [],
            "choices": [],
            "description": "",
        },
        {
            "name": "count",
            "type": "int",
            "kind": "positional",
            "required": False,
            "default": 1,
            "aliases": [],
            "choices": [],
            "description": "",
        },
        {
            "name": "excited",
            "type": "bool",
            "kind": "positional",
            "required": False,
            "default": False,
            "aliases": [],
            "choices": [],
            "description": "",
        },
    ]


def test_cyrene_bot_command_decorator_preserves_explicit_usage() -> None:
    plugin = CyreneBot()

    @plugin.command("/repeat", usage="/repeat <word> [times]")
    async def repeat(word, count=1):
        return " ".join([word] * count)

    route = plugin.routes[0]

    assert route.usage == "/repeat <word> [times]"
    assert route.arguments[0].name == "word"


def test_cyrene_bot_command_decorator_records_rest_argument_schema() -> None:
    plugin = CyreneBot()

    @plugin.command("/say")
    async def say(message: Rest[str]):
        return message

    route = plugin.routes[0]

    assert route.usage == "/say <message...>"
    assert [argument.model_dump(exclude_none=True) for argument in route.arguments] == [
        {
            "name": "message",
            "type": "str",
            "kind": "rest",
            "required": True,
            "aliases": [],
            "choices": [],
            "description": "",
        }
    ]


def test_cyrene_bot_command_decorator_records_option_and_flag_schema() -> None:
    plugin = CyreneBot()

    @plugin.command("/search")
    async def search(
        query: Rest[str],
        limit: Annotated[Option[int], Arg(aliases=["-l"], description="Max rows")] = 10,
        verbose: Flag = False,
    ):
        return query

    route = plugin.routes[0]

    assert route.usage == "/search <query...> [--limit|-l:int=10] [--verbose]"
    assert [argument.model_dump(exclude_none=True) for argument in route.arguments] == [
        {
            "name": "query",
            "type": "str",
            "kind": "rest",
            "required": True,
            "aliases": [],
            "choices": [],
            "description": "",
        },
        {
            "name": "limit",
            "type": "int",
            "kind": "option",
            "required": False,
            "default": 10,
            "aliases": ["-l"],
            "choices": [],
            "description": "Max rows",
        },
        {
            "name": "verbose",
            "type": "bool",
            "kind": "flag",
            "required": False,
            "default": False,
            "aliases": [],
            "choices": [],
            "description": "",
        },
    ]


def test_cyrene_bot_command_decorator_records_choice_schema_and_alias() -> None:
    plugin = CyreneBot()

    @plugin.command("/run")
    async def run(
        mode: Annotated[Choice["fast", "safe"], Arg(alias="-m")] = "safe",  # noqa: F821
    ):
        return mode

    route = plugin.routes[0]

    assert route.usage == "/run [mode:fast|safe=safe]"
    assert route.arguments[0].model_dump(exclude_none=True) == {
        "name": "mode",
        "type": "str",
        "kind": "positional",
        "required": False,
        "default": "safe",
        "aliases": ["-m"],
        "choices": ["fast", "safe"],
        "description": "",
    }


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


def test_cyrene_bot_task_decorator_can_infer_name_from_function_name() -> None:
    plugin = CyreneBot()

    @plugin.task
    async def daily_greeting(request):
        """Generate greetings."""
        return PluginTaskResult(metadata={"task": request.task.name})

    tasks = plugin.tasks

    assert len(tasks) == 1
    assert tasks[0].name == "daily greeting"
    assert tasks[0].description == "Generate greetings."


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


def test_cyrene_bot_event_decorator_can_infer_type_from_function_name() -> None:
    plugin = CyreneBot()

    @plugin.event
    async def on_message(event):
        """Observe messages."""
        return PluginEventResult(metadata={"text": event.text})

    events = plugin.events

    assert len(events) == 1
    assert events[0].event_type == PluginEventType.MESSAGE
    assert events[0].description == "Observe messages."


def test_cyrene_bot_middleware_decorator_records_llm_middleware() -> None:
    plugin = CyreneBot()

    @plugin.middleware("llm")
    async def audit(request, next):
        """Trace LLM calls."""
        return await next(request)

    middlewares = plugin.middlewares

    assert len(middlewares) == 1
    assert middlewares[0].middleware_type == PluginMiddlewareType.LLM
    assert middlewares[0].description == "Trace LLM calls."


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


def test_cyrene_router_prefix_rewrites_usage_with_arguments() -> None:
    plugin = CyreneBot()
    router = CyreneRouter(prefix="/tools")

    @router.command("/repeat")
    async def repeat(word, count=1):
        return " ".join([word] * count)

    plugin.include_router(router)

    assert plugin.routes[0].usage == "/tools repeat <word> [count:int=1]"


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


def test_cyrene_bot_command_executor_binds_typed_command_arguments() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.typed_args",
                name="Typed Args",
                description="Typed args plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/add")
        async def add(a: int, b: int, verbose: bool = False):
            if verbose:
                return f"{a} + {b} = {a + b}"
            return str(a + b)

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

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/add 2 3 true",
                    name="add",
                    args=("2", "3", "true"),
                    args_text="2 3 true",
                ),
                event=_event("/add 2 3 true"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "2 + 3 = 5"

    asyncio.run(run())


def test_cyrene_bot_command_executor_uses_defaults_for_typed_arguments() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.typed_defaults",
                name="Typed Defaults",
                description="Typed defaults plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/hello")
        async def hello(name: str = "world"):
            return f"Hello, {name}!"

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

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(raw_text="/hello", name="hello"),
                event=_event("/hello"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "Hello, world!"

    asyncio.run(run())


def test_cyrene_bot_command_executor_infers_argument_types_from_defaults() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.default_inferred_args",
                name="Default Inferred Args",
                description="Default inferred args plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/repeat")
        async def repeat(word="hi", count=1, excited=False):
            suffix = "!" if excited else "."
            return " ".join([word] * count) + suffix

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

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/repeat hey 2 true",
                    name="repeat",
                    args=("hey", "2", "true"),
                    args_text="hey 2 true",
                ),
                event=_event("/repeat hey 2 true"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "hey hey!"

    asyncio.run(run())


def test_cyrene_bot_command_executor_defaults_untyped_object_defaults_to_str() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.untyped_default",
                name="Untyped Default",
                description="Untyped default plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/tag")
        async def tag(value=None):
            return f"tag:{value}"

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

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/tag alpha",
                    name="tag",
                    args=("alpha",),
                    args_text="alpha",
                ),
                event=_event("/tag alpha"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "tag:alpha"

    asyncio.run(run())


def test_cyrene_bot_command_executor_rejects_bad_typed_argument() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.bad_typed_arg",
                name="Bad Typed Arg",
                description="Bad typed arg plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/add")
        async def add(a: int, b: int):
            return str(a + b)

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

        context = Context()
        plugin.setup(context)
        with pytest.raises(PluginInputError):
            await context.executor.execute(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/add nope 3",
                        name="add",
                        args=("nope", "3"),
                        args_text="nope 3",
                    ),
                    event=_event("/add nope 3"),
                )
            )

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_missing_argument_with_usage() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.missing_arg",
                name="Missing Arg",
                description="Missing arg plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/hello")
        async def hello(name):
            return f"Hello, {name}!"

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

        context = Context()
        plugin.setup(context)
        with pytest.raises(PluginInputError) as exc_info:
            await context.executor.execute(
                PluginCommandRequest(
                    command=BotCommand(raw_text="/hello", name="hello"),
                    event=_event("/hello"),
                )
            )

        assert "缺少参数 name" in str(exc_info.value)
        assert "用法: /hello <name>" in str(exc_info.value)

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_extra_argument_with_usage() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.extra_arg",
                name="Extra Arg",
                description="Extra arg plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/hello")
        async def hello(name):
            return f"Hello, {name}!"

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

        context = Context()
        plugin.setup(context)
        with pytest.raises(PluginInputError) as exc_info:
            await context.executor.execute(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/hello Cyrene extra",
                        name="hello",
                        args=("Cyrene", "extra"),
                        args_text="Cyrene extra",
                    ),
                    event=_event("/hello Cyrene extra"),
                )
            )

        assert "参数过多: extra" in str(exc_info.value)
        assert "用法: /hello <name>" in str(exc_info.value)

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


def test_cyrene_bot_command_executor_binds_untyped_required_arguments_as_text() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.untyped_required",
                name="Untyped Required",
                description="Untyped required plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/hello")
        async def hello(name):
            return f"Hello, {name}!"

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self):
                raise AssertionError

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/hello Cyrene",
                    name="hello",
                    args=("Cyrene",),
                    args_text="Cyrene",
                ),
                event=_event("/hello Cyrene"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "Hello, Cyrene!"

    asyncio.run(run())


def test_cyrene_bot_command_executor_binds_rest_argument() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.rest",
                name="Rest",
                description="Rest argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/say")
        async def say(message: Rest[str]):
            return message

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self):
                raise AssertionError

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/say hello world",
                    name="say",
                    args=("hello", "world"),
                    args_text="hello world",
                ),
                event=_event("/say hello world"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "hello world"

    asyncio.run(run())


def test_cyrene_bot_command_executor_binds_options_and_flags() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.options",
                name="Options",
                description="Option argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/search")
        async def search(
            query: Rest[str],
            limit: Annotated[Option[int], Arg(aliases=["-l"])] = 10,
            verbose: Flag = False,
        ):
            return f"{query}:{limit}:{verbose}"

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self):
                raise AssertionError

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/search hello world --limit 5 --verbose",
                    name="search",
                    args=("hello", "world", "--limit", "5", "--verbose"),
                    args_text="hello world --limit 5 --verbose",
                ),
                event=_event("/search hello world --limit 5 --verbose"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "hello world:5:True"

        alias_result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/search hello -l 7",
                    name="search",
                    args=("hello", "-l", "7"),
                    args_text="hello -l 7",
                ),
                event=_event("/search hello -l 7"),
            )
        )

        assert alias_result.actions[0].message is not None
        assert alias_result.actions[0].message.content[0].text == "hello:7:False"

        false_result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/search hello --verbose=false",
                    name="search",
                    args=("hello", "--verbose=false"),
                    args_text="hello --verbose=false",
                ),
                event=_event("/search hello --verbose=false"),
            )
        )

        assert false_result.actions[0].message is not None
        assert false_result.actions[0].message.content[0].text == "hello:10:False"

    asyncio.run(run())


def test_cyrene_bot_command_executor_binds_and_validates_choice_arguments() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.choice",
                name="Choice",
                description="Choice argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/run")
        async def run_mode(
            mode: Option[Choice["fast", "safe"]] = "safe",  # noqa: F821
            limit: Option[int] = 10,
        ):
            return f"{mode}:{limit}"

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self):
                raise AssertionError

        context = Context()
        plugin.setup(context)
        result = await context.executor.execute(
            PluginCommandRequest(
                command=BotCommand(
                    raw_text="/run --mode fast --limit 5",
                    name="run",
                    args=("--mode", "fast", "--limit", "5"),
                    args_text="--mode fast --limit 5",
                ),
                event=_event("/run --mode fast --limit 5"),
            )
        )

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "fast:5"

        with pytest.raises(PluginInputError) as exc_info:
            await context.executor.execute(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/run --mode risky",
                        name="run",
                        args=("--mode", "risky"),
                        args_text="--mode risky",
                    ),
                    event=_event("/run --mode risky"),
                )
            )

        assert "必须是 'fast', 'safe'" in str(exc_info.value)
        assert "用法: /run [--mode:fast|safe=safe] [--limit:int=10]" in str(
            exc_info.value
        )

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_unknown_option_with_usage() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.unknown_option",
                name="Unknown Option",
                description="Option argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/search")
        async def search(query: Rest[str], limit: Option[int] = 10):
            return query

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self):
                raise AssertionError

        context = Context()
        plugin.setup(context)

        with pytest.raises(PluginInputError) as exc_info:
            await context.executor.execute(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/search hello --limt 5",
                        name="search",
                        args=("hello", "--limt", "5"),
                        args_text="hello --limt 5",
                    ),
                    event=_event("/search hello --limt 5"),
                )
            )

        assert "未知参数 --limt" in str(exc_info.value)
        assert "用法: /search <query...> [--limit:int=10]" in str(exc_info.value)

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_missing_option_value_with_usage() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.missing_option_value",
                name="Missing Option Value",
                description="Option argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/search")
        async def search(
            query: Rest[str], limit: Option[int] = 10, verbose: Flag = False
        ):
            return query

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self):
                raise AssertionError

        context = Context()
        plugin.setup(context)

        with pytest.raises(PluginInputError) as exc_info:
            await context.executor.execute(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/search hello --limit --verbose",
                        name="search",
                        args=("hello", "--limit", "--verbose"),
                        args_text="hello --limit --verbose",
                    ),
                    event=_event("/search hello --limit --verbose"),
                )
            )

        assert "参数 limit 缺少值" in str(exc_info.value)
        assert "用法: /search <query...> [--limit:int=10] [--verbose]" in str(
            exc_info.value
        )

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_duplicate_option_with_usage() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.duplicate_option",
                name="Duplicate Option",
                description="Option argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/search")
        async def search(query: Rest[str], limit: Option[int] = 10):
            return query

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self):
                raise AssertionError

        context = Context()
        plugin.setup(context)

        with pytest.raises(PluginInputError) as exc_info:
            await context.executor.execute(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/search hello --limit 1 --limit 2",
                        name="search",
                        args=("hello", "--limit", "1", "--limit", "2"),
                        args_text="hello --limit 1 --limit 2",
                    ),
                    event=_event("/search hello --limit 1 --limit 2"),
                )
            )

        assert "参数 limit 重复" in str(exc_info.value)
        assert "用法: /search <query...> [--limit:int=10]" in str(exc_info.value)

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_missing_rest_argument_with_usage() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.rest_missing",
                name="Rest Missing",
                description="Rest argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/say")
        async def say(message: Rest[str]):
            return message

        class Context:
            runtime = object()
            manifest = plugin.manifest

            def register_command(self, definition, executor):
                self.executor = executor

            def register_task(self, definition, executor):
                raise AssertionError

            def register_tool(self, definition, executor):
                raise AssertionError

            def register_skill(self):
                raise AssertionError

        context = Context()
        plugin.setup(context)

        with pytest.raises(PluginInputError) as exc_info:
            await context.executor.execute(
                PluginCommandRequest(
                    command=BotCommand(raw_text="/say", name="say"),
                    event=_event("/say"),
                )
            )

        assert "缺少参数 message" in str(exc_info.value)
        assert "用法: /say <message...>" in str(exc_info.value)

    asyncio.run(run())


def test_cyrene_bot_command_decorator_rejects_argument_after_rest() -> None:
    plugin = CyreneBot()

    with pytest.raises(PluginConfigurationError):

        @plugin.command("/say")
        async def say(message: Rest[str], excited=False):
            return message


def _setup_command_executor(plugin: CyreneBot):
    class Context:
        runtime = object()
        manifest = plugin.manifest

        def register_command(self, definition, executor):
            self.executor = executor

        def register_task(self, definition, executor):
            raise AssertionError

        def register_tool(self, definition, executor):
            raise AssertionError

        def register_skill(self):
            raise AssertionError

    context = Context()
    plugin.setup(context)
    return context.executor


def _command_request(
    command_name: str,
    *args: str,
    raw_text: str | None = None,
) -> PluginCommandRequest:
    args_text = " ".join(args)
    return PluginCommandRequest(
        command=BotCommand(
            raw_text=raw_text or f"/{command_name}" + (f" {args_text}" if args else ""),
            name=command_name,
            args=args,
            args_text=args_text,
        ),
        event=_event(raw_text or f"/{command_name}" + (f" {args_text}" if args else "")),
    )


def test_cyrene_bot_command_executor_reports_inline_empty_option_value() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.inline_empty_option",
                name="Inline Empty Option",
                description="Option argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/search")
        async def search(query: Rest[str], limit: Option[int] = 10):
            return f"{query}:{limit}"

        executor = _setup_command_executor(plugin)

        with pytest.raises(PluginInputError) as exc_info:
            await executor.execute(_command_request("search", "hello", "--limit="))

        assert "参数 limit 缺少值" in str(exc_info.value)
        assert "用法: /search <query...> [--limit:int=10]" in str(exc_info.value)

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_trailing_option_without_value() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.trailing_option",
                name="Trailing Option",
                description="Option argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/search")
        async def search(query: Rest[str], limit: Option[int] = 10):
            return f"{query}:{limit}"

        executor = _setup_command_executor(plugin)

        with pytest.raises(PluginInputError) as exc_info:
            await executor.execute(_command_request("search", "hello", "--limit"))

        assert "参数 limit 缺少值" in str(exc_info.value)
        assert "用法: /search <query...> [--limit:int=10]" in str(exc_info.value)

    asyncio.run(run())


def test_cyrene_bot_command_executor_accepts_negative_numeric_option_values() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.negative_option_value",
                name="Negative Option Value",
                description="Option argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/scale")
        async def scale(amount: Option[float]):
            return f"{amount:.1f}"

        executor = _setup_command_executor(plugin)
        result = await executor.execute(_command_request("scale", "--amount", "-1.5"))

        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "-1.5"

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_extra_positional_arguments() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.extra_args",
                name="Extra Args",
                description="Positional argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/hello")
        async def hello(name: str):
            return f"Hello, {name}!"

        executor = _setup_command_executor(plugin)

        with pytest.raises(PluginInputError) as exc_info:
            await executor.execute(_command_request("hello", "Cyrene", "again"))

        assert "参数过多: again" in str(exc_info.value)
        assert "用法: /hello <name>" in str(exc_info.value)

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_missing_and_invalid_positionals() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.positionals",
                name="Positionals",
                description="Positional argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/repeat")
        async def repeat(word: str, count: int):
            return " ".join([word] * count)

        executor = _setup_command_executor(plugin)

        with pytest.raises(PluginInputError) as missing:
            await executor.execute(_command_request("repeat", "hi"))
        with pytest.raises(PluginInputError) as invalid:
            await executor.execute(_command_request("repeat", "hi", "many"))

        assert "缺少参数 count" in str(missing.value)
        assert "用法: /repeat <word> <count:int>" in str(missing.value)
        assert "参数 count 应为 int，收到 'many'" in str(invalid.value)
        assert "用法: /repeat <word> <count:int>" in str(invalid.value)

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_missing_required_option() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.required_option",
                name="Required Option",
                description="Option argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/search")
        async def search(query: Rest[str], limit: Option[int]):
            return f"{query}:{limit}"

        route = plugin.routes[0]
        executor = _setup_command_executor(plugin)

        assert route.usage == "/search <query...> <--limit:int>"
        with pytest.raises(PluginInputError) as exc_info:
            await executor.execute(_command_request("search", "hello"))

        assert "缺少参数 limit" in str(exc_info.value)
        assert "用法: /search <query...> <--limit:int>" in str(exc_info.value)

    asyncio.run(run())


def test_cyrene_bot_command_executor_reports_invalid_explicit_flag_value() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.invalid_flag",
                name="Invalid Flag",
                description="Flag argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/search")
        async def search(query: Rest[str], verbose: Flag = False):
            return f"{query}:{verbose}"

        executor = _setup_command_executor(plugin)

        with pytest.raises(PluginInputError) as exc_info:
            await executor.execute(_command_request("search", "hello", "--verbose=maybe"))

        assert "参数 verbose 应为 bool，收到 'maybe'" in str(exc_info.value)
        assert "用法: /search <query...> [--verbose]" in str(exc_info.value)

    asyncio.run(run())


def test_cyrene_bot_command_executor_uses_default_for_optional_rest_argument() -> None:
    async def run() -> None:
        plugin = CyreneBot(
            PluginManifest(
                plugin_id="demo.optional_rest",
                name="Optional Rest",
                description="Rest argument plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )

        @plugin.command("/say")
        async def say(message: Rest[str] = "default message"):
            return message

        executor = _setup_command_executor(plugin)
        result = await executor.execute(_command_request("say"))

        assert plugin.routes[0].usage == "/say [message...=default message]"
        assert result.actions[0].message is not None
        assert result.actions[0].message.content[0].text == "default message"

    asyncio.run(run())


def test_cyrene_bot_command_decorator_rejects_empty_choice_and_invalid_rest_marker() -> None:
    with pytest.raises(TypeError, match=r"Choice\[\.\.\.\] requires"):
        Choice[()]

    plugin = CyreneBot()
    with pytest.raises(PluginConfigurationError, match="标记类型不支持"):

        @plugin.command("/bad")
        async def bad(message: Rest[int]):
            return message


def test_cyrene_bot_command_setup_rejects_varargs_and_varkwargs() -> None:
    for handler_source, expected in [
        ("async def bad(*args):\n    return args", "*args"),
        ("async def bad(**kwargs):\n    return kwargs", "**kwargs"),
    ]:
        namespace: dict[str, object] = {}
        exec(handler_source, namespace)
        plugin = CyreneBot(
            PluginManifest(
                plugin_id=f"demo.{expected.replace('*', 'star')}",
                name="Bad Signature",
                description="Bad command plugin.",
                entrypoint="main.py",
                capabilities=["bot_command"],
            )
        )
        plugin.command("/bad")(namespace["bad"])

        with pytest.raises(PluginConfigurationError, match=r"\*args 或 \*\*kwargs"):
            _setup_command_executor(plugin)
