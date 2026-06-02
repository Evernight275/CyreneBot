from __future__ import annotations

from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.core.schema.tool import (
    ShellCommandDecision,
    ShellCommandPolicy,
    ShellCommandRule,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
)


def test_tool_result_defaults_are_isolated() -> None:
    first = ToolResult(
        call_id="call-1",
        name="lookup",
        content="ok",
    )
    second = ToolResult(
        call_id="call-2",
        name="lookup",
    )

    first.metadata["key"] = "value"

    assert first.success is True
    assert first.error is None
    assert second.metadata == {}


def test_tool_definition_has_trusted_safety_profile_by_default() -> None:
    definition = ToolDefinition(
        name="lookup",
        description="Lookup a value.",
    )

    assert definition.safety_profile.risk_level == ToolRiskLevel.TRUSTED
    assert definition.safety_profile.permissions == []
    assert definition.safety_profile.sandbox_required is False

    definition.safety_profile.permissions.append(ToolPermission.MEMORY_READ)
    next_definition = ToolDefinition(
        name="next_lookup",
        description="Lookup another value.",
    )
    assert next_definition.safety_profile.permissions == []


def test_shell_command_policy_defaults_and_rules() -> None:
    policy = ShellCommandPolicy(
        rules=[
            ShellCommandRule(
                command="rg",
                decision=ShellCommandDecision.ALLOW,
            )
        ]
    )

    assert policy.default_decision == ShellCommandDecision.DENY
    assert policy.rules[0].command == "rg"
    assert policy.rules[0].decision == ShellCommandDecision.ALLOW
    assert "&&" in policy.blocked_tokens


def test_provider_config_repr_hides_api_key() -> None:
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key="secret-key",
    )

    assert "secret-key" not in repr(config)
