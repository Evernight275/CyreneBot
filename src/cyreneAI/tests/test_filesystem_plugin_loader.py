from __future__ import annotations

import asyncio
import json
from textwrap import dedent

import pytest

from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.errors.plugin import PluginConfigurationError, PluginInputError
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import PluginCommandRequest
from cyreneAI.infra.adapters.plugins.filesystem import FileSystemPluginLoader


def _event() -> BotEvent:
    return BotEvent(
        event_id="event-1",
        event_type=BotEventType.COMMAND,
        channel_id="memory",
        session_id="memory:user-1",
        user_id="user-1",
        message=BotMessage(
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text="/hello Cyrene",
                )
            ]
        ),
    )


def _write_hello_plugin(path) -> None:
    path.mkdir()
    (path / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "demo.hello",
                "name": "Hello",
                "version": "0.1.0",
                "description": "Hello command plugin.",
                "entrypoint": "main.py",
                "author": "Cyrene",
                "license": "MIT",
                "keywords": ["demo", "hello"],
                "capabilities": ["bot_command"],
                "permissions": [],
            }
        ),
        encoding="utf-8",
    )
    (path / "main.py").write_text(
        dedent(
            '''
            from cyreneAI.plugin_api import CyreneBot, text

            plugin = CyreneBot()

            @plugin.command("/hello", aliases=["hi"])
            async def hello(request, ctx):
                """Say hello."""
                name = request.command.args_text or "world"
                return text(request, f"Hello, {name}!")
            '''
        ),
        encoding="utf-8",
    )


def test_filesystem_plugin_loader_loads_plugin_json_project(tmp_path) -> None:
    async def run() -> None:
        plugin_path = tmp_path / "demo_hello"
        _write_hello_plugin(plugin_path)

        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[FileSystemPluginLoader(plugin_path)],
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_manager is not None
            plugins = runtime.plugin_manager.list_plugins()
            assert plugins[0].plugin_id == "demo.hello"
            assert plugins[0].author == "Cyrene"
            assert plugins[0].license == "MIT"
            assert plugins[0].keywords == ["demo", "hello"]
            assert [command.name for command in runtime.plugin_manager.list_commands()] == [
                "hello"
            ]

            result = await runtime.plugin_manager.execute_command(
                PluginCommandRequest(
                    command=BotCommand(
                        raw_text="/hello Cyrene",
                        name="hello",
                        args=("Cyrene",),
                        args_text="Cyrene",
                    ),
                    event=_event(),
                )
            )

            assert result.actions[0].message is not None
            assert result.actions[0].message.content[0].text == "Hello, Cyrene!"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_filesystem_plugin_loader_loads_plugins_from_directory(tmp_path) -> None:
    first = tmp_path / "01_hello"
    second = tmp_path / "02_hi"
    _write_hello_plugin(first)
    _write_hello_plugin(second)
    payload = json.loads((second / "plugin.json").read_text(encoding="utf-8"))
    payload["plugin_id"] = "demo.hi"
    payload["name"] = "Hi"
    (second / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")

    plugins = FileSystemPluginLoader(tmp_path).load()

    assert [plugin.manifest.plugin_id for plugin in plugins] == [
        "demo.hello",
        "demo.hi",
    ]


def test_filesystem_plugin_loader_rejects_missing_path(tmp_path) -> None:
    with pytest.raises(PluginConfigurationError):
        FileSystemPluginLoader(tmp_path / "missing").load()


def test_filesystem_plugin_loader_rejects_invalid_manifest_json(tmp_path) -> None:
    plugin_path = tmp_path / "bad"
    plugin_path.mkdir()
    (plugin_path / "plugin.json").write_text("{", encoding="utf-8")

    with pytest.raises(PluginInputError):
        FileSystemPluginLoader(plugin_path).load()


def test_filesystem_plugin_loader_requires_plugin_object(tmp_path) -> None:
    plugin_path = tmp_path / "missing_plugin"
    plugin_path.mkdir()
    (plugin_path / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "demo.missing",
                "name": "Missing",
                "description": "Missing plugin object.",
                "entrypoint": "main.py",
            }
        ),
        encoding="utf-8",
    )
    (plugin_path / "main.py").write_text("value = 1\n", encoding="utf-8")

    with pytest.raises(PluginConfigurationError):
        FileSystemPluginLoader(plugin_path).load()
