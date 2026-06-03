from __future__ import annotations

import logging

from cyreneAI.application.agent.orchestrator import AgentOrchestrator
from cyreneAI.application.agent.request_builder import build_agent_run_request
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
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginError,
    PluginExecutionError,
    PluginInputError,
    PluginNotFoundError,
)
from cyreneAI.core.schema.bot import (
    BotAction,
    BotActionType,
    BotEvent,
    BotEventType,
    BotMessage,
)
from cyreneAI.core.errors.bot import BotInputError, BotUnsupportedEventError
from cyreneAI.core.schema.application import ApplicationBotRequest, ApplicationBotResult
from cyreneAI.core.schema.application import BotMessageResponseMode, BotMessageTriggerMode
from cyreneAI.core.schema.message import ContentPart, ContentPartType, Message, MessageRole
from cyreneAI.core.schema.plugin import PluginCommandRequest
from cyreneAI.core.schema.plugin import PluginEvent, PluginEventType
from cyreneAI.core.schema.agent import AgentRunResult
from cyreneAI.core.schema.tool import ToolResult


logger = logging.getLogger(__name__)


class BotOrchestrator:
    """
    应用 bot 编排器。
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime
        self._chat_orchestrator = ChatOrchestrator(runtime)
        self._agent_orchestrator = AgentOrchestrator(runtime)

    async def handle(self, request: ApplicationBotRequest) -> ApplicationBotResult:
        """
        处理一次标准化 bot 事件。
        """
        request = _request_with_bot_admin_metadata(request, self._runtime)
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

        if not _should_trigger_message_response(request):
            return ApplicationBotResult(
                actions=plugin_event_actions,
                metadata={
                    **request.metadata,
                    "bot_event_id": request.event.event_id,
                    "bot_channel_id": request.event.channel_id,
                    "message_triggered": False,
                    "message_trigger_mode": request.message_trigger_mode,
                },
            )

        user_message = _bot_event_to_user_message(request.event)
        context_session_id = _context_session_id(request)
        if request.message_response_mode == BotMessageResponseMode.AGENT:
            agent_result = await self._agent_orchestrator.run(
                build_agent_run_request(
                    session_id=context_session_id,
                    provider_id=request.provider_id,
                    model=request.model,
                    messages=[user_message],
                    context_budget=request.context_budget,
                    max_steps=request.max_agent_steps,
                    required_skill_names=request.required_skill_names,
                    max_skills=request.max_skills,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    stream=request.stream,
                    tool_choice=request.tool_choice,
                    allowed_tool_names=request.allowed_tool_names,
                    tool_execution_policy=request.tool_execution_policy,
                    max_tool_calls_per_step=request.max_agent_tool_calls_per_step,
                    max_total_tool_calls=request.max_agent_total_tool_calls,
                    max_tool_result_chars=request.max_agent_tool_result_chars,
                    planning=request.agent_planning,
                    tool_selection=request.agent_tool_selection,
                    memory_retrieval=request.agent_memory_retrieval,
                    metadata={
                        **request.metadata,
                        "bot_event_id": request.event.event_id,
                        "bot_channel_id": request.event.channel_id,
                        "bot_user_id": request.event.user_id or "",
                    },
                )
            )
            action = _agent_result_to_send_message_action(
                event=request.event,
                agent_result=agent_result,
            )
            return ApplicationBotResult(
                actions=[*plugin_event_actions, action],
                agent_result=agent_result,
                tool_results=_agent_tool_results(agent_result),
                metadata={
                    **request.metadata,
                    "bot_event_id": request.event.event_id,
                    "bot_channel_id": request.event.channel_id,
                    "message_response_mode": request.message_response_mode,
                },
            )

        chat_result = await self._chat_orchestrator.chat(
            ApplicationChatRequest(
                session_id=context_session_id,
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
                tool_execution_policy=request.tool_execution_policy,
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
                "message_response_mode": request.message_response_mode,
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
                metadata={
                    **request.metadata,
                    "provider_id": request.provider_id,
                    "model": request.model,
                },
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
        except PluginInputError as exc:
            actions = [
                _command_text_action(
                    request=request,
                    command_name=command.name,
                    command_args=command.args,
                    text=str(exc),
                )
            ]
            return _command_actions_to_result(request, command.name, command.args, actions)
        except PluginExecutionError:
            logger.exception(
                "Plugin command execution failed: command=%s",
                command.name,
            )
            actions = [
                _command_text_action(
                    request=request,
                    command_name=command.name,
                    command_args=command.args,
                    text=f"Command /{command.name} failed.",
                )
            ]
            return _command_actions_to_result(request, command.name, command.args, actions)
        except PluginError:
            logger.exception(
                "Plugin command failed: command=%s",
                command.name,
            )
            actions = [
                _command_text_action(
                    request=request,
                    command_name=command.name,
                    command_args=command.args,
                    text=f"Command /{command.name} failed.",
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


def _request_with_bot_admin_metadata(
    request: ApplicationBotRequest,
    runtime: CyreneAIRuntime,
) -> ApplicationBotRequest:
    if not _is_bot_admin_request(request, runtime):
        return request
    if _metadata_is_admin(request.metadata.get("is_admin")):
        return request
    return request.model_copy(
        update={
            "metadata": {
                **request.metadata,
                "is_admin": True,
            }
        }
    )


def _is_bot_admin_request(
    request: ApplicationBotRequest,
    runtime: CyreneAIRuntime,
) -> bool:
    if _metadata_is_admin(request.metadata.get("is_admin")):
        return True

    user_id = request.event.user_id
    if user_id is None:
        return False

    config = runtime.bot_admin_config
    if config is None:
        return False

    normalized_user_id = str(user_id).strip()
    return any(
        normalized_user_id == configured_user_id.strip()
        for configured_user_id in config.user_ids
        if configured_user_id.strip()
    )


def _known_plugin_command_names(plugin_manager: PluginManager | None) -> set[str] | None:
    if plugin_manager is None:
        return None
    return {
        name
        for command in plugin_manager.list_commands()
        for name in (command.name, *command.aliases)
    }


def _should_trigger_message_response(request: ApplicationBotRequest) -> bool:
    mode = request.message_trigger_mode
    if mode == BotMessageTriggerMode.ALWAYS:
        return True
    if mode == BotMessageTriggerMode.NEVER:
        return False
    if mode == BotMessageTriggerMode.DIRECT:
        return _is_direct_message(request.event)
    if mode == BotMessageTriggerMode.MENTION:
        return _is_mentioned(request)
    if mode == BotMessageTriggerMode.KEYWORD:
        return _has_trigger_keyword(request)
    if mode == BotMessageTriggerMode.DIRECT_OR_MENTION:
        return _is_direct_message(request.event) or _is_mentioned(request)
    return False


def _is_direct_message(event: BotEvent) -> bool:
    if _metadata_truthy(event.metadata.get("is_direct")):
        return True
    if event.message is not None and _metadata_truthy(
        event.message.metadata.get("is_direct")
    ):
        return True

    chat_type = event.metadata.get("telegram_chat_type")
    if chat_type is None and event.message is not None:
        chat_type = event.message.metadata.get("telegram_chat_type")
    return str(chat_type).casefold() == "private"


def _is_mentioned(request: ApplicationBotRequest) -> bool:
    if _metadata_truthy(request.event.metadata.get("bot_was_mentioned")):
        return True

    text = _bot_event_text(request.event)
    if not text:
        return False
    normalized_text = text.casefold()
    mentions = [
        mention.casefold().removeprefix("@")
        for mention in request.message_trigger_mentions
        if mention.strip()
    ]
    return any(
        f"@{mention}" in normalized_text
        for mention in mentions
    )


def _has_trigger_keyword(request: ApplicationBotRequest) -> bool:
    text = _bot_event_text(request.event)
    if not text:
        return False
    normalized_text = text.casefold()
    return any(
        keyword.strip().casefold() in normalized_text
        for keyword in request.message_trigger_keywords
        if keyword.strip()
    )


def _metadata_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.casefold() in {"1", "true", "yes", "on"}
    return False


def _context_session_id(request: ApplicationBotRequest) -> str:
    value = request.metadata.get("context_session_id")
    if isinstance(value, str) and value:
        return value
    return request.event.session_id


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


def _agent_result_to_send_message_action(
    *,
    event: BotEvent,
    agent_result: AgentRunResult,
) -> BotAction:
    response_message = agent_result.response.message
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
                "provider_id": agent_result.response.provider_id,
                "model": agent_result.response.model or "",
                "agent_stop_reason": agent_result.stop_reason,
            },
        ),
        metadata={
            "bot_event_id": event.event_id,
            "agent_completed": agent_result.completed,
            "agent_stop_reason": agent_result.stop_reason,
        },
    )


def _agent_tool_results(agent_result: AgentRunResult) -> list[ToolResult]:
    return [
        tool_result
        for step in agent_result.steps
        for tool_result in step.tool_results
    ]
