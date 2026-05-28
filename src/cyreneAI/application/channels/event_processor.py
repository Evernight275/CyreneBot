from __future__ import annotations

from typing import Any

from pydantic import Field

from cyreneAI.application.bot.dispatcher import (
    ApplicationBotDispatchResult,
    BotDispatcher,
)
from cyreneAI.application.bot.orchestrator import ApplicationBotRequest
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.bot import BotEvent
from cyreneAI.core.schema.context import ContextBudget
from cyreneAI.core.schema.tool import ToolChoice


class ApplicationChannelEventsRequest(CyreneAISchema):
    """
    应用 channel 事件批处理请求。
    """

    events: list[BotEvent] = Field(default_factory=list)
    provider_id: str
    model: str

    context_budget: ContextBudget | None = None
    required_skill_names: list[str] = Field(default_factory=list)
    max_skills: int | None = None

    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    tool_choice: ToolChoice | None = None
    allowed_tool_names: list[str] | None = None
    max_tool_rounds: int = Field(default=1, ge=0)

    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationChannelEventsResult(CyreneAISchema):
    """
    应用 channel 事件批处理结果。
    """

    dispatch_results: list[ApplicationBotDispatchResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelEventProcessor:
    """
    channel 事件批处理器。
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._dispatcher = BotDispatcher(runtime)

    async def process(
        self,
        request: ApplicationChannelEventsRequest,
    ) -> ApplicationChannelEventsResult:
        """
        按顺序处理一批标准化 BotEvent。
        """
        dispatch_results: list[ApplicationBotDispatchResult] = []
        event_count = len(request.events)
        for index, event in enumerate(request.events):
            dispatch_results.append(
                await self._dispatcher.dispatch(
                    ApplicationBotRequest(
                        event=event,
                        provider_id=request.provider_id,
                        model=request.model,
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
                            "channel_event_count": str(event_count),
                            "channel_event_index": str(index),
                        },
                    )
                )
            )

        return ApplicationChannelEventsResult(
            dispatch_results=dispatch_results,
            metadata={
                **request.metadata,
                "channel_event_count": str(event_count),
            },
        )
