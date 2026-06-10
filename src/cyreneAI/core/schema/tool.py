from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema


class ToolPermission(StrEnum):
    """
    Tool permission categories used by execution policy checks.
    """

    CONTEXT_READ = "context.read"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    NETWORK = "network"
    SUBPROCESS = "subprocess"
    ENVIRONMENT = "environment"


class ToolRiskLevel(StrEnum):
    """
    Coarse risk levels for tool execution.
    """

    TRUSTED = "trusted"
    READ_ONLY = "read_only"
    WRITE = "write"
    NETWORK = "network"
    PROCESS = "process"


class ShellCommandDecision(StrEnum):
    """
    Controlled shell command policy decision.
    """

    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"


def _empty_tool_permissions() -> list[ToolPermission]:
    return []


def _empty_tool_names() -> list[str]:
    return []


def _empty_shell_command_rules() -> list["ShellCommandRule"]:
    return []


def _empty_shell_blocked_tokens() -> list[str]:
    return [
        "|",
        "||",
        "&",
        "&&",
        ";",
        ">",
        ">>",
        "<",
        "`",
        "$(",
    ]


def _empty_mcp_args() -> list[str]:
    return []


def _empty_mcp_env() -> dict[str, str]:
    return {}


class ToolSafetyProfile(CyreneAISchema):
    """
    Tool safety metadata used before dispatching execution.
    """

    risk_level: ToolRiskLevel = ToolRiskLevel.TRUSTED
    permissions: list[ToolPermission] = Field(default_factory=_empty_tool_permissions)
    sandbox_required: bool = False
    timeout_seconds: int | None = Field(default=None, ge=1)
    max_output_chars: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionPolicy(CyreneAISchema):
    """
    Per-execution policy gate for tool calls.
    """

    allowed_tool_names: list[str] | None = None
    denied_tool_names: list[str] = Field(default_factory=_empty_tool_names)
    allowed_permissions: list[ToolPermission] | None = None
    max_risk_level: ToolRiskLevel | None = None
    allow_sandbox_bypass: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ShellCommandRule(CyreneAISchema):
    """
    A first-token command rule for controlled shell execution.
    """

    command: str
    decision: ShellCommandDecision
    subcommands: list[str] | None = None


class ShellCommandPolicy(CyreneAISchema):
    """
    Controlled shell policy for allow/review/deny command classes.
    """

    rules: list[ShellCommandRule] = Field(default_factory=_empty_shell_command_rules)
    default_decision: ShellCommandDecision = ShellCommandDecision.DENY
    blocked_tokens: list[str] = Field(default_factory=_empty_shell_blocked_tokens)


class ToolDefinition(CyreneAISchema):
    """
    工具定义schema
    """

    name: str
    description: str
    parameters_schema: dict[str, Any] | None = None
    safety_profile: ToolSafetyProfile = Field(default_factory=ToolSafetyProfile)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(CyreneAISchema):
    """
    工具调用schema
    """

    id: str
    name: str
    arguments: str | None = None


class ToolResult(CyreneAISchema):
    """
    工具执行结果schema
    """

    call_id: str
    name: str
    content: str | None = None
    success: bool = True
    error: str | None = None
    requires_replan: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolChoice(CyreneAISchema):
    """
    工具选择schema
    """

    mode: Literal["auto", "none", "required", "tool"] = "auto"
    name: str | None = None


class MCPStdioServerConfig(CyreneAISchema):
    """
    MCP stdio server configuration used by infra adapters.
    """

    name: str
    command: str
    args: list[str] = Field(default_factory=_empty_mcp_args)
    env: dict[str, str] = Field(default_factory=_empty_mcp_env)
    enabled: bool = True
    timeout_seconds: float = Field(default=30, gt=0)
