from __future__ import annotations

import pytest

from cyreneAI.core.errors.plugin import PluginConfigurationError
from cyreneAI.core.schema.plugin import PluginManifest
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
