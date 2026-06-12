#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DISABLED_ENV_FILE_VALUES = {"", "0", "false", "no", "none", "off"}


def main() -> int:
    env_file = _preparse_env_file()
    if env_file is not None:
        loaded_count = _load_env_file(env_file, required=env_file != DEFAULT_ENV_FILE)
        if loaded_count:
            print(f"Loaded environment file: {env_file}", flush=True)

    args = _parse_args()
    build_frontend = _build_frontend_mode(args.build_frontend)

    if build_frontend == "always" or (
        build_frontend == "auto" and _frontend_build_required()
    ):
        _build_frontend(args.npm_registry)

    env = os.environ.copy()
    env["PYTHONPATH"] = env.get("PYTHONPATH") or "src"
    if args.config:
        env["CYRENEAI_CONFIG"] = str(args.config)

    print("Starting CyreneBot server...", flush=True)
    print(f"Login:   http://{args.host}:{args.port}/console/login", flush=True)

    return _run_server(
        [
            "uv",
            "run",
            "--group",
            "server",
            "python",
            "-m",
            "uvicorn",
            "cyreneAI.server.main:app",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        env=env,
    )


def _run_server(command: list[str], env: dict[str, str]) -> int:
    process = subprocess.Popen(command, cwd=ROOT_DIR, env=env)
    try:
        return process.wait()
    except KeyboardInterrupt:
        print("\nStopping CyreneBot...", flush=True)
        process.terminate()
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            return 130


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the CyreneBot server.")
    parser.add_argument(
        "--env-file",
        default=os.getenv("CYRENEAI_ENV_FILE"),
        help=(
            "Optional env file loaded before startup. Defaults to .env when it "
            "exists. Existing shell environment variables are not overridden."
        ),
    )
    parser.add_argument(
        "--no-env-file",
        action="store_true",
        help="Do not load the default .env file.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("HOST", "127.0.0.1"),
        help="Bind address. Defaults to HOST or 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8000")),
        help="Bind port. Defaults to PORT or 8000.",
    )
    parser.add_argument(
        "--build-frontend",
        default=os.getenv("BUILD_FRONTEND", "auto"),
        choices=["auto", "always", "never", "true", "false", "1", "0", "yes", "no"],
        help="Build frontend before startup. Defaults to BUILD_FRONTEND or auto.",
    )
    parser.add_argument(
        "--npm-registry",
        default=os.getenv("NPM_REGISTRY"),
        help="Optional npm registry used for npm ci.",
    )
    parser.add_argument(
        "--config",
        default=os.getenv("CYRENEAI_CONFIG"),
        help="Optional runtime config file path, for example /etc/cyrene/cyrene.toml.",
    )
    return parser.parse_args()


def _preparse_env_file() -> Path | None:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        return None

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-file")
    parser.add_argument("--no-env-file", action="store_true")
    args, _ = parser.parse_known_args()

    if args.no_env_file:
        return None

    raw_path = args.env_file if args.env_file is not None else os.getenv("CYRENEAI_ENV_FILE")
    if raw_path is not None:
        normalized = raw_path.strip()
        if normalized.lower() in _DISABLED_ENV_FILE_VALUES:
            return None
        return Path(normalized).expanduser()

    return DEFAULT_ENV_FILE if DEFAULT_ENV_FILE.is_file() else None


def _load_env_file(path: Path, *, required: bool) -> int:
    env_path = path if path.is_absolute() else (ROOT_DIR / path)
    if not env_path.is_file():
        if required:
            raise SystemExit(f"env file not found: {env_path}")
        return 0

    loaded_count = 0
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"failed to read env file: {env_path}") from exc

    for line_number, line in enumerate(lines, start=1):
        item = _parse_env_line(line, path=env_path, line_number=line_number)
        if item is None:
            continue

        key, value = item
        if key not in os.environ:
            os.environ[key] = value
            loaded_count += 1

    return loaded_count


def _parse_env_line(
    line: str,
    *,
    path: Path,
    line_number: int,
) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()

    key, separator, raw_value = stripped.partition("=")
    if not separator:
        raise SystemExit(f"invalid env file line {path}:{line_number}")

    key = key.strip()
    if not _ENV_NAME_PATTERN.fullmatch(key):
        raise SystemExit(f"invalid env variable name at {path}:{line_number}: {key}")

    return key, _parse_env_value(raw_value, path=path, line_number=line_number)


def _parse_env_value(raw_value: str, *, path: Path, line_number: int) -> str:
    value = raw_value.strip()
    if not value:
        return ""

    quote = value[0]
    if quote in {"'", '"'}:
        return _parse_quoted_env_value(value, quote=quote, path=path, line_number=line_number)

    return _strip_unquoted_env_comment(value).strip()


def _parse_quoted_env_value(
    value: str,
    *,
    quote: str,
    path: Path,
    line_number: int,
) -> str:
    chars: list[str] = []
    escaped = False

    for char in value[1:]:
        if quote == '"' and escaped:
            chars.append(_decode_env_escape(char))
            escaped = False
            continue

        if quote == '"' and char == "\\":
            escaped = True
            continue

        if char == quote:
            return "".join(chars)

        chars.append(char)

    raise SystemExit(f"unterminated quoted env value at {path}:{line_number}")


def _decode_env_escape(char: str) -> str:
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "\\": "\\",
        '"': '"',
    }
    return escapes.get(char, char)


def _strip_unquoted_env_comment(value: str) -> str:
    for index, char in enumerate(value):
        if char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index]
    return value


def _build_frontend_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"always", "true", "1", "yes"}:
        return "always"
    if normalized in {"never", "false", "0", "no"}:
        return "never"
    return "auto"


def _frontend_build_required() -> bool:
    required_paths = [
        FRONTEND_DIST_DIR / "index.html",
        FRONTEND_DIST_DIR / "login.html",
        FRONTEND_DIST_DIR / "assets",
    ]
    return any(not path.exists() for path in required_paths)


def _build_frontend(npm_registry: str | None) -> None:
    if not FRONTEND_DIR.is_dir():
        raise SystemExit(f"frontend directory not found: {FRONTEND_DIR}")

    npm_ci_command = ["npm", "ci", "--no-audit", "--no-fund"]
    if npm_registry:
        npm_ci_command.append(f"--registry={npm_registry}")

    print("Building frontend...", flush=True)
    _run(npm_ci_command, cwd=FRONTEND_DIR)
    _run(["npm", "run", "build"], cwd=FRONTEND_DIR)


def _run(command: list[str], cwd: Path) -> None:
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except FileNotFoundError as exc:
        executable = command[0]
        raise SystemExit(f"required executable not found: {executable}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
