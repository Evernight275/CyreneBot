from __future__ import annotations

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError, NotFoundError
from cyreneAI.core.errors.plugin import PluginInputError
from cyreneAI.core.plugin.plugin_protocol import PluginRegistryProtocol
from cyreneAI.core.schema.bot import (
    BotAction,
    BotActionType,
    BotConversationRef,
    BotEvent,
    BotMessage,
)
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import (
    PluginCommandArgumentDefinition,
    PluginCommandArgumentKind,
    PluginCapability,
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
)
from cyreneAI.core.schema.provider import ProviderConfig


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
            text = self._render_help(is_admin=request.is_admin)
        elif command.name == "ping":
            text = "pong"
        elif command.name == "echo":
            text = command.args_text or "(empty)"
        elif command.name == "session":
            text = await self._render_session_current(request)
        elif command.name == "session current":
            text = await self._render_session_current(request)
        elif command.name == "session ls":
            text = await self._render_session_list(request)
        elif command.name == "session new":
            text = await self._create_session_conversation(request)
        elif command.name == "session use":
            text = await self._use_session_conversation(request)
        elif command.name == "session rename":
            text = await self._rename_session_conversation(request)
        elif command.name == "session delete":
            text = await self._delete_session_conversation(request)
        elif command.name == "reset":
            text = await self._reset_context(request)
        elif command.name == "status":
            text = self._render_status()
        elif command.name == "tool ls":
            text = self._render_tool_list()
        elif command.name == "tool on":
            text = self._set_tool_enabled(command.args, enabled=True)
        elif command.name == "tool off":
            text = self._set_tool_enabled(command.args, enabled=False)
        elif command.name == "tool off_all":
            text = self._disable_all_tools()
        elif command.name == "provider ls":
            text = self._render_provider_list()
        elif command.name == "provider catalog":
            text = self._render_provider_catalog()
        elif command.name == "provider status":
            text = await self._render_provider_status(command.args)
        elif command.name == "provider models":
            text = await self._render_provider_models(command.args)
        elif command.name == "provider start":
            text = await self._start_provider(command.args)
        elif command.name == "provider stop":
            text = await self._stop_provider(command.args)
        elif command.name == "provider reload":
            text = await self._reload_provider(command.args)
        elif command.name == "provider check":
            text = await self._check_provider(command.args)
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

    def _render_help(self, *, is_admin: bool = False) -> str:
        lines = ["Available commands:"]
        for command in self._registry.list_commands():
            if not command.enabled:
                continue
            if command.admin_required and not is_admin:
                continue
            usage = _render_command_usage(command)
            admin_suffix = " [admin]" if command.admin_required else ""
            lines.append(f"{usage} - {command.description}{admin_suffix}")
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

    def _render_tool_list(self) -> str:
        registry = self._runtime.tool_registry
        if registry is None:
            return "Tools are disabled."

        definitions = sorted(
            registry.list_definitions(),
            key=lambda definition: definition.name,
        )
        if not definitions:
            return "No tools registered."

        lines = ["Tools:"]
        for definition in definitions:
            enabled = registry.is_enabled(definition.name)
            status = "on" if enabled else "off"
            source = definition.metadata.get("source")
            source_suffix = f" source={source}" if isinstance(source, str) else ""
            risk = definition.safety_profile.risk_level.value
            lines.append(
                f"- {definition.name} [{status}] risk={risk}{source_suffix}: "
                f"{definition.description}"
            )
        return "\n".join(lines)

    def _set_tool_enabled(self, args: tuple[str, ...], *, enabled: bool) -> str:
        registry = self._runtime.tool_registry
        if registry is None:
            return "Tools are disabled."
        if not args:
            return "Usage: /tool on <name>" if enabled else "Usage: /tool off <name>"
        name = args[0]
        if not registry.exists(name):
            return f"Unknown tool: {name}"
        registry.set_enabled(name, enabled)
        status = "enabled" if enabled else "disabled"
        return f"Tool {name} {status}."

    def _disable_all_tools(self) -> str:
        registry = self._runtime.tool_registry
        if registry is None:
            return "Tools are disabled."
        count = 0
        for definition in registry.list_definitions():
            if registry.is_enabled(definition.name):
                registry.set_enabled(definition.name, False)
                count += 1
        return f"Disabled {count} tool(s)."

    async def _render_session_current(
        self,
        request: PluginCommandRequest,
    ) -> str:
        manager = self._runtime.bot_session_manager
        if manager is None:
            return "Bot sessions are disabled."
        conversation = await manager.get_active_conversation(_request_event(request))
        return _render_conversation_current(conversation)

    async def _render_session_list(
        self,
        request: PluginCommandRequest,
    ) -> str:
        manager = self._runtime.bot_session_manager
        if manager is None:
            return "Bot sessions are disabled."
        event = _request_event(request)
        active = await manager.get_active_conversation(event)
        conversations = await manager.list_conversations(event)
        lines = ["Sessions:"]
        for conversation in conversations:
            marker = "*" if conversation.conversation_id == active.conversation_id else "-"
            lines.append(f"{marker} {conversation.name}")
        return "\n".join(lines)

    async def _create_session_conversation(
        self,
        request: PluginCommandRequest,
    ) -> str:
        manager = self._runtime.bot_session_manager
        if manager is None:
            return "Bot sessions are disabled."
        name = request.command.args_text
        if not name:
            return "Usage: /session new <name>"
        try:
            conversation = await manager.create_conversation(
                _request_event(request),
                name,
            )
        except CyreneAIError as exc:
            return f"Session create failed: {exc}"
        return f"Session {conversation.name} created and selected."

    async def _use_session_conversation(
        self,
        request: PluginCommandRequest,
    ) -> str:
        manager = self._runtime.bot_session_manager
        if manager is None:
            return "Bot sessions are disabled."
        name = request.command.args_text
        if not name:
            return "Usage: /session use <name>"
        try:
            conversation = await manager.use_conversation(
                _request_event(request),
                name,
            )
        except CyreneAIError as exc:
            return f"Session switch failed: {exc}"
        return f"Session {conversation.name} selected."

    async def _rename_session_conversation(
        self,
        request: PluginCommandRequest,
    ) -> str:
        manager = self._runtime.bot_session_manager
        if manager is None:
            return "Bot sessions are disabled."
        args = request.command.args
        if len(args) < 2:
            return "Usage: /session rename <old> <new>"
        old_name = args[0]
        new_name = " ".join(args[1:])
        try:
            conversation = await manager.rename_conversation(
                _request_event(request),
                old_name,
                new_name,
            )
        except CyreneAIError as exc:
            return f"Session rename failed: {exc}"
        return f"Session renamed to {conversation.name}."

    async def _delete_session_conversation(
        self,
        request: PluginCommandRequest,
    ) -> str:
        manager = self._runtime.bot_session_manager
        if manager is None:
            return "Bot sessions are disabled."
        name = request.command.args_text
        if not name:
            return "Usage: /session delete <name>"
        try:
            conversation = await manager.delete_conversation(
                _request_event(request),
                name,
            )
        except CyreneAIError as exc:
            return f"Session delete failed: {exc}"

        deleted_count = await self._clear_context_session(
            conversation.context_session_id
        )
        suffix = (
            f" Context snapshots deleted: {deleted_count}."
            if deleted_count is not None
            else " Context manager is not configured."
        )
        return f"Session {conversation.name} deleted.{suffix}"

    async def _reset_context(self, request: PluginCommandRequest) -> str:
        try:
            conversation = await self._resolve_reset_conversation(request)
        except CyreneAIError as exc:
            return f"Session reset failed: {exc}"
        if conversation is not None:
            deleted_count = await self._clear_context_session(
                conversation.context_session_id
            )
            if deleted_count is None:
                return "Context manager is not configured."
            return (
                f"Session {conversation.name} reset. "
                f"Context snapshots deleted: {deleted_count}."
            )

        context_session_id = _metadata_string(
            request.metadata.get("context_session_id")
        ) or _request_event(request).session_id
        deleted_count = await self._clear_context_session(context_session_id)
        if deleted_count is None:
            return "Context manager is not configured."
        return f"Context reset. Context snapshots deleted: {deleted_count}."

    async def _resolve_reset_conversation(
        self,
        request: PluginCommandRequest,
    ) -> BotConversationRef | None:
        manager = self._runtime.bot_session_manager
        if manager is None:
            if request.command.args_text:
                return None
            return None
        if request.command.args_text:
            try:
                return await manager.get_conversation(
                    _request_event(request),
                    request.command.args_text,
                )
            except CyreneAIError:
                raise
        return await manager.get_active_conversation(_request_event(request))

    async def _clear_context_session(self, context_session_id: str) -> int | None:
        manager = self._runtime.context_manager
        if manager is None:
            return None
        return await manager.clear_session(context_session_id)

    def _render_provider_list(self) -> str:
        configs = {
            config.provider_id: config
            for config in self._runtime.provider_manager.list_running_configs()
        }
        if not configs:
            return "No providers running."

        lines = ["Running providers:"]
        for provider_id in sorted(configs):
            config = configs[provider_id]
            lines.append(
                f"- {provider_id} type={config.provider_type.value} "
                f"enabled={str(config.enabled).lower()}"
            )
        return "\n".join(lines)

    def _render_provider_catalog(self) -> str:
        registry = self._runtime.provider_registry
        if registry is None:
            return "Provider catalog is not configured."

        providers = sorted(
            registry.get_all(),
            key=lambda provider: provider.provider_type.value,
        )
        if not providers:
            return "No provider types registered."

        lines = ["Provider catalog:"]
        for provider in providers:
            capabilities = ",".join(
                capability.value
                for capability in (provider.capabilities or [])
            )
            suffix = f" capabilities={capabilities}" if capabilities else ""
            lines.append(
                f"- {provider.provider_type.value}: {provider.name}{suffix}"
            )
        return "\n".join(lines)

    async def _render_provider_status(self, args: tuple[str, ...]) -> str:
        if not args:
            return "Usage: /provider status <provider_id>"
        provider_id = args[0]
        saved_config = await self._saved_provider_config_or_none(provider_id)
        running = self._runtime.provider_manager.exists(provider_id)
        if saved_config is None and not running:
            return f"Unknown provider: {provider_id}"

        config = saved_config
        if config is None and running:
            config = self._runtime.provider_manager.get(provider_id).config
        assert config is not None

        lines = [
            f"Provider {provider_id}:",
            f"type: {config.provider_type.value}",
            f"configured: {str(saved_config is not None).lower()}",
            f"running: {str(running).lower()}",
            f"enabled: {str(config.enabled).lower()}",
            f"api_key: {'set' if config.api_key else 'missing'}",
        ]
        if config.base_url:
            lines.append(f"base_url: {config.base_url}")
        if config.timeout is not None:
            lines.append(f"timeout_seconds: {config.timeout.total_seconds():g}")
        return "\n".join(lines)

    async def _render_provider_models(self, args: tuple[str, ...]) -> str:
        if not args:
            return "Usage: /provider models <provider_id>"
        provider_id = args[0]
        try:
            models = await self._runtime.provider_manager.list_models(provider_id)
        except CyreneAIError as exc:
            return f"Provider models failed: {exc}"
        if not models:
            return f"No models reported for provider {provider_id}."
        lines = [f"Models for {provider_id}:"]
        lines.extend(f"- {model.model_id}" for model in models)
        return "\n".join(lines)

    async def _start_provider(self, args: tuple[str, ...]) -> str:
        if not args:
            return "Usage: /provider start <provider_id>"
        store = self._runtime.provider_config_store
        if store is None:
            return "Provider config store is not configured."
        provider_id = args[0]
        try:
            config = await store.get_config(provider_id)
            config = config.model_copy(update={"enabled": True})
            if self._runtime.provider_manager.exists(provider_id):
                await self._runtime.provider_manager.reload(config)
            else:
                await self._runtime.provider_manager.add(config)
            await store.upsert_config(config)
        except CyreneAIError as exc:
            return f"Provider start failed: {exc}"
        return f"Provider {provider_id} started."

    async def _stop_provider(self, args: tuple[str, ...]) -> str:
        if not args:
            return "Usage: /provider stop <provider_id>"
        provider_id = args[0]
        saved_config = await self._saved_provider_config_or_none(provider_id)
        if saved_config is not None and self._runtime.provider_config_store is not None:
            await self._runtime.provider_config_store.upsert_config(
                saved_config.model_copy(update={"enabled": False})
            )
        if not self._runtime.provider_manager.exists(provider_id):
            return f"Provider {provider_id} is not running."
        try:
            await self._runtime.provider_manager.remove(provider_id)
        except CyreneAIError as exc:
            return f"Provider stop failed: {exc}"
        return f"Provider {provider_id} stopped."

    async def _reload_provider(self, args: tuple[str, ...]) -> str:
        if not args:
            return "Usage: /provider reload <provider_id>"
        provider_id = args[0]
        config = await self._saved_provider_config_or_none(provider_id)
        if config is None:
            if not self._runtime.provider_manager.exists(provider_id):
                return f"Unknown provider: {provider_id}"
            config = self._runtime.provider_manager.get(provider_id).config
        try:
            await self._runtime.provider_manager.reload(config)
        except CyreneAIError as exc:
            return f"Provider reload failed: {exc}"
        return f"Provider {provider_id} reloaded."

    async def _check_provider(self, args: tuple[str, ...]) -> str:
        if not args:
            return "Usage: /provider check <provider_id>"
        provider_id = args[0]
        try:
            models = await self._runtime.provider_manager.list_models(provider_id)
        except CyreneAIError as exc:
            return f"Provider check failed: {exc}"
        return f"Provider {provider_id} reachable. models={len(models)}"

    async def _saved_provider_config_or_none(
        self,
        provider_id: str,
    ) -> ProviderConfig | None:
        store = self._runtime.provider_config_store
        if store is None:
            return None
        try:
            return await store.get_config(provider_id)
        except NotFoundError:
            return None


