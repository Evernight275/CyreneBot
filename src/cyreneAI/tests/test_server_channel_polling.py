from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.bot import (
    BotAction,
    BotChannelDefinition,
    BotEvent,
    BotEventType,
    BotMessage,
)
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest, ChatResponse
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.infra.adapters.bot_polling_states.memory import (
    InMemoryBotPollingStateStore,
)
from cyreneAI.infra.adapters.bot_polling_states.sqlite import (
    create_sqlite_bot_polling_state_store,
)
from cyreneAI.server.channel_polling import ChannelPollingRunner


def _content(text: str) -> list[ContentPart]:
    return [
        ContentPart(
            type=ContentPartType.TEXT,
            text=text,
        )
    ]


def _event(event_id: str, text: str) -> BotEvent:
    return BotEvent(
        event_id=event_id,
        event_type=BotEventType.MESSAGE,
        channel_id="telegram",
        session_id="telegram:99",
        user_id="42",
        thread_id="99",
        message=BotMessage(
            sender_id="42",
            content=_content(text),
        ),
    )


class FakePollingProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        name="fake",
        description="Fake polling provider.",
    )
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        timeout=timedelta(seconds=1),
    )

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        text = (
            request.messages[-1].content[0].text if request.messages[-1].content else ""
        )
        return ChatResponse(
            provider_id=request.provider_id,
            model=request.model,
            message=Message(
                role=MessageRole.ASSISTANT,
                content=_content(f"reply:{text}"),
            ),
            finish_reason=ChatFinishReason.STOP,
        )

    async def close(self) -> None:
        pass


class FakePollingChannel:
    def __init__(self) -> None:
        self.poll_requests: list[dict] = []
        self.actions: list[BotAction] = []
        self.event_batches = [
            [
                _event("1000", "one"),
                _event("1001", "two"),
            ],
            [],
        ]

    async def poll_events(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
        timeout: int | None = None,
        allowed_updates: list[str] | None = None,
    ) -> list[BotEvent]:
        self.poll_requests.append(
            {
                "offset": offset,
                "limit": limit,
                "timeout": timeout,
                "allowed_updates": allowed_updates,
            }
        )
        return self.event_batches.pop(0)

    async def send(self, action: BotAction) -> None:
        self.actions.append(action)


class FailingFirstSendPollingChannel(FakePollingChannel):
    def __init__(self) -> None:
        super().__init__()
        self.send_calls = 0

    async def send(self, action: BotAction) -> None:
        self.send_calls += 1
        if self.send_calls == 1:
            raise RuntimeError("telegram send failed")
        await super().send(action)


async def _build_runtime(
    provider: FakePollingProvider,
    channel: FakePollingChannel,
    polling_state_store=None,
) -> CyreneAIRuntime:
    registry = BotChannelRegistry()
    registry.register(
        BotChannelDefinition(
            channel_id="telegram",
            name="Telegram",
        ),
        channel,
    )
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig) -> FakePollingProvider:
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    manager = ProviderManager(factory)
    await manager.add(provider.config)
    return CyreneAIRuntime(
        provider_manager=manager,
        context_builder=ContextWindowBuilder(),
        bot_channel_registry=registry,
        bot_polling_state_store=polling_state_store,
    )


def test_channel_polling_runner_processes_events_and_advances_offset() -> None:
    async def run() -> None:
        provider = FakePollingProvider()
        channel = FakePollingChannel()
        runtime = await _build_runtime(provider, channel)
        runner = ChannelPollingRunner(
            runtime=runtime,
            channel_id="telegram",
            provider_id="provider-1",
            model="chat-model",
            interval_seconds=0,
            timeout_seconds=30,
            limit=10,
            allowed_updates=["message"],
            metadata={"source": "test"},
        )

        processed = await runner.run_once()
        empty_processed = await runner.run_once()

        assert processed == 2
        assert empty_processed == 0
        assert runner.offset == 1002
        assert channel.poll_requests == [
            {
                "offset": None,
                "limit": 10,
                "timeout": 30,
                "allowed_updates": ["message"],
            },
            {
                "offset": 1002,
                "limit": 10,
                "timeout": 30,
                "allowed_updates": ["message"],
            },
        ]
        assert [request.messages[-1].content for request in provider.requests] == [
            _content("one"),
            _content("two"),
        ]
        assert provider.requests[0].metadata["polling_channel_id"] == "telegram"
        assert provider.requests[0].metadata["source"] == "test"
        assert [
            action.message.content for action in channel.actions if action.message
        ] == [
            _content("reply:one"),
            _content("reply:two"),
        ]

        await runtime.close()

    asyncio.run(run())


