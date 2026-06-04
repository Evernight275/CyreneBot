from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from contextlib import suppress
from pathlib import Path
from types import ModuleType

import pytest

from cyreneAI.api import PluginTestClient
from cyreneAI.api.cli import (
    PluginCheckError,
    PluginInitError,
    check_plugin_project,
    generate_plugin_documentation,
    init_plugin_project,
    main,
    sign_plugin_project,
)


def test_init_plugin_project_creates_minimal_runnable_plugin(tmp_path: Path) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin", author="Tester")

    manifest = json.loads((project_path / "plugin.json").read_text("utf-8"))
    assert manifest == {
        "plugin_id": "my_plugin",
        "name": "My Plugin",
        "version": "0.1.0",
        "description": "A CyreneAI plugin.",
        "entrypoint": "main.py",
        "author": "Tester",
        "license": "MIT",
        "keywords": [],
        "capabilities": ["bot_command"],
        "permissions": [],
        "metadata": {
            "isolation": {
                "mode": "in_process",
            },
        },
    }
    assert (project_path / "pyproject.toml").is_file()
    assert (project_path / "tests" / "test_plugin.py").is_file()

    plugin_module = _load_generated_main(project_path)

    async def run() -> None:
        client = PluginTestClient(plugin_module.plugin)
        result = await client.command("/hello Cyrene")

        assert result.has_text("Hello, Cyrene!")

    asyncio.run(run())


def test_init_plugin_project_refuses_to_overwrite_existing_files(
    tmp_path: Path,
) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")

    with pytest.raises(PluginInitError):
        init_plugin_project(project_path)


def test_init_plugin_project_can_force_overwrite(tmp_path: Path) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")
    (project_path / "main.py").write_text("broken", encoding="utf-8")

    init_plugin_project(project_path, force=True)

    assert "CyreneBot" in (project_path / "main.py").read_text("utf-8")


def test_cli_init_command_reports_created_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_path = tmp_path / "cli_plugin"

    exit_code = main(["init", str(project_path), "--plugin-id", "demo.cli"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"Initialized CyreneAI plugin at {project_path}" in captured.out
    assert (
        json.loads((project_path / "plugin.json").read_text("utf-8"))["plugin_id"]
        == "demo.cli"
    )


def test_cli_init_command_defaults_to_current_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "same_level_plugin"
    project_path.mkdir()
    monkeypatch.chdir(project_path)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"Initialized CyreneAI plugin at {Path('.')}" in captured.out
    assert (
        json.loads((project_path / "plugin.json").read_text("utf-8"))["plugin_id"]
        == "same_level_plugin"
    )


def test_cli_init_command_returns_error_for_existing_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")

    exit_code = main(["init", str(project_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "target files already exist" in captured.err


def test_init_plugin_project_supports_templates(tmp_path: Path) -> None:
    expected = {
        "basic": (["bot_command"], []),
        "storage": (["bot_command"], ["storage"]),
        "task": (["bot_command", "task"], ["task"]),
        "event": (["event"], []),
        "proactive": (
            ["bot_command", "event", "task"],
            ["storage", "task", "message_send"],
        ),
        "llm": (["bot_command"], ["llm"]),
    }

    for template, (capabilities, permissions) in expected.items():
        project_path = init_plugin_project(
            tmp_path / template,
            template=template,
        )
        manifest = json.loads((project_path / "plugin.json").read_text("utf-8"))

        assert manifest["capabilities"] == capabilities
        assert manifest["permissions"] == permissions
        check_plugin_project(project_path)


def test_check_plugin_project_accepts_generated_plugin(tmp_path: Path) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")

    report = check_plugin_project(project_path)

    assert report.project_path == project_path
    assert report.manifest.plugin_id == "my_plugin"
    assert report.warnings == (
        "plugin has no .cyreneai-plugin-signature.json signature file",
    )


def test_sign_plugin_project_makes_check_signature_clean(tmp_path: Path) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")

    signature_path = sign_plugin_project(project_path, signed_by="tester")
    report = check_plugin_project(project_path)

    assert signature_path.name == ".cyreneai-plugin-signature.json"
    assert report.warnings == ()


def test_generate_plugin_documentation_outputs_markdown(tmp_path: Path) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")

    content = generate_plugin_documentation(project_path)

    assert "# My Plugin" in content
    assert "## Commands" in content
    assert "### `/hello`" in content
    assert "| `name` | positional | `str` | no | `world` |  |" in content


def test_generate_plugin_documentation_outputs_json(tmp_path: Path) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin", template="task")

    payload = json.loads(
        generate_plugin_documentation(project_path, output_format="json")
    )

    assert payload["plugin"]["plugin_id"] == "my_plugin"
    assert payload["tasks"][0]["name"] == "cleanup"


def test_cli_docs_command_writes_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")
    output_path = tmp_path / "PLUGIN_DOCS.md"

    exit_code = main(["docs", str(project_path), "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert "### `/hello`" in output_path.read_text("utf-8")


def test_cli_check_command_reports_checked_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")

    exit_code = main(["check", str(project_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"Checked CyreneAI plugin my_plugin at {project_path}" in captured.out


def test_check_plugin_project_rejects_missing_capability(tmp_path: Path) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")
    manifest_path = project_path / "plugin.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["capabilities"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PluginCheckError, match="missing capabilities: bot_command"):
        check_plugin_project(project_path)


def test_check_plugin_project_rejects_missing_permission(tmp_path: Path) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")
    (project_path / "main.py").write_text(
        "\n".join(
            [
                "from cyreneAI.api import CyreneBot, Depends",
                "",
                "plugin = CyreneBot()",
                "",
                "@plugin.command",
                "async def asset(assets=Depends('assets')):",
                "    return await assets.read_text('prompt.txt')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PluginCheckError, match="setup failed"):
        check_plugin_project(project_path)


def test_cli_check_command_returns_error_for_invalid_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["check", str(tmp_path / "missing")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "does not exist" in captured.err


def _load_generated_main(project_path: Path) -> ModuleType:
    module_name = "_generated_cyrene_plugin_main"
    spec = importlib.util.spec_from_file_location(module_name, project_path / "main.py")
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(project_path))
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
        with suppress(ValueError):
            sys.path.remove(str(project_path))
    return module
