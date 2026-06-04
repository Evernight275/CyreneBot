from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from cyreneAI.core.errors.tool import ToolConfigurationError, ToolExecutionError
from cyreneAI.core.schema.tool import ToolCall
from cyreneAI.infra.adapters.tools.http.executor import HttpToolExecutor


async def _run_http_tool() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload == {
            "id": "call-1",
            "name": "lookup",
            "arguments": {"key": "answer"},
        }
        return httpx.Response(
            200,
            json={
                "call_id": "attacker-call",
                "name": "attacker-tool",
                "content": "value:answer",
                "metadata": {"source": "mock"},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://tools.local",
    )
    try:
        executor = HttpToolExecutor(
            "https://tools.local/lookup",
            client=client,
        )
        result = await executor.execute(
            ToolCall(
                id="call-1",
                name="lookup",
                arguments='{"key":"answer"}',
            )
        )
    finally:
        await client.aclose()

    assert result.call_id == "call-1"
    assert result.name == "lookup"
    assert result.content == "value:answer"
    assert result.metadata == {"source": "mock"}


def test_http_tool_executor_posts_tool_payload_and_maps_result() -> None:
    asyncio.run(_run_http_tool())


def test_http_tool_executor_rejects_invalid_url() -> None:
    with pytest.raises(ToolConfigurationError):
        HttpToolExecutor("file:///tmp/tool")

    with pytest.raises(ToolConfigurationError):
        HttpToolExecutor("/lookup")


async def _run_http_tool_with_oversized_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="abcdef")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://tools.local",
    )
    try:
        executor = HttpToolExecutor(
            "https://tools.local/lookup",
            client=client,
            max_response_bytes=5,
        )
        await executor.execute(
            ToolCall(
                id="call-1",
                name="lookup",
                arguments="{}",
            )
        )
    finally:
        await client.aclose()


def test_http_tool_executor_rejects_oversized_response() -> None:
    with pytest.raises(ToolExecutionError):
        asyncio.run(_run_http_tool_with_oversized_response())


async def _run_http_tool_with_server_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://tools.local",
    )
    try:
        executor = HttpToolExecutor(
            "https://tools.local/lookup",
            client=client,
        )
        await executor.execute(
            ToolCall(
                id="call-1",
                name="lookup",
                arguments="{}",
            )
        )
    finally:
        await client.aclose()


def test_http_tool_executor_translates_http_errors() -> None:
    with pytest.raises(ToolExecutionError):
        asyncio.run(_run_http_tool_with_server_error())


async def _run_http_tool_with_text_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="plain value",
            headers={"content-type": "text/plain"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://tools.local",
    )
    try:
        executor = HttpToolExecutor(
            "https://tools.local/lookup",
            client=client,
        )
        result = await executor.execute(
            ToolCall(
                id="call-1",
                name="lookup",
                arguments="{}",
            )
        )
    finally:
        await client.aclose()

    assert result.call_id == "call-1"
    assert result.name == "lookup"
    assert result.content == "plain value"


def test_http_tool_executor_maps_text_response() -> None:
    asyncio.run(_run_http_tool_with_text_response())


async def _run_http_tool_with_transport_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://tools.local",
    )
    try:
        executor = HttpToolExecutor(
            "https://tools.local/lookup",
            client=client,
        )
        await executor.execute(
            ToolCall(
                id="call-1",
                name="lookup",
                arguments="{}",
            )
        )
    finally:
        await client.aclose()


def test_http_tool_executor_translates_transport_errors() -> None:
    with pytest.raises(ToolExecutionError) as caught:
        asyncio.run(_run_http_tool_with_transport_error())

    assert isinstance(caught.value.cause, httpx.ConnectError)
