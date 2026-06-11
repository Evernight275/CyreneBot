#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"


def main() -> int:
    args = _parse_args()
    build_frontend = _build_frontend_mode(args.build_frontend)

    if build_frontend == "always" or (
        build_frontend == "auto" and _frontend_build_required()
    ):
        _build_frontend(args.npm_registry)

    env = os.environ.copy()
    env["PYTHONPATH"] = env.get("PYTHONPATH") or "src"

    print(f"Successfully Start the Server", flush=True)
    print(f"Login:   http://{args.host}:{args.port}/console/login", flush=True)

    return _run_server(
        [
            "uv",
            "run",
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
    return parser.parse_args()


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