def test_channel_polling_runner_persists_offset_and_skips_processed_events() -> None:
    async def run() -> None:
        provider = FakePollingProvider()
        channel = FakePollingChannel()
        state_store = InMemoryBotPollingStateStore()
        await state_store.save_offset("telegram", 1000)
        await state_store.mark_event_processed("telegram", "1000")
        runtime = await _build_runtime(
            provider,
            channel,
            polling_state_store=state_store,
        )
        runner = ChannelPollingRunner(
            runtime=runtime,
            channel_id="telegram",
            provider_id="provider-1",
            model="chat-model",
            interval_seconds=0,
            timeout_seconds=30,
            allowed_updates=["message"],
        )

        processed = await runner.run_once()

        assert processed == 1
        assert channel.poll_requests[0]["offset"] == 1000
        assert runner.offset == 1002
        assert await state_store.get_offset("telegram") == 1002
        assert await state_store.is_event_processed("telegram", "1000") is True
        assert await state_store.is_event_processed("telegram", "1001") is True
        assert [request.messages[-1].content for request in provider.requests] == [
            _content("two"),
        ]
        assert [
            action.message.content for action in channel.actions if action.message
        ] == [
            _content("reply:two"),
        ]

        await runtime.close()

    asyncio.run(run())


def test_channel_polling_runner_advances_offset_after_poison_event() -> None:
    async def run() -> None:
        provider = FakePollingProvider()
        channel = FailingFirstSendPollingChannel()
        state_store = InMemoryBotPollingStateStore()
        runtime = await _build_runtime(
            provider,
            channel,
            polling_state_store=state_store,
        )
        runner = ChannelPollingRunner(
            runtime=runtime,
            channel_id="telegram",
            provider_id="provider-1",
            model="chat-model",
            interval_seconds=0,
            timeout_seconds=30,
            allowed_updates=["message"],
        )

        processed = await runner.run_once()

        assert processed == 1
        assert runner.offset == 1002
        assert await state_store.get_offset("telegram") == 1002
        assert await state_store.is_event_processed("telegram", "1000") is True
        assert await state_store.is_event_processed("telegram", "1001") is True
        assert [request.messages[-1].content for request in provider.requests] == [
            _content("one"),
            _content("two"),
        ]
        assert [
            action.message.content for action in channel.actions if action.message
        ] == [
            _content("reply:two"),
        ]

        await runtime.close()

    asyncio.run(run())


def test_channel_polling_runner_uses_persisted_state_after_restart(tmp_path) -> None:
    async def run() -> None:
        database_path = tmp_path / "polling.db"
        first_store = await create_sqlite_bot_polling_state_store(database_path)
        first_provider = FakePollingProvider()
        first_channel = FakePollingChannel()
        first_runtime = await _build_runtime(
            first_provider,
            first_channel,
            polling_state_store=first_store,
        )
        first_runner = ChannelPollingRunner(
            runtime=first_runtime,
            channel_id="telegram",
            provider_id="provider-1",
            model="chat-model",
            interval_seconds=0,
            timeout_seconds=30,
            allowed_updates=["message"],
        )

        assert await first_runner.run_once() == 2
        await first_runtime.close()

        second_store = await create_sqlite_bot_polling_state_store(database_path)
        second_provider = FakePollingProvider()
        second_channel = FakePollingChannel()
        second_runtime = await _build_runtime(
            second_provider,
            second_channel,
            polling_state_store=second_store,
        )
        second_runner = ChannelPollingRunner(
            runtime=second_runtime,
            channel_id="telegram",
            provider_id="provider-1",
            model="chat-model",
            interval_seconds=0,
            timeout_seconds=30,
            allowed_updates=["message"],
        )

        assert await second_runner.run_once() == 0
        assert second_channel.poll_requests[0]["offset"] == 1002
        assert second_provider.requests == []
        assert second_channel.actions == []
        await second_runtime.close()

    asyncio.run(run())


