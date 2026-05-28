from __future__ import annotations

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
        if should_parse_bot_command(request.event):
            return await self._command_event_to_result(request)

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
            actions=[action],
            chat_result=chat_result,
            tool_results=chat_result.tool_results,
            metadata={
                **request.metadata,
                "bot_event_id": request.event.event_id,
                "bot_channel_id": request.event.channel_id,
            },
        )


    async def _command_event_to_result(
        self,
        request: ApplicationBotRequest,
    ) -> ApplicationBotResult:
        command = parse_bot_command(request.event)
        plugin_manager = self._runtime.plugin_manager
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
                    metadata=request.metadata,
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
