from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from cyreneAI.application.channels.webhook_handler import (
    ApplicationChannelWebhookRequest,
    ChannelWebhookHandler,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError


logger = logging.getLogger(__name__)


class ChannelWebSocketRunner:
    """
    server 级 channel websocket 后台任务。
    """

    def __init__(
        self,
        *,
        runtime: CyreneAIRuntime,
        channel_id: str,
        provider_id: str,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_agent_steps: int = 4,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._runtime = runtime
        self._channel_id = channel_id
        self._provider_id = provider_id
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_agent_steps = max_agent_steps
        self._metadata = metadata or {}
        self._handler = ChannelWebhookHandler(runtime)
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self._task = asyncio.create_task(self.run_until_closed())

    async def stop(self) -> None:
        channel = self._channel()
        close_websocket = getattr(channel, "close_websocket", None)
        if close_websocket is not None:
            result = close_websocket()
            if hasattr(result, "__await__"):
                await result
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_until_closed(self) -> None:
        channel = self._channel()
        run_websocket = getattr(channel, "run_websocket", None)
        if run_websocket is None:
            raise RuntimeError(
                f"Bot channel {self._channel_id} does not support websocket updates"
            )
        result = run_websocket(self.handle_update)
        if hasattr(result, "__await__"):
            await result

    async def handle_update(self, update: dict[str, Any]) -> None:
        try:
            await self._handler.handle(
                ApplicationChannelWebhookRequest(
                    channel_id=self._channel_id,
                    payload=update.copy(),
                    provider_id=self._provider_id,
                    model=self._model,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    max_agent_steps=self._max_agent_steps,
                    metadata={
                        **self._metadata,
                        "websocket_channel_id": self._channel_id,
                        "websocket_event_id": str(update.get("id") or ""),
                        "websocket_event_type": str(update.get("t") or ""),
                    },
                )
            )
        except CyreneAIError:
            logger.exception(
                "Channel websocket update rejected: channel_id=%s event_id=%s",
                self._channel_id,
                update.get("id"),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Channel websocket update processing failed: channel_id=%s event_id=%s",
                self._channel_id,
                update.get("id"),
            )

    def _channel(self) -> Any:
        if self._runtime.bot_channel_registry is None:
            raise RuntimeError("Bot channel registry is not set")
        return self._runtime.bot_channel_registry.get_channel(self._channel_id)
