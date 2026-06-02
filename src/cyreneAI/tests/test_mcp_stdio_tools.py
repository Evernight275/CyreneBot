from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from cyreneAI.core.schema.tool import MCPStdioServerConfig, ToolCall
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.infra.adapters.tools.mcp_stdio import register_mcp_stdio_tools


def test_mcp_stdio_tools_register_and_execute(tmp_path: Path) -> None:
    server_path = tmp_path / "fake_mcp_server.py"
    server_path.write_text(
        r'''
import json
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\n", b"\r\n"):
            break
        key, _, value = line.decode("ascii").strip().partition(":")
        headers[key.lower()] = value.strip()
    body = sys.stdin.buffer.read(int(headers["content-length"]))
    return json.loads(body.decode("utf-8"))


def write_message(payload):
    body = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body)
    sys.stdout.buffer.flush()


while True:
    message = read_message()
    if message is None:
        break
    if "id" not in message:
        continue
    method = message.get("method")
    if method == "initialize":
        write_message({"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": {}}})
    elif method == "tools/list":
        write_message({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {
                "tools": [{
                    "name": "echo",
                    "description": "Echo text.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                }]
            },
        })
    elif method == "tools/call":
        text = message.get("params", {}).get("arguments", {}).get("text", "")
        write_message({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {"content": [{"type": "text", "text": "echo:" + text}]},
        })
''',
        encoding="utf-8",
    )

    async def run() -> None:
        registry = ToolRegistry()
        await register_mcp_stdio_tools(
            registry,
            [
                MCPStdioServerConfig(
                    name="demo",
                    command=sys.executable,
                    args=[str(server_path)],
                    timeout_seconds=5,
                )
            ],
        )
        assert registry.exists("mcp_demo_echo")

        result = await ToolManager(registry).execute(
            ToolCall(
                id="call-1",
                name="mcp_demo_echo",
                arguments=json.dumps({"text": "hello"}),
            )
        )
        assert result.content == "echo:hello"
        assert result.metadata["mcp_server"] == "demo"

    asyncio.run(run())
