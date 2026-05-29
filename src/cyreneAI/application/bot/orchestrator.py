from __future__ import annotations

import logging

from cyreneAI.application.chat.orchestrator import (
    ApplicationChatRequest,
    ApplicationChatResult,
    ChatOrchestrator,
)
from cyreneAI.application.bot.command_parser import (
    parse_bot_command,
    should_parse_bot_command,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.core.errors.plugin import PluginAuthorizationError, PluginNotFoundError
from cyreneAI.core.schema.bot import (
    BotAction,
    BotActionType,
    BotEvent,
    BotEventType,
    BotMessage,
)
from cyreneAI.core.errors.bot import BotInputError, BotUnsupportedEventError
from cyreneAI.core.schema.application import ApplicationBotRequest, ApplicationBotResult
from cyreneAI.core.schema.message import ContentPart, ContentPartType, Message, MessageRole
from cyreneAI.core.schema.plugin import PluginCommandRequest
from cyreneAI.core.schema.plugin import PluginEvent, PluginEventType


logger = logging.getLogger(__name__)


class BotOrchestrator:
    """
    应用 bot 编排器。
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime
        self._chat_orchestrator = ChatOrchestrator(runtime)

    async def handle(self, request: ApplicationBotRequest) -> ApplicationBotResult:
        """
        处理一次标准化 bot 事件。
        """
        plugin_event_actions = await self._dispatch_plugin_event(request)

        if should_parse_bot_command(request.event):
            command_result = await self._command_event_to_result(request)
            return command_result.model_copy(
                update={
                    "actions": [
                        *plugin_event_actions,
                        *command_result.actions,
                    ]
                }
            )

        if request.event.event_type != BotEventType.MESSAGE:
            raise BotUnsupportedEventError(
                f"Bot event {request.event.event_type} is not supported"
            )

        user_message = _bot_event_to_user_message(request.event)
        chat_result = await self._chat_orchestrator.chat(
            ApplicationChatRequest(
                session_id=request.event.session_id,
                provider_id=request.provider_id,
                model=request.model,
                messages=[user_message],
                context_budget=request.context_budget,
                required_skill_names=request.required_skill_names,
                max_skills=request.max_skills,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stream=request.stream,
                tool_choice=request.tool_choice,
                allowed_tool_names=request.allowed_tool_names,
                max_tool_rounds=request.max_tool_rounds,
                metadata={
                    **request.metadata,
                    "bot_event_id": request.event.event_id,
                    "bot_channel_id": request.event.channel_id,
                    "bot_user_id": request.event.user_id or "",
                },
            )
        )
        action = _chat_result_to_send_message_action(
            event=request.event,
            chat_result=chat_result,
        )
        return ApplicationBotResult(
            actions=[*plugin_event_actions, action],
            chat_result=chat_result,
            tool_results=chat_result.tool_results,
            metadata={
                **request.metadata,
                "bot_event_id": request.event.event_id,
                "bot_channel_id": request.event.channel_id,
            },
        )

    async def _dispatch_plugin_event(
        self,
        request: ApplicationBotRequest,
    ) -> list[BotAction]:
        plugin_manager = self._runtime.plugin_manager
        if plugin_manager is None:
            return []

        try:
            results = await plugin_manager.dispatch_event(
                _bot_event_to_plugin_event(request.event),
                metadata=request.metadata,
            )
        except CyreneAIError:
            logger.exception(
                "Plugin event dispatch failed; continuing bot main reply path"
            )
            return []
        return [action for result in results for action in result.actions]

    async def _command_event_to_result(
        self,
        request: ApplicationBotRequest,
    ) -> ApplicationBotResult:
        plugin_manager = self._runtime.plugin_manager
        command = parse_bot_command(
            request.event,
            known_command_names=_known_plugin_command_names(plugin_manager),
        )
        if plugin_manager is None:
            actions = [_unknown_command_action(request, command.name)]
            return _command_actions_to_result(request, command.name, command.args, actions)

        is_admin = _metadata_is_admin(request.metadata.get("is_admin"))
        try:
            plugin_result = await plugin_manager.execute_command(
                PluginCommandRequest(
                    command=command,
                    event=request.event,
                    is_admin=is_admin,
                    metadata={
                        **request.metadata,
                        "provider_id": request.provider_id,
                        "model": request.model,
                    },
                )
            )
        except PluginNotFoundError:
            actions = [_unknown_command_action(request, command.name)]
            return _command_actions_to_result(request, command.name, command.args, actions)
        except PluginAuthorizationError:
            actions = [
                _command_text_action(
                    request=request,
                    command_name=command.name,
                    command_args=command.args,
                    text=f"Command /{command.name} requires admin permission.",
                )
            ]
            return _command_actions_to_result(request, command.name, command.args, actions)

        return ApplicationBotResult(
            actions=plugin_result.actions,
            metadata={
                **request.metadata,
                **plugin_result.metadata,
                "bot_event_id": request.event.event_id,
                "bot_channel_id": request.event.channel_id,
                "command": command.name,
                "command_args": list(command.args),
            },
        )


def _command_actions_to_result(
    request: ApplicationBotRequest,
    command_name: str,
    command_args: tuple[str, ...],
    actions: list[BotAction],
) -> ApplicationBotResult:
    return ApplicationBotResult(
        actions=actions,
        metadata={
            **request.metadata,
            "bot_event_id": request.event.event_id,
            "bot_channel_id": request.event.channel_id,
            "command": command_name,
            "command_args": list(command_args),
        },
    )


def _unknown_command_action(
    request: ApplicationBotRequest,
    command_name: str,
) -> BotAction:
    return _command_text_action(
        request=request,
        command_name=command_name,
        command_args=(),
        text="\n".join(
            [
                f"Unknown command: {command_name}",
                "Use /help to see available commands.",
            ]
        ),
    )


def _command_text_action(
    *,
    request: ApplicationBotRequest,
    command_name: str,
    command_args: tuple[str, ...],
    text: str,
) -> BotAction:
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
                "command": command_name,
            },
        ),
        metadata={
            "bot_event_id": request.event.event_id,
            "command": command_name,
            "command_args": list(command_args),
        },
    )


def _metadata_is_admin(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.casefold() == "true"
    return False


def _known_plugin_command_names(plugin_manager: object | None) -> set[str] | None:
    if plugin_manager is None:
        return None
    return {
        name
        for command in plugin_manager.list_commands()
        for name in (command.name, *command.aliases)
    }


def _bot_event_to_plugin_event(event: BotEvent) -> PluginEvent:
    return PluginEvent(
        event_id=event.event_id,
        event_type=_plugin_event_type(event.event_type),
        session_id=event.session_id,
        user_id=event.user_id,
        thread_id=event.thread_id,
        message_id=event.message.message_id if event.message is not None else None,
        text=_bot_event_text(event),
    )


def _plugin_event_type(event_type: BotEventType) -> PluginEventType:
    try:
        return PluginEventType(str(event_type))
    except ValueError:
        return PluginEventType.UNKNOWN


def _bot_event_text(event: BotEvent) -> str | None:
    if event.message is None:
        return None
    texts = [
        part.text
        for part in event.message.content
        if part.type == ContentPartType.TEXT and part.text is not None
    ]
    if not texts:
        return None
    return "".join(texts)


def _bot_event_to_user_message(event: BotEvent) -> Message:
    if event.message is None:
        raise BotInputError("MESSAGE event must include message")
    if not event.message.content:
        raise BotInputError("MESSAGE event must include message content")

    return Message(
        role=MessageRole.USER,
        name=event.user_id,
        content=event.message.content,
    )


def _chat_result_to_send_message_action(
    *,
    event: BotEvent,
    chat_result: ApplicationChatResult,
) -> BotAction:
    response_message = chat_result.response.message
    content = response_message.content if response_message is not None else None
    if not content:
        content = [
            ContentPart(
                type=ContentPartType.TEXT,
                text="",
            )
        ]

    return BotAction(
        action_type=BotActionType.SEND_MESSAGE,
        channel_id=event.channel_id,
        session_id=event.session_id,
        recipient_id=event.user_id,
        thread_id=event.thread_id,
        message=BotMessage(
            sender_id="bot",
            content=content,
            metadata={
                "provider_id": chat_result.response.provider_id,
                "model": chat_result.response.model or "",
            },
        ),
        metadata={
            "bot_event_id": event.event_id,
            "finish_reason": chat_result.response.finish_reason,
        },
    )
