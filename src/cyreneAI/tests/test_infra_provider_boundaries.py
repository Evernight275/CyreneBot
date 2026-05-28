from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
CORE_DIR = PROJECT_ROOT / "core"
INFRA_DIR = PROJECT_ROOT / "infra"
APPLICATION_DIR = PROJECT_ROOT / "application"
PROVIDER_CATALOG_DIR = INFRA_DIR / "provider_catalog"
PROVIDER_ADAPTERS_DIR = INFRA_DIR / "adapters" / "providers"
BOOTSTRAP_REGISTRATIONS_DIR = INFRA_DIR / "bootstrap" / "registrations"

EXTERNAL_SDK_IMPORT_ROOTS = {
    "anthropic",
    "dotenv",
    "google",
    "httpx",
    "openai",
}


def _python_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _imports_root(module: str, roots: set[str]) -> bool:
    return module.split(".", maxsplit=1)[0] in roots


def test_infra_provider_catalog_only_contains_info_files() -> None:
    invalid_paths = []
    for path in PROVIDER_CATALOG_DIR.iterdir():
        if path.name == "__pycache__":
            continue
        if path.name == "__init__.py":
            continue
        if path.is_file() and path.name.endswith("_info.py"):
            continue
        invalid_paths.append(path)

    assert invalid_paths == []


def test_core_does_not_import_external_sdks_or_upper_layers() -> None:
    forbidden_import_roots = {
        *EXTERNAL_SDK_IMPORT_ROOTS,
        "cyreneAI.infra",
        "cyreneAI.application",
        "cyreneAI.server",
        "cyreneAI.adapters",
    }
    violations = []

    for path in _python_files(CORE_DIR):
        for module in _imported_modules(path):
            if _imports_root(module, EXTERNAL_SDK_IMPORT_ROOTS) or any(
                module == root or module.startswith(f"{root}.")
                for root in forbidden_import_roots
                if root.startswith("cyreneAI.")
            ):
                violations.append((_relative(path), module))

    assert violations == []


def test_provider_catalog_imports_only_core_schema() -> None:
    violations = []

    for path in _python_files(PROVIDER_CATALOG_DIR):
        for module in _imported_modules(path):
            if module.startswith("cyreneAI.") and not module.startswith(
                "cyreneAI.core.schema."
            ):
                violations.append((_relative(path), module))
            elif _imports_root(module, EXTERNAL_SDK_IMPORT_ROOTS):
                violations.append((_relative(path), module))

    assert violations == []


def test_provider_adapter_directories_have_expected_files() -> None:
    invalid_paths = []

    for path in PROVIDER_ADAPTERS_DIR.iterdir():
        if path.name == "__pycache__":
            continue
        if path.name in {"__init__.py", "model_mapper.py"}:
            continue
        if path.is_dir():
            allowed_names = {"__init__.py", "builder.py", "errors.py", "instance.py", "mapper.py"}
            for child in path.iterdir():
                if child.name == "__pycache__":
                    continue
                if child.name not in allowed_names or not child.is_file():
                    invalid_paths.append(child)
            continue
        invalid_paths.append(path)

    assert invalid_paths == []


def test_provider_adapters_do_not_import_application_or_server() -> None:
    violations = []

    for path in _python_files(PROVIDER_ADAPTERS_DIR):
        for module in _imported_modules(path):
            if (
                module == "cyreneAI.application"
                or module.startswith("cyreneAI.application.")
                or module == "cyreneAI.server"
                or module.startswith("cyreneAI.server.")
            ):
                violations.append((_relative(path), module))

    assert violations == []


def test_bootstrap_registrations_only_wire_core_catalog_and_adapters() -> None:
    allowed_roots = {
        "cyreneAI.core",
        "cyreneAI.infra.adapters",
        "cyreneAI.infra.bootstrap",
        "cyreneAI.infra.provider_catalog",
    }
    violations = []

    for path in _python_files(BOOTSTRAP_REGISTRATIONS_DIR):
        for module in _imported_modules(path):
            if module.startswith("cyreneAI.") and not any(
                module == root or module.startswith(f"{root}.")
                for root in allowed_roots
            ):
                violations.append((_relative(path), module))
            elif _imports_root(module, EXTERNAL_SDK_IMPORT_ROOTS):
                violations.append((_relative(path), module))

    assert violations == []


def test_application_does_not_import_provider_catalog_or_provider_instances() -> None:
    violations = []
    forbidden_prefixes = {
        "cyreneAI.infra.provider_catalog",
        "cyreneAI.infra.adapters.providers",
    }

    for path in _python_files(APPLICATION_DIR):
        for module in _imported_modules(path):
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
            ):
                violations.append((_relative(path), module))

    assert violations == []
