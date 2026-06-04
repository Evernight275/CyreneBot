from __future__ import annotations

from inspect import isasyncgen, isgenerator
from typing import Any

from cyreneAI.core.errors.plugin import PluginExecutionError, PluginInputError
from cyreneAI.core.schema.bot import BotAction, BotActionType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import PluginCommandRequest, PluginCommandResult


def text(
    request: PluginCommandRequest,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> PluginCommandResult:
    """
    构造文本回复结果。
    """
    if request.event is None:
        raise PluginInputError("text reply requires request.event")

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
                    text=content,
                )
            ],
            metadata={
                "command": request.command.name,
                **(metadata or {}),
            },
        ),
        metadata={
            "bot_event_id": request.event.event_id,
            "command": request.command.name,
            **(metadata or {}),
        },
    )
    return PluginCommandResult(
        actions=[action],
        metadata=metadata or {},
    )


async def _coerce_command_handler_result(
    request: PluginCommandRequest,
    result: Any,
) -> PluginCommandResult:
    if isinstance(result, str):
        return text(request, result)
    if isinstance(result, PluginCommandResult):
        return result
    if isasyncgen(result):
        partials: list[PluginCommandResult] = []
        async for item in result:
            partials.append(_coerce_command_result_item(request, item))
        return _merge_command_results(partials)
    if isgenerator(result):
        return _merge_command_results(
            [_coerce_command_result_item(request, item) for item in result]
        )
    raise PluginExecutionError(
        f"插件命令 {request.command.name} 必须返回 str、PluginCommandResult，或 yield 它们"
    )


def _coerce_command_result_item(
    request: PluginCommandRequest,
    item: Any,
) -> PluginCommandResult:
    if isinstance(item, str):
        return text(request, item)
    if isinstance(item, PluginCommandResult):
        return item
    raise PluginExecutionError(
        f"插件命令 {request.command.name} yield 项必须是 str 或 PluginCommandResult"
    )


def _merge_command_results(
    results: list[PluginCommandResult],
) -> PluginCommandResult:
    actions: list[BotAction] = []
    metadata: dict[str, Any] = {}
    handled = True
    for result in results:
        handled = handled and result.handled
        actions.extend(result.actions)
        metadata.update(result.metadata)
    return PluginCommandResult(
        handled=handled,
        actions=actions,
        metadata=metadata,
    )
