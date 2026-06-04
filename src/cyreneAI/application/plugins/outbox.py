from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.core.errors.bot import BotStateError
from cyreneAI.core.schema.bot import BotAction, BotActionType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import PluginMessageReceipt

DEFAULT_MIN_INTERVAL_SECONDS = 30.0
DEFAULT_MAX_PER_SESSION_PER_HOUR = 12
DEFAULT_MAX_PER_PLUGIN_PER_HOUR = 60
RATE_LIMIT_WINDOW_SECONDS = 3600.0


class ApplicationPluginOutbox:
    """
    application 托管的插件出站消息服务。
    """

    def __init__(
        self,
        runtime: CyreneAIRuntime,
        *,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        max_per_session_per_hour: int = DEFAULT_MAX_PER_SESSION_PER_HOUR,
        max_per_plugin_per_hour: int = DEFAULT_MAX_PER_PLUGIN_PER_HOUR,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._runtime = runtime
        self._min_interval_seconds = max(0.0, min_interval_seconds)
        self._max_per_session_per_hour = max(1, max_per_session_per_hour)
        self._max_per_plugin_per_hour = max(1, max_per_plugin_per_hour)
        self._clock = clock or time.monotonic
        self._lock = asyncio.Lock()
        self._session_history: dict[tuple[str, str], deque[float]] = {}
        self._plugin_history: dict[str, deque[float]] = {}

    def namespace(
        self,
        plugin_id: str,
        *,
        can_bypass_rate_limit: bool = False,
    ) -> "_ApplicationPluginOutboxNamespace":
        return _ApplicationPluginOutboxNamespace(
            self,
            plugin_id,
            can_bypass_rate_limit=can_bypass_rate_limit,
        )

    async def send(
        self,
        plugin_id: str,
        session_id: str,
        *,
        text: str,
        metadata: dict[str, object] | None = None,
        bypass_rate_limit: bool = False,
        can_bypass_rate_limit: bool = False,
    ) -> PluginMessageReceipt:
        if self._runtime.bot_channel_registry is None:
            raise BotStateError("Bot channel registry is not set")
        if self._runtime.bot_session_manager is None:
            raise BotStateError("Bot session manager is not set")

        state = await self._runtime.bot_session_manager.get_state(session_id)
        rate_limit_bypassed = bypass_rate_limit and can_bypass_rate_limit
        if not rate_limit_bypassed:
            rate_limited = await self._reserve_send(plugin_id, state.session.session_id)
            if rate_limited is not None:
                return rate_limited

        session = state.session
        message_metadata: dict[str, Any] = {
            "plugin_id": plugin_id,
            **(metadata or {}),
        }
        if rate_limit_bypassed:
            message_metadata["rate_limit_bypassed"] = True

        action = BotAction(
            action_type=BotActionType.SEND_MESSAGE,
            channel_id=session.channel_id,
            session_id=session.session_id,
            recipient_id=session.user_id,
            thread_id=session.thread_id,
            message=BotMessage(
                sender_id="bot",
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=text,
                    )
                ],
                metadata=message_metadata,
            ),
            metadata=message_metadata,
        )

        channel = self._runtime.bot_channel_registry.get_channel(session.channel_id)
        try:
            await channel.send(action)
        except CyreneAIError as exc:
            return PluginMessageReceipt(
                session_id=session.session_id,
                accepted=False,
                metadata={
                    **message_metadata,
                    "send_failed": True,
                    "reason": str(exc),
                },
            )
        return PluginMessageReceipt(
            session_id=session.session_id,
            metadata=message_metadata,
        )

    async def _reserve_send(
        self,
        plugin_id: str,
        session_id: str,
    ) -> PluginMessageReceipt | None:
        now = self._clock()
        async with self._lock:
            session_history = self._session_history.setdefault(
                (plugin_id, session_id),
                deque(),
            )
            plugin_history = self._plugin_history.setdefault(plugin_id, deque())
            _purge_old(session_history, now)
            _purge_old(plugin_history, now)

            if session_history:
                elapsed = now - session_history[-1]
                if elapsed < self._min_interval_seconds:
                    return _rate_limited_receipt(
                        session_id,
                        reason="min_interval",
                        retry_after_seconds=self._min_interval_seconds - elapsed,
                    )

            if len(session_history) >= self._max_per_session_per_hour:
                return _rate_limited_receipt(
                    session_id,
                    reason="session_hourly_limit",
                    retry_after_seconds=_retry_after_window(session_history, now),
                )

            if len(plugin_history) >= self._max_per_plugin_per_hour:
                return _rate_limited_receipt(
                    session_id,
                    reason="plugin_hourly_limit",
                    retry_after_seconds=_retry_after_window(plugin_history, now),
                )

            session_history.append(now)
            plugin_history.append(now)
            return None


class _ApplicationPluginOutboxNamespace:
    def __init__(
        self,
        outbox: ApplicationPluginOutbox,
        plugin_id: str,
        *,
        can_bypass_rate_limit: bool = False,
    ) -> None:
        self._outbox = outbox
        self._plugin_id = plugin_id
        self._can_bypass_rate_limit = can_bypass_rate_limit

    async def send(
        self,
        session_id: str,
        *,
        text: str,
        metadata: dict[str, object] | None = None,
        bypass_rate_limit: bool = False,
    ) -> PluginMessageReceipt:
        return await self._outbox.send(
            self._plugin_id,
            session_id,
            text=text,
            metadata=metadata,
            bypass_rate_limit=bypass_rate_limit,
            can_bypass_rate_limit=self._can_bypass_rate_limit,
        )


def _purge_old(history: deque[float], now: float) -> None:
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    while history and history[0] <= cutoff:
        history.popleft()


def _retry_after_window(history: deque[float], now: float) -> float:
    if not history:
        return 0.0
    return max(0.0, RATE_LIMIT_WINDOW_SECONDS - (now - history[0]))


def _rate_limited_receipt(
    session_id: str,
    *,
    reason: str,
    retry_after_seconds: float,
) -> PluginMessageReceipt:
    return PluginMessageReceipt(
        session_id=session_id,
        accepted=False,
        metadata={
            "rate_limited": True,
            "reason": reason,
            "retry_after_seconds": round(retry_after_seconds, 3),
        },
    )


__all__ = [
    "ApplicationPluginOutbox",
    "DEFAULT_MAX_PER_PLUGIN_PER_HOUR",
    "DEFAULT_MAX_PER_SESSION_PER_HOUR",
    "DEFAULT_MIN_INTERVAL_SECONDS",
]
