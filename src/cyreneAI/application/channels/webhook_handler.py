from __future__ import annotations

from typing import Any, cast

from pydantic import Field

from cyreneAI.application.bot.dispatcher import (
    ApplicationBotDispatchResult,
    BotDispatcher,
)
from cyreneAI.application.bot.orchestrator import ApplicationBotRequest
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.bot_protocol import BotUpdateMapperProtocol
from cyreneAI.core.errors.base import UnsupportedError
from cyreneAI.core.errors.bot import BotStateError
from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.context import ContextBudget
from cyreneAI.core.schema.tool import ToolChoice


class ApplicationChannelWebhookRequest(CyreneAISchema):
    """
    应用 channel webhook 请求。
    """

    channel_id: str
    payload: dict[str, Any]
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


class ChannelWebhookHandler:
    """
    channel webhook 处理器。
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime
        self._dispatcher = BotDispatcher(runtime)

    async def handle(
        self,
        request: ApplicationChannelWebhookRequest,
    ) -> ApplicationBotDispatchResult:
        """
        将 channel webhook payload 转入 bot 派发流程。
        """
        if self._runtime.bot_channel_registry is None:
            raise BotStateError("Bot channel registry is not set")

        channel = self._runtime.bot_channel_registry.get_channel(request.channel_id)
        if not hasattr(channel, "map_update"):
            raise UnsupportedError(
                f"Bot channel {request.channel_id} does not support webhook updates"
            )
        mapper = cast(BotUpdateMapperProtocol, channel)
        event = mapper.map_update(request.payload)

        return await self._dispatcher.dispatch(
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
                    "webhook_channel_id": request.channel_id,
                },
            )
        )
