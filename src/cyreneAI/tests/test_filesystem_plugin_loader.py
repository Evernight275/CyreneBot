from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest

from cyreneAI.api.cli import sign_plugin_project
from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.core.errors.plugin import PluginConfigurationError, PluginInputError
from cyreneAI.core.schema.bot import BotCommand, BotEvent, BotEventType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import PluginCommandRequest
from cyreneAI.infra.adapters.plugins.filesystem import (
    FileSystemPluginAssets,
    FileSystemPluginLoader,
)


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
        dedent('''
            from cyreneAI.api import CyreneBot, text

            plugin = CyreneBot()

            @plugin.command("/hello", aliases=["hi"])
            async def hello(request, ctx):
                """Say hello."""
                name = request.command.args_text or "world"
                return text(request, f"Hello, {name}!")
            '''),
        encoding="utf-8",
    )


@dataclass(frozen=True)
class _FakePluginPythonEnvironment:
    env_path: Path
    site_paths: tuple[Path, ...]
    metadata: dict


class _FakePluginPythonEnvironmentManager:
    def __init__(self, site_path: Path) -> None:
        self.site_path = site_path
        self.calls = []

    def ensure(self, *, project_path, manifest, content_hash):
        self.calls.append(
            {
                "project_path": project_path,
                "plugin_id": manifest.plugin_id,
                "content_hash": content_hash,
                "dependencies": list(manifest.python_dependencies),
            }
        )
        if not manifest.python_dependencies:
            return None
        return _FakePluginPythonEnvironment(
            env_path=self.site_path / ".venv",
            site_paths=(self.site_path,),
            metadata={
                "created": True,
                "environment_key": "fake-env-key",
            },
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
            source = runtime.plugin_manager.get_plugin_source("demo.hello")
            assert source.source_type == "filesystem"
            assert source.version == "0.1.0"
            assert source.signature_status == "unsigned"
            assert source.isolation_mode == "in_process"
            assert [
                command.name for command in runtime.plugin_manager.list_commands()
            ] == ["hello"]

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


def test_filesystem_plugin_loader_uses_python_environment_import_paths(
    tmp_path,
) -> None:
    plugin_path = tmp_path / "demo_dep"
    dependency_path = tmp_path / "dependency_site"
    plugin_path.mkdir()
    dependency_path.mkdir()
    (dependency_path / "demo_dependency.py").write_text(
        "VALUE = 'from managed env'\n",
        encoding="utf-8",
    )
    (plugin_path / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "demo.dep",
                "name": "Dependency Demo",
                "description": "Uses a managed dependency path.",
                "entrypoint": "main.py",
                "python_dependencies": ["demo-dependency==1.0"],
            }
        ),
        encoding="utf-8",
    )
    (plugin_path / "main.py").write_text(
        dedent("""
            from cyreneAI.api import CyreneBot
            import demo_dependency

            plugin = CyreneBot()
            plugin.plugin_value = demo_dependency.VALUE
            """),
        encoding="utf-8",
    )
    manager = _FakePluginPythonEnvironmentManager(dependency_path)

    plugin = FileSystemPluginLoader(
        plugin_path,
        python_environment_manager=manager,
    ).load()[0]
    source = plugin.__cyreneai_plugin_source__

    assert plugin.plugin_value == "from managed env"
    assert manager.calls[0]["plugin_id"] == "demo.dep"
    assert manager.calls[0]["dependencies"] == ["demo-dependency==1.0"]
    assert source.metadata["python_environment"]["created"] is True
    assert source.metadata["python_environment"]["environment_key"] == "fake-env-key"


def test_filesystem_plugin_loader_reloads_tracked_source(tmp_path) -> None:
    async def run() -> None:
        plugin_path = tmp_path / "demo_hello"
        _write_hello_plugin(plugin_path)

        runtime = await build_cyrene_ai_runtime(
            plugin_loaders=[FileSystemPluginLoader(plugin_path)],
            register_builtin_plugins=False,
        )
        try:
            assert runtime.plugin_host is not None
            manifest = json.loads((plugin_path / "plugin.json").read_text("utf-8"))
            manifest["version"] = "0.2.0"
            (plugin_path / "plugin.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            definition = runtime.plugin_host.reload("demo.hello")
            source = runtime.plugin_manager.get_plugin_source("demo.hello")

            assert definition.version == "0.2.0"
            assert source.version == "0.2.0"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_filesystem_plugin_loader_records_valid_signature(tmp_path) -> None:
    plugin_path = tmp_path / "demo_hello"
    _write_hello_plugin(plugin_path)
    sign_plugin_project(plugin_path, signed_by="tester")

    plugin = FileSystemPluginLoader(plugin_path).load()[0]
    source = plugin.__cyreneai_plugin_source__

    assert source.signature_status == "valid"
    assert source.signed_by == "tester"


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


def test_filesystem_plugin_loader_registers_project_assets(tmp_path) -> None:
    async def run() -> None:
        plugin_path = tmp_path / "demo_hello"
        _write_hello_plugin(plugin_path)
        (plugin_path / "assets" / "prompts").mkdir(parents=True)
        (plugin_path / "assets" / "prompts" / "hello.txt").write_text(
            "Hello assets.",
            encoding="utf-8",
        )
        assets = FileSystemPluginAssets()

        FileSystemPluginLoader(plugin_path, plugin_assets=assets).load()

        namespace = assets.namespace("demo.hello")
        assert await namespace.read_text("prompts/hello.txt") == "Hello assets."

    asyncio.run(run())


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


def test_filesystem_plugin_loader_rejects_entrypoint_escape(tmp_path) -> None:
    plugin_path = tmp_path / "escaped"
    plugin_path.mkdir()
    outside_path = tmp_path / "outside.py"
    outside_path.write_text("plugin = object()\n", encoding="utf-8")
    (plugin_path / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "demo.escaped",
                "name": "Escaped",
                "description": "Escaped plugin entrypoint.",
                "entrypoint": "../outside.py",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PluginConfigurationError):
        FileSystemPluginLoader(plugin_path).load()
