from __future__ import annotations

import asyncio

from cyreneAI.application.plugins.builtin_bot_commands import BuiltinBotCommandExecutor
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.plugin.registry import PluginRegistry
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import PluginCommandRequest
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition, ToolResult
from cyreneAI.core.tool.registry import ToolRegistry


class FakeToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(call_id=call.id, name=call.name, content="ok")


def _runtime() -> CyreneAIRuntime:
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        FakeToolExecutor(),
    )
    return CyreneAIRuntime(
        provider_manager=ProviderManager(ProviderFactory()),
        context_builder=ContextWindowBuilder(),
        tool_registry=tool_registry,
    )


def _request(name: str, *args: str) -> PluginCommandRequest:
    return PluginCommandRequest(
        command=BotCommand(
            raw_text="/" + " ".join([name, *args]),
            name=name,
            args=tuple(args),
            args_text=" ".join(args),
        ),
        event=BotEvent(
            event_id="event-1",
            event_type=BotEventType.COMMAND,
            channel_id="memory",
            session_id="memory:user-1",
            user_id="user-1",
            message=BotMessage(
                content=[
                    ContentPart(type=ContentPartType.TEXT, text="/tool ls"),
                ]
            ),
        ),
        is_admin=True,
    )


def _result_text(result) -> str:
    action = result.actions[0]
    assert action.message is not None
    return "".join(part.text or "" for part in action.message.content)


def test_builtin_tool_commands_list_and_toggle_tools() -> None:
    runtime = _runtime()
    assert runtime.tool_registry is not None
    executor = BuiltinBotCommandExecutor(registry=PluginRegistry(), runtime=runtime)

    list_result = asyncio.run(executor.execute(_request("tool ls")))
    assert "lookup [on]" in _result_text(list_result)

    off_result = asyncio.run(executor.execute(_request("tool off", "lookup")))
    assert "disabled" in _result_text(off_result)
    assert runtime.tool_registry.is_enabled("lookup") is False

    on_result = asyncio.run(executor.execute(_request("tool on", "lookup")))
    assert "enabled" in _result_text(on_result)
    assert runtime.tool_registry.is_enabled("lookup") is True
