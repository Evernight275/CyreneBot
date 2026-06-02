from __future__ import annotations

import asyncio
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from cyreneAI.core.errors.tool import ToolExecutionError, ToolPolicyError
from cyreneAI.core.schema.tool import (
    ShellCommandDecision,
    ShellCommandPolicy,
    ShellCommandRule,
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.tool.tool_protocol import ToolRegistryProtocol
from cyreneAI.infra.adapters.tools.common import parse_tool_arguments


def register_controlled_shell_tool(
    registry: ToolRegistryProtocol,
    *,
    policy: ShellCommandPolicy | None = None,
    cwd_root: str | Path | None = None,
    timeout_seconds: float = 10.0,
    max_stdout_bytes: int = 64_000,
    max_stderr_bytes: int = 16_000,
) -> None:
    """
    Register a controlled command execution tool with allow/review/deny policy.
    """
    definition = ToolDefinition(
        name="shell",
        description=(
            "Run a controlled OS command. Commands are classified as allowed, "
            "review-required, or denied before execution. Shell operators such "
            "as pipes, redirects, and command chaining are rejected."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "command": {
                    "description": "Command string or argv array.",
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                    ],
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory under the configured root.",
                },
                "review_approved": {
                    "type": "boolean",
                    "description": "Set true only after an admin has approved a review command.",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        safety_profile=ToolSafetyProfile(
            risk_level=ToolRiskLevel.PROCESS,
            permissions=[
                ToolPermission.SUBPROCESS,
                ToolPermission.FILESYSTEM_READ,
                ToolPermission.FILESYSTEM_WRITE,
                ToolPermission.NETWORK,
            ],
            sandbox_required=False,
            timeout_seconds=max(1, int(timeout_seconds)),
            max_output_chars=max_stdout_bytes + max_stderr_bytes + 4096,
        ),
        metadata={"source": "builtin"},
    )
    if registry.exists(definition.name):
        return
    registry.register(
        definition,
        _ControlledShellExecutor(
            policy=policy or default_shell_command_policy(),
            cwd_root=Path(cwd_root or Path.cwd()),
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=max_stdout_bytes,
            max_stderr_bytes=max_stderr_bytes,
        ),
    )


def default_shell_command_policy() -> ShellCommandPolicy:
    """
    Conservative default command policy.
    """
    return ShellCommandPolicy(
        rules=[
            ShellCommandRule(command="pwd", decision=ShellCommandDecision.ALLOW),
            ShellCommandRule(command="ls", decision=ShellCommandDecision.ALLOW),
            ShellCommandRule(command="cat", decision=ShellCommandDecision.ALLOW),
            ShellCommandRule(command="head", decision=ShellCommandDecision.ALLOW),
            ShellCommandRule(command="tail", decision=ShellCommandDecision.ALLOW),
            ShellCommandRule(command="rg", decision=ShellCommandDecision.ALLOW),
            ShellCommandRule(command="grep", decision=ShellCommandDecision.ALLOW),
            ShellCommandRule(command="where", decision=ShellCommandDecision.ALLOW),
            ShellCommandRule(command="which", decision=ShellCommandDecision.ALLOW),
            ShellCommandRule(
                command="git",
                decision=ShellCommandDecision.ALLOW,
                subcommands=[
                    "branch",
                    "describe",
                    "diff",
                    "grep",
                    "log",
                    "ls-files",
                    "rev-parse",
                    "show",
                    "show-ref",
                    "status",
                ],
            ),
            ShellCommandRule(
                command="python",
                decision=ShellCommandDecision.ALLOW,
                subcommands=["--version", "-V"],
            ),
            ShellCommandRule(
                command="python3",
                decision=ShellCommandDecision.ALLOW,
                subcommands=["--version", "-V"],
            ),
            ShellCommandRule(
                command="uv",
                decision=ShellCommandDecision.ALLOW,
                subcommands=["--version", "version"],
            ),
            ShellCommandRule(
                command="node",
                decision=ShellCommandDecision.ALLOW,
                subcommands=["--version", "-v"],
            ),
            ShellCommandRule(
                command="npm",
                decision=ShellCommandDecision.ALLOW,
                subcommands=["--version", "-v"],
            ),
            ShellCommandRule(command="uv", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="pip", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="pip3", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="python", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="python3", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="npm", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="npx", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="node", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="curl", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="wget", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="git", decision=ShellCommandDecision.REVIEW),
            ShellCommandRule(command="rm", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="del", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="erase", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="rmdir", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="rd", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="format", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="mkfs", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="diskpart", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="shutdown", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="reboot", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="sudo", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="su", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="cmd", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="powershell", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="pwsh", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="sh", decision=ShellCommandDecision.DENY),
            ShellCommandRule(command="bash", decision=ShellCommandDecision.DENY),
        ]
    )


class _ControlledShellExecutor:
    def __init__(
        self,
        *,
        policy: ShellCommandPolicy,
        cwd_root: Path,
        timeout_seconds: float,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> None:
        self._policy = policy
        self._cwd_root = cwd_root.resolve()
        self._timeout_seconds = timeout_seconds
        self._max_stdout_bytes = max_stdout_bytes
        self._max_stderr_bytes = max_stderr_bytes

    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = parse_tool_arguments(call.arguments)
        argv = _parse_argv(arguments.get("command"), policy=self._policy)
        cwd = _resolve_cwd(
            arguments.get("cwd"),
            root=self._cwd_root,
        )
        review_approved = _optional_bool(arguments.get("review_approved"))
        decision = _classify_command(argv, self._policy)
        metadata = {
            "argv": argv,
            "cwd": str(cwd),
            "decision": decision.value,
            "review_approved": review_approved,
        }
        if decision == ShellCommandDecision.DENY:
            raise ToolPolicyError(f"Command is denied by shell policy: {argv[0]}")
        if decision == ShellCommandDecision.REVIEW and not review_approved:
            return _json_result(
                call,
                {
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "decision": decision.value,
                    "requires_review": True,
                    "argv": argv,
                    "cwd": str(cwd),
                },
                success=False,
                error=f"Command requires review: {argv[0]}",
                metadata=metadata,
            )

        builtin_result = _execute_builtin(
            argv,
            cwd=cwd,
            root=self._cwd_root,
            call=call,
            metadata=metadata,
        )
        if builtin_result is not None:
            return builtin_result

        return await self._execute_subprocess(
            call=call,
            argv=argv,
            cwd=cwd,
            metadata=metadata,
        )

    async def _execute_subprocess(
        self,
        *,
        call: ToolCall,
        argv: list[str],
        cwd: Path,
        metadata: dict[str, Any],
    ) -> ToolResult:
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            if process is not None:
                process.kill()
                await process.wait()
            raise ToolExecutionError("shell command timed out", cause=exc) from exc
        except OSError as exc:
            raise ToolExecutionError("shell command failed to start", cause=exc) from exc

        _validate_output_size(
            stdout=stdout,
            stderr=stderr,
            max_stdout_bytes=self._max_stdout_bytes,
            max_stderr_bytes=self._max_stderr_bytes,
        )
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        return _json_result(
            call,
            {
                "exit_code": process.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "decision": metadata["decision"],
                "requires_review": False,
                "argv": argv,
                "cwd": str(cwd),
            },
            success=process.returncode == 0,
            error=stderr_text or None if process.returncode != 0 else None,
            metadata=metadata,
        )


def _parse_argv(value: object, *, policy: ShellCommandPolicy) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ToolExecutionError("command is required")
        _reject_blocked_tokens(stripped, policy)
        argv = shlex.split(stripped, posix=sys.platform != "win32")
    elif isinstance(value, list):
        argv = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ToolExecutionError("command array items must be non-empty strings")
            _reject_blocked_tokens(item, policy)
            argv.append(item.strip())
    else:
        raise ToolExecutionError("command must be a string or string array")

    if not argv:
        raise ToolExecutionError("command is required")
    return argv


def _reject_blocked_tokens(text: str, policy: ShellCommandPolicy) -> None:
    for token in policy.blocked_tokens:
        if token and token in text:
            raise ToolPolicyError(f"Shell control token is denied: {token}")


def _classify_command(
    argv: list[str],
    policy: ShellCommandPolicy,
) -> ShellCommandDecision:
    command = Path(argv[0]).name.casefold()
    subcommand = argv[1].casefold() if len(argv) > 1 else None
    fallback: ShellCommandDecision | None = None
    for rule in policy.rules:
        if rule.command.casefold() != command:
            continue
        if rule.subcommands is None:
            fallback = rule.decision
            continue
        if subcommand is not None and subcommand in {
            item.casefold()
            for item in rule.subcommands
        }:
            return rule.decision
    return fallback or policy.default_decision


def _resolve_cwd(value: object, *, root: Path) -> Path:
    if value is None:
        return root
    if not isinstance(value, str) or not value.strip():
        raise ToolExecutionError("cwd must be a non-empty string")
    path = Path(value)
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve()
    if root != resolved and not resolved.is_relative_to(root):
        raise ToolPolicyError("cwd cannot escape shell root")
    if not resolved.is_dir():
        raise ToolExecutionError("cwd must be an existing directory")
    return resolved


def _execute_builtin(
    argv: list[str],
    *,
    cwd: Path,
    root: Path,
    call: ToolCall,
    metadata: dict[str, Any],
) -> ToolResult | None:
    command = argv[0].casefold()
    if command == "pwd":
        return _builtin_result(call, str(cwd), argv=argv, cwd=cwd, metadata=metadata)
    if command == "ls":
        target = _safe_path(_ls_path_arg(argv), cwd=cwd, root=root)
        if not target.is_dir():
            raise ToolExecutionError("ls target must be a directory")
        names = [
            f"{child.name}/" if child.is_dir() else child.name
            for child in sorted(target.iterdir(), key=lambda item: item.name.casefold())
        ]
        return _builtin_result(
            call,
            "\n".join(names[:500]),
            argv=argv,
            cwd=cwd,
            metadata=metadata,
        )
    if command == "cat":
        if len(argv) < 2:
            raise ToolExecutionError("cat requires a path")
        return _builtin_result(
            call,
            _read_text(_safe_path(argv[1], cwd=cwd, root=root)),
            argv=argv,
            cwd=cwd,
            metadata=metadata,
        )
    if command in {"head", "tail"}:
        count, path_arg = _head_tail_args(argv)
        lines = _read_text(_safe_path(path_arg, cwd=cwd, root=root)).splitlines()
        selected = lines[:count] if command == "head" else lines[-count:]
        return _builtin_result(
            call,
            "\n".join(selected),
            argv=argv,
            cwd=cwd,
            metadata=metadata,
        )
    return None


def _ls_path_arg(argv: list[str]) -> str:
    path_arg = "."
    option_parsing = True
    for arg in argv[1:]:
        if option_parsing and arg == "--":
            option_parsing = False
            continue
        if option_parsing and arg.startswith("-") and arg != "-":
            _validate_ls_option(arg)
            continue
        if path_arg != ".":
            raise ToolExecutionError("ls supports at most one path")
        path_arg = arg
    return path_arg


def _validate_ls_option(value: str) -> None:
    if value in {"--all", "--almost-all", "--long", "--human-readable"}:
        return
    if value.startswith("--"):
        raise ToolExecutionError(f"unsupported ls option: {value}")
    supported_short_options = set("aAlhF1p")
    unsupported_options = [
        option for option in value[1:] if option not in supported_short_options
    ]
    if unsupported_options:
        raise ToolExecutionError(f"unsupported ls option: -{unsupported_options[0]}")


def _head_tail_args(argv: list[str]) -> tuple[int, str]:
    if len(argv) == 2:
        return 20, argv[1]
    if len(argv) == 4 and argv[1] == "-n":
        try:
            count = int(argv[2])
        except ValueError as exc:
            raise ToolExecutionError("line count must be an integer", cause=exc) from exc
        if count < 1 or count > 500:
            raise ToolExecutionError("line count must be between 1 and 500")
        return count, argv[3]
    raise ToolExecutionError(f"Usage: {argv[0]} [-n count] <path>")


def _safe_path(value: str, *, cwd: Path, root: Path) -> Path:
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else cwd / candidate).resolve()
    if root != resolved and not resolved.is_relative_to(root):
        raise ToolPolicyError("path cannot escape shell root")
    if not resolved.exists():
        raise ToolExecutionError(f"path does not exist: {value}")
    return resolved


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise ToolExecutionError("path must be a file")
    data = path.read_bytes()
    if len(data) > 256_000:
        raise ToolExecutionError("file is too large")
    return data.decode("utf-8", errors="replace")


def _builtin_result(
    call: ToolCall,
    stdout: str,
    *,
    argv: list[str],
    cwd: Path,
    metadata: dict[str, Any],
) -> ToolResult:
    return _json_result(
        call,
        {
            "exit_code": 0,
            "stdout": stdout,
            "stderr": "",
            "decision": metadata["decision"],
            "requires_review": False,
            "argv": argv,
            "cwd": str(cwd),
        },
        metadata=metadata,
    )


def _optional_bool(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ToolExecutionError("review_approved must be a boolean")
    return value


def _validate_output_size(
    *,
    stdout: bytes,
    stderr: bytes,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> None:
    if len(stdout) > max_stdout_bytes:
        raise ToolExecutionError("shell command stdout exceeded maximum size")
    if len(stderr) > max_stderr_bytes:
        raise ToolExecutionError("shell command stderr exceeded maximum size")


def _json_result(
    call: ToolCall,
    payload: dict[str, Any],
    *,
    success: bool = True,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        success=success,
        error=error,
        metadata=metadata or {},
    )


__all__ = ["default_shell_command_policy", "register_controlled_shell_tool"]
