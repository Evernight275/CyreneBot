from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any, cast

from cyreneAI.application.channels.event_processor import ChannelEventProcessor
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.bot_protocol import BotEventPollerProtocol
from cyreneAI.core.schema.application import ApplicationChannelEventsRequest
from cyreneAI.core.schema.bot import BotEvent

logger = logging.getLogger(__name__)


class ChannelPollingRunner:
    """
    server 级 channel polling 后台任务。
    """

    def __init__(
        self,
        *,
        runtime: CyreneAIRuntime,
        channel_id: str,
        provider_id: str,
        model: str,
        interval_seconds: float = 1.0,
        timeout_seconds: int = 30,
        limit: int | None = None,
        allowed_updates: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._runtime = runtime
        self._channel_id = channel_id
        self._provider_id = provider_id
        self._model = model
        self._interval_seconds = interval_seconds
        self._timeout_seconds = timeout_seconds
        self._limit = limit
        self._allowed_updates = allowed_updates
        self._metadata = metadata or {}
        self._offset: int | None = None
        self._offset_loaded = False
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._processor = ChannelEventProcessor(runtime)

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def offset(self) -> int | None:
        return self._offset

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> int:
        await self._load_offset()
        poller = self._poller()
        events = await poller.poll_events(
            offset=self._offset,
            limit=self._limit,
            timeout=self._timeout_seconds,
            allowed_updates=self._allowed_updates,
        )
        if not events:
            return 0

        pending_events = await self._pending_events(events)
        if not pending_events:
            await self._save_offset_for(events)
            return 0

        processed_count = 0
        attempted_events: list[BotEvent] = []
        for event in pending_events:
            attempted_events.append(event)
            try:
                await self._processor.process(
                    ApplicationChannelEventsRequest(
                        events=[event],
                        provider_id=self._provider_id,
                        model=self._model,
                        metadata={
                            **self._metadata,
                            "polling_channel_id": self._channel_id,
                        },
                    )
                )
                processed_count += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Polling event processing failed; advancing offset to avoid a stuck update: channel_id=%s event_id=%s",
                    self._channel_id,
                    event.event_id,
                )

        await self._mark_events_processed(attempted_events)
        await self._save_offset_for(events)
        return processed_count

    async def run_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Channel polling iteration failed: channel_id=%s",
                    self._channel_id,
                )
                await asyncio.sleep(self._interval_seconds)
                continue
            await asyncio.sleep(self._interval_seconds)

    def _poller(self) -> BotEventPollerProtocol:
        if self._runtime.bot_channel_registry is None:
            raise RuntimeError("Bot channel registry is not set")
        channel = self._runtime.bot_channel_registry.get_channel(self._channel_id)
        if not hasattr(channel, "poll_events"):
            raise RuntimeError(
                f"Bot channel {self._channel_id} does not support polling"
            )
        return cast(BotEventPollerProtocol, channel)

    async def _load_offset(self) -> None:
        if self._offset_loaded:
            return
        state_store = self._runtime.bot_polling_state_store
        if state_store is not None:
            self._offset = await state_store.get_offset(self._channel_id)
        self._offset_loaded = True

    async def _pending_events(self, events: list[BotEvent]) -> list[BotEvent]:
        state_store = self._runtime.bot_polling_state_store
        if state_store is None:
            return events

        pending_events: list[BotEvent] = []
        for event in events:
            if not await state_store.is_event_processed(
                self._channel_id,
                event.event_id,
            ):
                pending_events.append(event)
        return pending_events

    async def _mark_events_processed(self, events: list[BotEvent]) -> None:
        state_store = self._runtime.bot_polling_state_store
        if state_store is None:
            return
        for event in events:
            await state_store.mark_event_processed(
                self._channel_id,
                event.event_id,
            )

    async def _save_offset_for(self, events: list[BotEvent]) -> None:
        offset = self._next_offset(events)
        if offset is None:
            return
        self._offset = offset
        state_store = self._runtime.bot_polling_state_store
        if state_store is not None:
            await state_store.save_offset(self._channel_id, offset)

    def _next_offset(self, events: list[BotEvent]) -> int | None:
        event_ids: list[int] = []
        for event in events:
            try:
                event_ids.append(int(event.event_id))
            except ValueError:
                continue
        if event_ids:
            return max(event_ids) + 1
        return None
