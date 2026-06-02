from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote_plus, urlencode, urlparse, urlunparse, parse_qsl
from urllib.request import Request, urlopen

from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.tool.tool_protocol import ToolRegistryProtocol
from cyreneAI.infra.adapters.tools.common import parse_tool_arguments


def register_web_search_tool(
    registry: ToolRegistryProtocol,
    *,
    url_template: str,
    api_key: str | None = None,
    api_key_header: str = "Authorization",
    timeout_seconds: float = 10.0,
) -> None:
    """
    Register a generic HTTP-backed web search tool.
    """
    definition = ToolDefinition(
        name="web_search",
        description="Search the web using the configured search endpoint.",
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        safety_profile=ToolSafetyProfile(
            risk_level=ToolRiskLevel.NETWORK,
            permissions=[ToolPermission.NETWORK],
            timeout_seconds=max(1, int(timeout_seconds)),
            max_output_chars=65536,
        ),
        metadata={"source": "web_search"},
    )
    if registry.exists(definition.name):
        return
    registry.register(
        definition,
        _WebSearchToolExecutor(
            url_template=url_template,
            api_key=api_key,
            api_key_header=api_key_header,
            timeout_seconds=timeout_seconds,
        ),
    )


class _WebSearchToolExecutor:
    def __init__(
        self,
        *,
        url_template: str,
        api_key: str | None,
        api_key_header: str,
        timeout_seconds: float,
        max_bytes: int = 1_000_000,
    ) -> None:
        self._url_template = url_template
        self._api_key = api_key
        self._api_key_header = api_key_header
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = parse_tool_arguments(call.arguments)
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolExecutionError("query is required")
        max_results = arguments.get("max_results")
        if max_results is not None and (
            not isinstance(max_results, int) or isinstance(max_results, bool) or max_results < 1
        ):
            raise ToolExecutionError("max_results must be a positive integer")

        url = _build_url(
            self._url_template,
            query=query.strip(),
            max_results=min(max_results or 10, 20),
        )
        headers = {"Accept": "application/json,text/plain"}
        if self._api_key:
            headers[self._api_key_header] = self._api_key
        response_text = await asyncio.to_thread(
            self._request_text,
            url,
            headers,
        )
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=response_text,
            metadata={"url": url, "source": "web_search"},
        )

    def _request_text(self, url: str, headers: dict[str, str]) -> str:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                data = response.read(self._max_bytes + 1)
        except OSError as exc:
            raise ToolExecutionError("web_search request failed", cause=exc) from exc
        if len(data) > self._max_bytes:
            raise ToolExecutionError("web_search response exceeded maximum size")
        text = data.decode("utf-8", errors="replace")
        return _compact_json_text(text)


def _build_url(url_template: str, *, query: str, max_results: int) -> str:
    if "{query}" in url_template or "{max_results}" in url_template:
        return url_template.format(
            query=quote_plus(query),
            raw_query=query,
            max_results=max_results,
        )

    parsed = urlparse(url_template)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_items.setdefault("q", query)
    query_items.setdefault("limit", str(max_results))
    return urlunparse(
        parsed._replace(query=urlencode(query_items))
    )


def _compact_json_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True)


__all__ = ["register_web_search_tool"]