def _builtin_bot_commands_definition() -> PluginDefinition:
    return PluginDefinition(
        plugin_id=BUILTIN_BOT_COMMANDS_PLUGIN_ID,
        name="Builtin Bot Commands",
        description="Built-in bot command plugin.",
        builtin=True,
        capabilities=[
            PluginCapability.BOT_COMMAND,
            PluginCapability.STATUS,
            PluginCapability.TOOL,
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
                name="session",
                description="Show current session.",
                usage="/session",
            ),
            PluginCommandDefinition(
                name="session current",
                description="Show current session.",
                usage="/session current",
            ),
            PluginCommandDefinition(
                name="session ls",
                description="List sessions.",
                usage="/session ls",
            ),
            PluginCommandDefinition(
                name="session new",
                description="Create and select a session.",
                usage="/session new <name>",
            ),
            PluginCommandDefinition(
                name="session use",
                description="Select a session.",
                usage="/session use <name>",
            ),
            PluginCommandDefinition(
                name="session rename",
                description="Rename a session.",
                usage="/session rename <old> <new>",
            ),
            PluginCommandDefinition(
                name="session delete",
                description="Delete a session.",
                usage="/session delete <name>",
            ),
            PluginCommandDefinition(
                name="reset",
                description="Reset current session context.",
                usage="/reset [session]",
            ),
            PluginCommandDefinition(
                name="status",
                description="Show runtime status.",
                usage="/status",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="tool ls",
                description="List runtime tools.",
                usage="/tool ls",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="tool on",
                description="Enable a runtime tool.",
                usage="/tool on <name>",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="tool off",
                description="Disable a runtime tool.",
                usage="/tool off <name>",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="tool off_all",
                description="Disable all runtime tools.",
                usage="/tool off_all",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="provider ls",
                description="List running providers.",
                usage="/provider ls",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="provider catalog",
                description="List registered provider types.",
                usage="/provider catalog",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="provider status",
                description="Show provider status.",
                usage="/provider status <provider_id>",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="provider models",
                description="List provider models.",
                usage="/provider models <provider_id>",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="provider start",
                description="Start a saved provider.",
                usage="/provider start <provider_id>",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="provider stop",
                description="Stop a running provider.",
                usage="/provider stop <provider_id>",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="provider reload",
                description="Reload a provider.",
                usage="/provider reload <provider_id>",
                admin_required=True,
            ),
            PluginCommandDefinition(
                name="provider check",
                description="Check provider connectivity.",
                usage="/provider check <provider_id>",
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


def _request_event(request: PluginCommandRequest) -> BotEvent:
    if request.event is None:
        raise PluginInputError("插件命令请求必须包含 bot event")
    return request.event


def _render_conversation_current(conversation: BotConversationRef) -> str:
    return "\n".join(
        [
            "Current session:",
            f"name: {conversation.name}",
            f"context_session_id: {conversation.context_session_id}",
        ]
    )


def _metadata_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _render_command_usage(command: PluginCommandDefinition) -> str:
    if command.usage:
        return command.usage
    parts = [f"/{command.name}"]
    for argument in command.arguments:
        parts.append(_render_argument_usage(argument))
    return " ".join(parts)


def _render_argument_usage(argument: PluginCommandArgumentDefinition) -> str:
    type_suffix = "" if argument.type == "str" else f":{argument.type}"
    if argument.kind == PluginCommandArgumentKind.OPTION:
        names = [f"--{argument.name.replace('_', '-')}", *argument.aliases]
        display = "|".join(names)
        if argument.required:
            return f"<{display}{type_suffix}>"
        if argument.default is not None:
            return f"[{display}{type_suffix}={_format_default(argument.default)}]"
        return f"[{display}{type_suffix}]"
    if argument.kind == PluginCommandArgumentKind.FLAG:
        names = [f"--{argument.name.replace('_', '-')}", *argument.aliases]
        return f"[{'|'.join(names)}]"
    rest_suffix = "..." if argument.kind == PluginCommandArgumentKind.REST else ""
    if argument.required:
        return f"<{argument.name}{type_suffix}{rest_suffix}>"
    if argument.default is not None:
        return f"[{argument.name}{type_suffix}{rest_suffix}={_format_default(argument.default)}]"
    return f"[{argument.name}{type_suffix}{rest_suffix}]"


def _format_default(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _render_unknown_command(command_name: str) -> str:
    return "\n".join(
        [
            f"Unknown command: {command_name}",
            "Use /help to see available commands.",
        ]
    )
