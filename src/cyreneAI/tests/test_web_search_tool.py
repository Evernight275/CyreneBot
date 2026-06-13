from __future__ import annotations

import asyncio
import json
from urllib.request import Request

import pytest

from cyreneAI.core.errors.tool import ToolExecutionError, ToolInputError
from cyreneAI.core.schema.tool import ToolCall
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.infra.adapters.tools import web_search


def _call(arguments: dict) -> ToolCall:
    return ToolCall(
        id="call-web-search",
        name="web_search",
        arguments=json.dumps(arguments),
    )


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self._data[:size]


def test_web_search_tool_builds_template_url_and_compacts_json(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, *, timeout: float) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["accept"] = request.get_header("Accept")
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return _FakeResponse(b'{"z": 2, "a": 1}')

    async def run() -> None:
        monkeypatch.setattr(web_search, "urlopen", fake_urlopen)
        registry = ToolRegistry()
        web_search.register_web_search_tool(
            registry,
            url_template="https://search.local/search?q={query}&limit={max_results}",
            api_key="secret",
            api_key_header="X-API-Key",
            timeout_seconds=3.5,
        )
        manager = ToolManager(registry)

        result = await manager.execute(
            _call({"query": "hello world", "max_results": 99})
        )

        assert result.success is True
        assert json.loads(result.content or "{}") == {"a": 1, "z": 2}
        assert result.metadata["source"] == "web_search"
        assert result.metadata["url"] == captured["url"]

    asyncio.run(run())

    assert captured == {
        "url": "https://search.local/search?q=hello+world&limit=20",
        "accept": "application/json,text/plain",
        "headers": {
            "Accept": "application/json,text/plain",
            "X-api-key": "secret",
        },
        "timeout": 3.5,
    }


def test_web_search_tool_adds_default_query_parameters(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_urlopen(request: Request, *, timeout: float) -> _FakeResponse:
        captured["url"] = request.full_url
        return _FakeResponse(b"plain text")

    async def run() -> None:
        monkeypatch.setattr(web_search, "urlopen", fake_urlopen)
        registry = ToolRegistry()
        web_search.register_web_search_tool(
            registry,
            url_template="https://search.local/search?lang=en",
        )
        manager = ToolManager(registry)

        result = await manager.execute(_call({"query": "cyrene ai"}))

        assert result.content == "plain text"

    asyncio.run(run())

    assert captured["url"] == "https://search.local/search?lang=en&q=cyrene+ai&limit=10"


@pytest.mark.parametrize(
    "arguments, error_type, message",
    [
        ({}, ToolInputError, "arguments.query is required"),
        ({"query": "   "}, ToolExecutionError, "query is required"),
        (
            {"query": "cyrene", "max_results": 0},
            ToolExecutionError,
            "max_results must be",
        ),
        (
            {"query": "cyrene", "max_results": True},
            ToolInputError,
            "arguments.max_results has invalid type",
        ),
    ],
)
def test_web_search_tool_validates_arguments(arguments, error_type, message) -> None:
    async def run() -> None:
        registry = ToolRegistry()
        web_search.register_web_search_tool(
            registry,
            url_template="https://search.local/search",
        )
        manager = ToolManager(registry)

        with pytest.raises(error_type, match=message):
            await manager.execute(_call(arguments))

    asyncio.run(run())


def test_web_search_tool_translates_request_failure(monkeypatch) -> None:
    def fake_urlopen(request: Request, *, timeout: float) -> _FakeResponse:
        raise OSError("offline")

    async def run() -> None:
        monkeypatch.setattr(web_search, "urlopen", fake_urlopen)
        registry = ToolRegistry()
        web_search.register_web_search_tool(
            registry,
            url_template="https://search.local/search",
        )
        manager = ToolManager(registry)

        with pytest.raises(ToolExecutionError, match="web_search request failed"):
            await manager.execute(_call({"query": "cyrene"}))

    asyncio.run(run())


def test_web_search_executor_rejects_oversized_response(monkeypatch) -> None:
    def fake_urlopen(request: Request, *, timeout: float) -> _FakeResponse:
        return _FakeResponse(b"abcd")

    async def run() -> None:
        monkeypatch.setattr(web_search, "urlopen", fake_urlopen)
        executor = web_search._WebSearchToolExecutor(
            url_template="https://search.local/search",
            api_key=None,
            api_key_header="Authorization",
            timeout_seconds=1,
            max_bytes=3,
        )

        with pytest.raises(ToolExecutionError, match="maximum size"):
            await executor.execute(_call({"query": "cyrene"}))

    asyncio.run(run())
