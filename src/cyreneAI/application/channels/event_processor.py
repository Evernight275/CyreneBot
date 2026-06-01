from __future__ import annotations

from cyreneAI.application.bot.dispatcher import (
    ApplicationBotDispatchResult,
    BotDispatcher,
)
from cyreneAI.application.bot.orchestrator import ApplicationBotRequest
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.schema.application import (
    ApplicationChannelEventsRequest,
    ApplicationChannelEventsResult,
)


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
                        tool_execution_policy=request.tool_execution_policy,
                        max_tool_rounds=request.max_tool_rounds,
                        max_agent_steps=request.max_agent_steps,
                        message_response_mode=request.message_response_mode,
                        message_trigger_mode=request.message_trigger_mode,
                        message_trigger_keywords=request.message_trigger_keywords,
                        message_trigger_mentions=request.message_trigger_mentions,
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
