from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT_DIR = Path(__file__).resolve().parents[3]
START_SCRIPT = ROOT_DIR / "start.py"


def test_start_script_loads_env_file_without_overriding_shell_env(
    monkeypatch,
    tmp_path,
) -> None:
    start = _load_start_script()
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "NEW_VALUE=from-dotenv",
                "EXISTING_VALUE=from-file",
                'QUOTED_VALUE="hello world"',
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("NEW_VALUE", raising=False)
    monkeypatch.delenv("QUOTED_VALUE", raising=False)
    monkeypatch.setenv("EXISTING_VALUE", "from-shell")

    loaded_count = start._load_env_file(env_path, required=True)

    assert loaded_count == 2
    assert start.os.environ["NEW_VALUE"] == "from-dotenv"
    assert start.os.environ["EXISTING_VALUE"] == "from-shell"
    assert start.os.environ["QUOTED_VALUE"] == "hello world"


def test_start_script_preparse_env_file_uses_default_dotenv(
    monkeypatch,
    tmp_path,
) -> None:
    start = _load_start_script()
    env_path = tmp_path / ".env"
    env_path.write_text("NEW_VALUE=from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(start, "DEFAULT_ENV_FILE", env_path)
    monkeypatch.setattr(sys, "argv", ["start.py"])

    assert start._preparse_env_file() == env_path


def test_start_script_preparse_env_file_skips_help(monkeypatch) -> None:
    start = _load_start_script()
    monkeypatch.setattr(sys, "argv", ["start.py", "--help"])

    assert start._preparse_env_file() is None


def _load_start_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "cyrene_start_for_tests", START_SCRIPT
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
