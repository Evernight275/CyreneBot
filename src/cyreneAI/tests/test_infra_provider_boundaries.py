from __future__ import annotations

from pathlib import Path


def test_infra_provider_catalog_only_contains_info_files() -> None:
    provider_catalog_dir = Path(__file__).parents[1] / "infra" / "provider_catalog"

    invalid_paths = []
    for path in provider_catalog_dir.iterdir():
        if path.name == "__pycache__":
            continue
        if path.name == "__init__.py":
            continue
        if path.is_file() and path.name.endswith("_info.py"):
            continue
        invalid_paths.append(path)

    assert invalid_paths == []
