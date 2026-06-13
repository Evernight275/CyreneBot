from __future__ import annotations

import json
import subprocess

import pytest

from cyreneAI.core.errors.plugin import PluginConfigurationError
from cyreneAI.core.schema.plugin import PluginManifest
from cyreneAI.infra.adapters.plugins import python_env
from cyreneAI.infra.adapters.plugins.python_env import PluginPythonEnvironmentManager


def test_plugin_python_environment_manager_skips_plugins_without_dependencies(
    tmp_path,
) -> None:
    manager = PluginPythonEnvironmentManager(tmp_path / "venvs")
    manifest = PluginManifest(
        plugin_id="demo.no_deps",
        name="No Deps",
        description="No dependencies.",
        entrypoint="main.py",
    )

    environment = manager.ensure(
        project_path=tmp_path,
        manifest=manifest,
        content_hash="hash",
    )

    assert environment is None
    assert not (tmp_path / "venvs").exists()


def test_plugin_python_environment_manager_requires_auto_install_for_missing_env(
    tmp_path,
) -> None:
    manager = PluginPythonEnvironmentManager(
        tmp_path / "venvs",
        auto_install=False,
    )
    manifest = PluginManifest(
        plugin_id="demo.deps",
        name="Deps",
        description="Has dependencies.",
        entrypoint="main.py",
        python_dependencies=["numpy>=2"],
    )

    with pytest.raises(PluginConfigurationError):
        manager.ensure(
            project_path=tmp_path,
            manifest=manifest,
            content_hash="hash",
        )


def test_plugin_python_environment_manager_creates_marker_and_reuses_env(
    tmp_path,
    monkeypatch,
) -> None:
    created_envs: list[str] = []

    def fake_create_environment(
        self: PluginPythonEnvironmentManager,
        *,
        env_path,
        dependencies,
        project_path,
        manifest,
    ) -> None:
        created_envs.append(str(env_path))
        env_path.mkdir(parents=True)

    def fake_site_paths(env_path):
        return (env_path / "site-packages",)

    monkeypatch.setattr(
        PluginPythonEnvironmentManager,
        "_create_environment",
        fake_create_environment,
    )
    monkeypatch.setattr(python_env, "_site_paths", fake_site_paths)

    manager = PluginPythonEnvironmentManager(tmp_path / "venvs")
    manifest = PluginManifest(
        plugin_id="demo.deps/unsafe",
        name="Deps",
        description="Has dependencies.",
        entrypoint="main.py",
        python_dependencies=[" requests>=2 ", ""],
    )

    first = manager.ensure(
        project_path=tmp_path,
        manifest=manifest,
        content_hash="hash",
    )
    second = manager.ensure(
        project_path=tmp_path,
        manifest=manifest,
        content_hash="hash",
    )

    assert first is not None
    assert second is not None
    assert first.metadata["created"] is True
    assert second.metadata["created"] is False
    assert first.metadata["python_dependencies"] == ["requests>=2"]
    assert first.env_path == second.env_path
    assert first.site_paths == (first.env_path / "site-packages",)
    assert created_envs == [str(first.env_path)]

    marker = first.env_path / ".cyreneai-plugin-env.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["plugin_id"] == (
        "demo.deps/unsafe"
    )


def test_plugin_python_environment_manager_recreates_invalid_marker(
    tmp_path,
    monkeypatch,
) -> None:
    create_count = 0

    def fake_create_environment(
        self: PluginPythonEnvironmentManager,
        *,
        env_path,
        dependencies,
        project_path,
        manifest,
    ) -> None:
        nonlocal create_count
        create_count += 1
        env_path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        PluginPythonEnvironmentManager,
        "_create_environment",
        fake_create_environment,
    )
    monkeypatch.setattr(python_env, "_site_paths", lambda env_path: ())

    manager = PluginPythonEnvironmentManager(tmp_path / "venvs")
    manifest = PluginManifest(
        plugin_id="demo.deps",
        name="Deps",
        description="Has dependencies.",
        entrypoint="main.py",
        python_dependencies=["numpy>=2"],
    )
    metadata = python_env._environment_metadata(
        manifest=manifest,
        content_hash="hash",
        dependencies=["numpy>=2"],
    )
    env_path = manager._environment_path(manifest, metadata)
    env_path.mkdir(parents=True)
    (env_path / ".cyreneai-plugin-env.json").write_text("{broken", encoding="utf-8")

    environment = manager.ensure(
        project_path=tmp_path,
        manifest=manifest,
        content_hash="hash",
    )

    assert environment is not None
    assert environment.metadata["created"] is True
    assert create_count == 1


def test_plugin_python_environment_manager_rejects_env_path_escape(tmp_path) -> None:
    manager = PluginPythonEnvironmentManager(tmp_path / "venvs")

    with pytest.raises(PluginConfigurationError, match="escapes environment root"):
        manager._reset_environment_path(tmp_path / "outside" / ".venv")


def test_plugin_python_environment_site_paths_require_python(tmp_path) -> None:
    with pytest.raises(PluginConfigurationError, match="does not contain python"):
        python_env._site_paths(tmp_path / ".venv")


def test_plugin_python_environment_site_paths_validate_output(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".venv"
    python_path = python_env._environment_python(env_path)
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")

    monkeypatch.setattr(
        python_env,
        "_run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout='{"not": "a list"}',
            stderr="",
        ),
    )

    with pytest.raises(PluginConfigurationError, match="invalid site-packages"):
        python_env._site_paths(env_path)


def test_plugin_python_environment_run_command_translates_failures(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        python_env.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["python"],
            returncode=5,
            stdout="",
            stderr="boom",
        ),
    )

    with pytest.raises(PluginConfigurationError, match="exit code 5: boom"):
        python_env._run_command(
            ["python", "-V"],
            timeout_seconds=1,
            cwd=tmp_path,
            plugin_id="demo",
        )

    def raise_os_error(*args, **kwargs):
        raise OSError("missing")

    monkeypatch.setattr(python_env.subprocess, "run", raise_os_error)

    with pytest.raises(PluginConfigurationError, match="failed to start"):
        python_env._run_command(
            ["python", "-V"],
            timeout_seconds=1,
            cwd=tmp_path,
            plugin_id="demo",
        )
