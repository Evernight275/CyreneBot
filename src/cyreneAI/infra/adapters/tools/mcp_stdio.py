from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, cast

from cyreneAI.core.errors.tool import ToolConfigurationError, ToolExecutionError
from cyreneAI.core.schema.tool import (
    MCPStdioServerConfig,
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.tool.tool_protocol import ToolRegistryProtocol
from cyreneAI.infra.adapters.tools.common import parse_tool_arguments


async def register_mcp_stdio_tools(
    registry: ToolRegistryProtocol,
    configs: list[MCPStdioServerConfig],
) -> None:
    """
    Register tools exposed by configured MCP stdio servers.
    """
    for config in configs:
        if not config.enabled:
            continue
        tools = await _list_mcp_tools(config)
        for tool in tools:
            remote_name = _required_string(tool.get("name"), "MCP tool name")
            local_name = f"mcp_{_safe_name(config.name)}_{_safe_name(remote_name)}"
            if registry.exists(local_name):
                continue
            description = tool.get("description")
            input_schema = tool.get("inputSchema") or tool.get("input_schema")
            registry.register(
                ToolDefinition(
                    name=local_name,
                    description=(
                        description
                        if isinstance(description, str) and description.strip()
                        else f"MCP tool {remote_name} from {config.name}."
                    ),
                    parameters_schema=(
                        cast(dict[str, Any], input_schema)
                        if isinstance(input_schema, dict)
                        else None
                    ),
                    safety_profile=ToolSafetyProfile(
                        risk_level=ToolRiskLevel.NETWORK,
                        permissions=[ToolPermission.NETWORK, ToolPermission.SUBPROCESS],
                        sandbox_required=False,
                        timeout_seconds=max(1, int(config.timeout_seconds)),
                        max_output_chars=65536,
                    ),
                    metadata={
                        "source": "mcp",
                        "mcp_server": config.name,
                        "mcp_tool_name": remote_name,
                    },
                ),
                _MCPStdioToolExecutor(config, remote_name),
            )


class _MCPStdioToolExecutor:
    def __init__(self, config: MCPStdioServerConfig, remote_name: str) -> None:
        self._config = config
        self._remote_name = remote_name

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = parse_tool_arguments(call.arguments)
        result = await _call_mcp_tool(
            self._config,
            name=self._remote_name,
            arguments=arguments,
        )
        is_error = bool(result.get("isError") or result.get("is_error"))
        content = _mcp_content_to_text(result.get("content"))
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=content,
            success=not is_error,
            error=content if is_error else None,
            metadata={
                "source": "mcp",
                "mcp_server": self._config.name,
                "mcp_tool_name": self._remote_name,
            },
        )


async def _list_mcp_tools(config: MCPStdioServerConfig) -> list[dict[str, Any]]:
    async with _MCPStdioSession(config) as session:
        await session.initialize()
        response = await session.request("tools/list", {})
    tools = response.get("tools")
    if not isinstance(tools, list):
        raise ToolConfigurationError(f"MCP server {config.name} returned invalid tools")
    return [cast(dict[str, Any], tool) for tool in tools if isinstance(tool, dict)]


async def _call_mcp_tool(
    config: MCPStdioServerConfig,
    *,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    async with _MCPStdioSession(config) as session:
        await session.initialize()
        return await session.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )


class _MCPStdioSession:
    def __init__(self, config: MCPStdioServerConfig) -> None:
        self._config = config
        self._request_id = 0
        self._process: asyncio.subprocess.Process | None = None

    async def __aenter__(self) -> "_MCPStdioSession":
        command = [self._config.command, *self._config.args]
        if not self._config.command:
            raise ToolConfigurationError("MCP stdio command cannot be empty")
        environment = os.environ.copy()
        environment.update(self._config.env)
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
        except OSError as exc:
            raise ToolConfigurationError(
                f"MCP server {self._config.name} failed to start",
                cause=exc,
            ) from exc
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        process = self._process
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def initialize(self) -> None:
        await self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "cyreneAI",
                    "version": "0.1.0",
                },
            },
        )
        await self.notify("notifications/initialized", {})

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write_message(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        await self._write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        while True:
            message = await asyncio.wait_for(
                self._read_message(),
                timeout=self._config.timeout_seconds,
            )
            if message.get("id") != request_id:
                continue
            error = message.get("error")
            if error is not None:
                raise ToolExecutionError(
                    f"MCP server {self._config.name} request {method} failed: {error}"
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise ToolExecutionError(
                    f"MCP server {self._config.name} request {method} returned invalid result"
                )
            return cast(dict[str, Any], result)

    async def _write_message(self, payload: dict[str, Any]) -> None:
        process = self._require_process()
        assert process.stdin is not None
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        process.stdin.write(header + body)
        await process.stdin.drain()

    async def _read_message(self) -> dict[str, Any]:
        process = self._require_process()
        assert process.stdout is not None
        headers: dict[str, str] = {}
        while True:
            line = await process.stdout.readline()
            if not line:
                raise ToolExecutionError(f"MCP server {self._config.name} closed stdout")
            if line in {b"\r\n", b"\n"}:
                break
            text = line.decode("ascii", errors="replace").strip()
            key, separator, value = text.partition(":")
            if separator:
                headers[key.lower()] = value.strip()
        raw_length = headers.get("content-length")
        if raw_length is None or not raw_length.isdigit():
            raise ToolExecutionError("MCP message missing Content-Length")
        body = await process.stdout.readexactly(int(raw_length))
        try:
            parsed = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("MCP message body is not valid JSON", cause=exc) from exc
        if not isinstance(parsed, dict):
            raise ToolExecutionError("MCP message body must be an object")
        return cast(dict[str, Any], parsed)

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise ToolExecutionError("MCP session is not started")
        return self._process


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolConfigurationError(f"{label} must be a non-empty string")
    return value.strip()


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    return safe or "tool"


def _mcp_content_to_text(content: Any) -> str:
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        item_type = item.get("type")
        if item_type == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
        else:
            parts.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
    return "\n".join(parts)


__all__ = ["register_mcp_stdio_tools"]
