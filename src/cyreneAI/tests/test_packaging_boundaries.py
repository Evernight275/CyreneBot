from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_pyproject() -> dict[str, Any]:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))


def test_setuptools_uses_package_whitelist() -> None:
    pyproject = _load_pyproject()

    project = pyproject["project"]
    setuptools_config = pyproject["tool"]["setuptools"]
    package_find = setuptools_config["packages"]["find"]

    assert project["name"] == "cyreneai-plugin-sdk"
    assert project["dependencies"] == ["pydantic"]
    assert pyproject["project"]["scripts"] == {"cyrene-plugin": "cyreneAI.api.cli:main"}
    assert setuptools_config["include-package-data"] is False
    assert package_find["where"] == ["src"]
    assert package_find["include"] == [
        "cyreneAI.api*",
        "cyreneAI.core*",
    ]
    assert package_find["exclude"] == [
        "cyreneAI.adapters*",
        "cyreneAI.application*",
        "cyreneAI.bootstrap*",
        "cyreneAI.infra*",
        "cyreneAI.server*",
        "cyreneAI.tests*",
    ]
    assert pyproject["tool"]["setuptools"]["package-data"]["cyreneAI.api"] == [
        "py.typed"
    ]
    assert pyproject["tool"]["setuptools"]["package-data"]["cyreneAI.core"] == [
        "py.typed"
    ]


def test_plugin_sdk_package_policy_is_machine_readable() -> None:
    pyproject = _load_pyproject()
    package_policy = pyproject["tool"]["cyreneAI"]["plugin_sdk_package"]

    assert package_policy["distribution_name"] == "cyreneai-plugin-sdk"
    assert package_policy["package_name"] == "cyreneAI"
    assert package_policy["include_packages"] == [
        "cyreneAI.api*",
        "cyreneAI.core*",
    ]
    assert package_policy["exclude_packages"] == [
        "cyreneAI.adapters*",
        "cyreneAI.application*",
        "cyreneAI.bootstrap*",
        "cyreneAI.infra*",
        "cyreneAI.server*",
        "cyreneAI.tests*",
    ]

    for required_file in package_policy["required_files"]:
        assert (PROJECT_ROOT / required_file).exists()


def test_plugin_sdk_package_policy_forbids_repository_artifacts() -> None:
    pyproject = _load_pyproject()
    forbidden_paths = set(
        pyproject["tool"]["cyreneAI"]["plugin_sdk_package"]["forbidden_sdist_paths"]
    )

    assert {
        ".env",
        ".github",
        ".venv",
        "data",
        "examples",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "frontend",
    } <= forbidden_paths


def test_manifest_excludes_non_distribution_artifacts() -> None:
    manifest = (PROJECT_ROOT / "MANIFEST.in").read_text("utf-8")

    for line in [
        "exclude src/cyreneAI/__init__.py",
        "exclude src/cyreneAI/bootstrap.py",
        "graft src/cyreneAI/api",
        "graft src/cyreneAI/core",
        "prune src/cyreneAI/adapters",
        "prune src/cyreneAI/application",
        "prune src/cyreneAI/infra",
        "prune src/cyreneAI/server",
        "prune src/cyreneAI/tests",
        "prune examples",
        "prune data",
        "prune .github",
        "prune .venv",
        "global-exclude .env",
        "global-exclude .env.*",
        "global-exclude Dockerfile",
        "global-exclude docker-compose.yml",
        "global-exclude docker-compose.yaml",
    ]:
        assert line in manifest