def test_channel_polling_runner_reports_missing_registry_and_poller() -> None:
    async def run() -> None:
        no_registry_runner = ChannelPollingRunner(
            runtime=SimpleNamespace(
                bot_channel_registry=None,
                bot_polling_state_store=None,
            ),
            channel_id="telegram",
            provider_id="provider-1",
            model="chat-model",
            interval_seconds=0,
        )

        with pytest.raises(RuntimeError, match="registry is not set"):
            await no_registry_runner.run_once()

        registry = BotChannelRegistry()
        registry.register(
            BotChannelDefinition(channel_id="telegram", name="Telegram"),
            object(),
        )
        missing_poller_runner = ChannelPollingRunner(
            runtime=SimpleNamespace(
                bot_channel_registry=registry,
                bot_polling_state_store=None,
            ),
            channel_id="telegram",
            provider_id="provider-1",
            model="chat-model",
            interval_seconds=0,
        )

        with pytest.raises(RuntimeError, match="does not support polling"):
            await missing_poller_runner.run_once()

    asyncio.run(run())


def test_channel_polling_runner_non_numeric_events_do_not_advance_offset() -> None:
    async def run() -> None:
        provider = FakePollingProvider()
        channel = FakePollingChannel()
        channel.event_batches = [[_event("abc", "one")]]
        state_store = InMemoryBotPollingStateStore()
        runtime = await _build_runtime(
            provider,
            channel,
            polling_state_store=state_store,
        )
        runner = ChannelPollingRunner(
            runtime=runtime,
            channel_id="telegram",
            provider_id="provider-1",
            model="chat-model",
            interval_seconds=0,
        )

        processed = await runner.run_once()

        assert processed == 1
        assert runner.offset is None
        assert await state_store.get_offset("telegram") is None
        assert await state_store.is_event_processed("telegram", "abc") is True
        await runtime.close()

    asyncio.run(run())


def test_channel_polling_runner_start_is_idempotent_and_stop_cancels() -> None:
    async def run() -> None:
        provider = FakePollingProvider()
        channel = FakePollingChannel()
        channel.event_batches = [[]]
        runtime = await _build_runtime(provider, channel)
        runner = ChannelPollingRunner(
            runtime=runtime,
            channel_id="telegram",
            provider_id="provider-1",
            model="chat-model",
            interval_seconds=10,
        )

        runner.start()
        first_task = runner._task
        assert runner.is_running is True

        runner.start()
        assert runner._task is first_task

        await runner.stop()

        assert runner.is_running is False
        assert runner._task is None
        await runtime.close()

    asyncio.run(run())


def test_channel_polling_runner_run_forever_logs_iteration_failures() -> None:
    class FailingPollChannel(FakePollingChannel):
        async def poll_events(self, **kwargs) -> list[BotEvent]:
            raise RuntimeError("poll failed")

    async def run() -> None:
        provider = FakePollingProvider()
        channel = FailingPollChannel()
        runtime = await _build_runtime(provider, channel)
        runner = ChannelPollingRunner(
            runtime=runtime,
            channel_id="telegram",
            provider_id="provider-1",
            model="chat-model",
            interval_seconds=0.01,
        )

        task = asyncio.create_task(runner.run_forever())
        await asyncio.sleep(0.03)
        await runner.stop()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        await runtime.close()

    asyncio.run(run())
