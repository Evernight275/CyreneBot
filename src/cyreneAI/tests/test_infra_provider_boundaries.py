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

APPLICATION_TOP_LEVEL_NAMES = {
    "__init__.py",
    "bootstrap.py",
    "bot",
    "channels",
    "chat",
    "generation",
    "knowledge",
    "plugins",
    "runtime.py",
}

APPLICATION_ALLOWED_PUBLIC_DATACLASSES = {
    ("application/runtime.py", "CyreneAIRuntime"),
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


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _decorator_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return _base_name(node)


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


def test_infra_does_not_import_application_or_server() -> None:
    violations = []
    forbidden_prefixes = {
        "cyreneAI.application",
        "cyreneAI.server",
    }

    for path in _python_files(INFRA_DIR):
        for module in _imported_modules(path):
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
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


def test_application_does_not_import_infra_or_server() -> None:
    violations = []
    forbidden_prefixes = {
        "cyreneAI.infra",
        "cyreneAI.server",
    }

    for path in _python_files(APPLICATION_DIR):
        for module in _imported_modules(path):
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
            ):
                violations.append((_relative(path), module))

    assert violations == []


def test_application_does_not_define_core_schema_classes() -> None:
    violations = []

    for path in _python_files(APPLICATION_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if any(_base_name(base) == "CyreneAISchema" for base in node.bases):
                violations.append((_relative(path), node.name))

    assert violations == []


def test_application_does_not_define_public_dataclass_dtos() -> None:
    violations = []

    for path in _python_files(APPLICATION_DIR):
        relative_path = _relative(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                _decorator_name(decorator) == "dataclass"
                for decorator in node.decorator_list
            ):
                continue
            if node.name.startswith("_"):
                continue
            if (relative_path, node.name) in APPLICATION_ALLOWED_PUBLIC_DATACLASSES:
                continue
            violations.append((relative_path, node.name))

    assert violations == []


def test_only_core_schema_defines_cyrene_ai_schema_subclasses() -> None:
    violations = []
    allowed_dir = CORE_DIR / "schema"

    for path in _python_files(PROJECT_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(_base_name(base) == "CyreneAISchema" for base in node.bases):
                continue
            if not path.is_relative_to(allowed_dir):
                violations.append((_relative(path), node.name))

    assert violations == []


def test_application_top_level_is_grouped_by_use_case_area() -> None:
    invalid_paths = [
        path
        for path in APPLICATION_DIR.iterdir()
        if path.name != "__pycache__" and path.name not in APPLICATION_TOP_LEVEL_NAMES
    ]

    assert invalid_paths == []
