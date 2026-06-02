from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cyreneAI.core.errors.plugin import PluginConfigurationError
from cyreneAI.core.schema.plugin import PluginManifest


@dataclass(frozen=True, slots=True)
class PluginPythonEnvironment:
    """
    Resolved Python environment for a filesystem plugin.
    """

    env_path: Path
    site_paths: tuple[Path, ...]
    metadata: dict[str, Any]


class PluginPythonEnvironmentManager:
    """
    Creates and reuses per-plugin virtual environments for declared dependencies.
    """

    def __init__(
        self,
        root_path: str | Path,
        *,
        auto_install: bool = True,
        python_executable: str | Path | None = None,
        install_timeout_seconds: float = 300.0,
    ) -> None:
        self._root_path = Path(root_path)
        self._auto_install = auto_install
        self._python_executable = str(python_executable or sys.executable)
        self._install_timeout_seconds = install_timeout_seconds

    def ensure(
        self,
        *,
        project_path: Path,
        manifest: PluginManifest,
        content_hash: str,
    ) -> PluginPythonEnvironment | None:
        dependencies = [
            dependency.strip()
            for dependency in manifest.python_dependencies
            if dependency.strip()
        ]
        if not dependencies:
            return None

        metadata = _environment_metadata(
            manifest=manifest,
            content_hash=content_hash,
            dependencies=dependencies,
        )
        env_path = self._environment_path(manifest, metadata)
        marker_path = env_path / ".cyreneai-plugin-env.json"

        if _marker_matches(marker_path, metadata):
            return PluginPythonEnvironment(
                env_path=env_path,
                site_paths=_site_paths(env_path),
                metadata={
                    **metadata,
                    "created": False,
                },
            )

        if not self._auto_install:
            raise PluginConfigurationError(
                f"Plugin {manifest.plugin_id} requires Python dependencies but "
                "automatic plugin dependency installation is disabled"
            )

        self._create_environment(
            env_path=env_path,
            dependencies=dependencies,
            project_path=project_path,
            manifest=manifest,
        )
        marker_path.write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return PluginPythonEnvironment(
            env_path=env_path,
            site_paths=_site_paths(env_path),
            metadata={
                **metadata,
                "created": True,
            },
        )

    def _environment_path(
        self,
        manifest: PluginManifest,
        metadata: dict[str, Any],
    ) -> Path:
        safe_plugin_id = "".join(
            char if char.isalnum() or char in {"-", "_", "."} else "_"
            for char in manifest.plugin_id
        )
        key = str(metadata["environment_key"])[:16]
        return self._root_path / safe_plugin_id / key / ".venv"

    def _create_environment(
        self,
        *,
        env_path: Path,
        dependencies: list[str],
        project_path: Path,
        manifest: PluginManifest,
    ) -> None:
        self._reset_environment_path(env_path)
        env_path.parent.mkdir(parents=True, exist_ok=True)
        _run_command(
            [
                self._python_executable,
                "-m",
                "venv",
                str(env_path),
            ],
            timeout_seconds=self._install_timeout_seconds,
            cwd=project_path,
            plugin_id=manifest.plugin_id,
        )
        _run_command(
            [
                str(_environment_python(env_path)),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                *dependencies,
            ],
            timeout_seconds=self._install_timeout_seconds,
            cwd=project_path,
            plugin_id=manifest.plugin_id,
        )

    def _reset_environment_path(self, env_path: Path) -> None:
        root = self._root_path.resolve()
        target = env_path.resolve()
        if root != target and not target.is_relative_to(root):
            raise PluginConfigurationError(
                f"Plugin environment path {target} escapes environment root {root}"
            )
        if env_path.exists():
            shutil.rmtree(env_path)


def _environment_metadata(
    *,
    manifest: PluginManifest,
    content_hash: str,
    dependencies: list[str],
) -> dict[str, Any]:
    payload = {
        "plugin_id": manifest.plugin_id,
        "version": manifest.version,
        "content_hash": content_hash,
        "python_dependencies": dependencies,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        **payload,
        "environment_key": hashlib.sha256(encoded).hexdigest(),
    }


def _marker_matches(marker_path: Path, metadata: dict[str, Any]) -> bool:
    if not marker_path.is_file():
        return False
    try:
        current = json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return all(current.get(key) == value for key, value in metadata.items())


def _environment_python(env_path: Path) -> Path:
    if sys.platform == "win32":
        return env_path / "Scripts" / "python.exe"
    return env_path / "bin" / "python"


def _site_paths(env_path: Path) -> tuple[Path, ...]:
    python = _environment_python(env_path)
    if not python.is_file():
        raise PluginConfigurationError(
            f"Plugin Python environment {env_path} does not contain python"
        )
    completed = _run_command(
        [
            str(python),
            "-c",
            "import json, site; print(json.dumps(site.getsitepackages()))",
        ],
        timeout_seconds=30.0,
        cwd=env_path,
        plugin_id="plugin_environment",
    )
    try:
        paths = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PluginConfigurationError(
            f"Plugin Python environment {env_path} did not report site-packages",
            cause=exc,
        ) from exc
    if not isinstance(paths, list):
        raise PluginConfigurationError(
            f"Plugin Python environment {env_path} returned invalid site-packages"
        )
    return tuple(Path(str(path)) for path in paths)


def _run_command(
    command: list[str],
    *,
    timeout_seconds: float,
    cwd: Path,
    plugin_id: str,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PluginConfigurationError(
            f"Plugin {plugin_id} Python environment command failed to start",
            cause=exc,
        ) from exc
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise PluginConfigurationError(
            f"Plugin {plugin_id} Python environment command failed with "
            f"exit code {completed.returncode}: {stderr}"
        )
    return completed


__all__ = ["PluginPythonEnvironment", "PluginPythonEnvironmentManager"]
