from __future__ import annotations

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.plugin import PluginInputError
from cyreneAI.core.plugin.plugin_protocol import PluginRegistryProtocol
from cyreneAI.core.schema.bot import (
    BotAction,
    BotActionType,
    BotMessage,
)
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import (
    PluginCapability,
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
)


BUILTIN_BOT_COMMANDS_PLUGIN_ID = "builtin.bot_commands"


def register_builtin_bot_command_plugins(
    registry: PluginRegistryProtocol,
    runtime: CyreneAIRuntime,
) -> None:
    """
    注册内置 bot 命令插件。
    """
    registry.register(
        _builtin_bot_commands_definition(),
        BuiltinBotCommandExecutor(
            registry=registry,
            runtime=runtime,
        ),
    )


class BuiltinBotCommandExecutor:
    """
    内置 bot 命令执行器。
    """

    def __init__(
        self,
        *,
        registry: PluginRegistryProtocol,
        runtime: CyreneAIRuntime,
    ) -> None:
        self._registry = registry
        self._runtime = runtime

    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        if request.event is None:
            raise PluginInputError("插件命令请求必须包含 bot event")

        command = request.command
        if command.name == "start":
            text = "\n".join(
                [
                    "CyreneAI bot is ready.",
                    "Use /help to see available commands.",
                ]
            )
        elif command.name == "help":
            text = self._render_help()
        elif command.name == "ping":
            text = "pong"
        elif command.name == "echo":
            text = command.args_text or "(empty)"
        elif command.name == "status":
            text = self._render_status()
        else:
            text = _render_unknown_command(command.name)

        return PluginCommandResult(
            actions=[
                _send_text_action(
                    request=request,
                    text=text,
                )
            ],
            metadata={
                "plugin_id": BUILTIN_BOT_COMMANDS_PLUGIN_ID,
                "command": command.name,
                "command_args": list(command.args),
            },
        )

    def _render_help(self) -> str:
        lines = ["Available commands:"]
        for command in self._registry.list_commands():
            if not command.enabled:
                continue
            usage = command.usage or f"/{command.name}"
            lines.append(f"{usage} - {command.description}")
        return "\n".join(lines)

    def _render_status(self) -> str:
        provider_count = len(self._runtime.provider_manager.list_running())
        channel_count = 0
        if self._runtime.bot_channel_registry is not None:
            channel_count = len(self._runtime.bot_channel_registry.list_definitions())

        lines = [
            "CyreneAI status:",
            f"providers: {provider_count}",
            f"bot_channels: {channel_count}",
            f"skills: {'enabled' if self._runtime.skill_manager else 'disabled'}",
            f"tools: {'enabled' if self._runtime.tool_manager else 'disabled'}",
            f"polling_state: {'enabled' if self._runtime.bot_polling_state_store else 'disabled'}",
        ]
        return "\n".join(lines)


def _builtin_bot_commands_definition() -> PluginDefinition:
    return PluginDefinition(
        plugin_id=BUILTIN_BOT_COMMANDS_PLUGIN_ID,
        name="Builtin Bot Commands",
        description="Built-in bot command plugin.",
        builtin=True,
        capabilities=[
            PluginCapability.BOT_COMMAND,
            PluginCapability.STATUS,
        ],
        commands=[
            PluginCommandDefinition(
                name="start",
                description="Start the bot.",
                usage="/start",
            ),
            PluginCommandDefinition(
                name="help",
                description="Show available commands.",
                usage="/help",
            ),
            PluginCommandDefinition(
                name="ping",
                description="Check whether the bot is responsive.",
                usage="/ping",
            ),
            PluginCommandDefinition(
                name="echo",
                description="Echo text back.",
                usage="/echo <text>",
            ),
            PluginCommandDefinition(
                name="status",
                description="Show runtime status.",
                usage="/status",
                admin_required=True,
            ),
        ],
    )


def _send_text_action(
    *,
    request: PluginCommandRequest,
    text: str,
) -> BotAction:
    if request.event is None:
        raise PluginInputError("插件命令请求必须包含 bot event")

    return BotAction(
        action_type=BotActionType.SEND_MESSAGE,
        channel_id=request.event.channel_id,
        session_id=request.event.session_id,
        recipient_id=request.event.user_id,
        thread_id=request.event.thread_id,
        message=BotMessage(
            sender_id="bot",
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=text,
                )
            ],
            metadata={
                "plugin_id": BUILTIN_BOT_COMMANDS_PLUGIN_ID,
                "command": request.command.name,
            },
        ),
        metadata={
            "bot_event_id": request.event.event_id,
            "plugin_id": BUILTIN_BOT_COMMANDS_PLUGIN_ID,
            "command": request.command.name,
            "command_args": list(request.command.args),
        },
    )


def _render_unknown_command(command_name: str) -> str:
    return "\n".join(
        [
            f"Unknown command: {command_name}",
            "Use /help to see available commands.",
        ]
    )
