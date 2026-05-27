from __future__ import annotations

from pydantic import Field

from cyreneAI.application.bot_orchestrator import (
    ApplicationBotRequest,
    ApplicationBotResult,
    BotOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.bot import BotStateError
from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.bot import BotAction, BotConversationState


class ApplicationBotDispatchResult(CyreneAISchema):
    """
    应用 bot 派发结果。
    """

    bot_result: ApplicationBotResult
    sent_actions: list[BotAction] = Field(default_factory=list)
    session_state: BotConversationState | None = None


class BotDispatcher:
    """
    bot 事件派发器。
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime
        self._orchestrator = BotOrchestrator(runtime)

    async def dispatch(
        self,
        request: ApplicationBotRequest,
    ) -> ApplicationBotDispatchResult:
        """
        处理 bot 事件并把动作派发到对应 channel。
        """
        if self._runtime.bot_channel_registry is None:
            raise BotStateError("Bot channel registry is not set")

        session_state = None
        orchestrator_request = request
        if self._runtime.bot_session_manager is not None:
            await self._runtime.bot_session_manager.get_or_create(request.event)
            session_state = await self._runtime.bot_session_manager.update_activity(
                session_id=request.event.session_id,
                event_id=request.event.event_id,
                metadata={
                    "channel_id": request.event.channel_id,
                    "user_id": request.event.user_id or "",
                    "thread_id": request.event.thread_id or "",
                },
            )
            orchestrator_request = request.model_copy(
                update={
                    "metadata": {
                        **request.metadata,
                        "bot_session_id": session_state.session.session_id,
                        "bot_session_status": session_state.session.status,
                        "bot_turn_count": str(session_state.turn_count),
                    }
                }
            )

        bot_result = await self._orchestrator.handle(orchestrator_request)
        sent_actions: list[BotAction] = []
        for action in bot_result.actions:
            channel = self._runtime.bot_channel_registry.get_channel(action.channel_id)
            await channel.send(action)
            sent_actions.append(action)

        return ApplicationBotDispatchResult(
            bot_result=bot_result,
            sent_actions=sent_actions,
            session_state=session_state,
        )
