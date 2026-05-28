from __future__ import annotations

from cyreneAI.application.chat.orchestrator import (
    ApplicationChatRequest,
    ApplicationChatResult,
    ChatOrchestrator,
)
from cyreneAI.application.bot.command_parser import (
    parse_bot_command,
    render_bot_command_result,
    should_parse_bot_command,
)
from cyreneAI.application.runtime import CyreneAIRuntime
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
            return _command_event_to_result(request)

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


def _command_event_to_result(request: ApplicationBotRequest) -> ApplicationBotResult:
    command = parse_bot_command(request.event)
    action = BotAction(
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
                    text=render_bot_command_result(command),
                )
            ],
            metadata={
                "command": command.name,
            },
        ),
        metadata={
            "bot_event_id": request.event.event_id,
            "command": command.name,
            "command_args": list(command.args),
        },
    )
    return ApplicationBotResult(
        actions=[action],
        metadata={
            **request.metadata,
            "bot_event_id": request.event.event_id,
            "bot_channel_id": request.event.channel_id,
            "command": command.name,
            "command_args": list(command.args),
        },
    )


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
