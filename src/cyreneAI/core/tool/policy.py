from __future__ import annotations

from cyreneAI.core.errors.tool import ToolPolicyError
from cyreneAI.core.schema.tool import (
    ToolDefinition,
    ToolExecutionPolicy,
    ToolRiskLevel,
)


_RISK_ORDER = {
    ToolRiskLevel.TRUSTED: 0,
    ToolRiskLevel.READ_ONLY: 1,
    ToolRiskLevel.WRITE: 2,
    ToolRiskLevel.NETWORK: 3,
    ToolRiskLevel.PROCESS: 4,
}


def enforce_tool_execution_policy(
    *,
    definition: ToolDefinition,
    policy: ToolExecutionPolicy,
    sandbox_available: bool = False,
) -> None:
    """
    Enforce a policy before dispatching a tool executor.
    """
    if (
        policy.allowed_tool_names is not None
        and definition.name not in policy.allowed_tool_names
    ):
        raise ToolPolicyError(f"Tool {definition.name} is not allowed")

    if definition.name in policy.denied_tool_names:
        raise ToolPolicyError(f"Tool {definition.name} is denied")

    safety_profile = definition.safety_profile
    if (
        safety_profile.sandbox_required
        and not sandbox_available
        and not policy.allow_sandbox_bypass
    ):
        raise ToolPolicyError(f"Tool {definition.name} requires sandbox execution")

    if policy.allowed_permissions is not None:
        allowed_permissions = set(policy.allowed_permissions)
        missing_permissions = [
            permission
            for permission in safety_profile.permissions
            if permission not in allowed_permissions
        ]
        if missing_permissions:
            formatted_permissions = ", ".join(missing_permissions)
            raise ToolPolicyError(
                f"Tool {definition.name} requires disallowed permissions: "
                f"{formatted_permissions}"
            )

    if policy.max_risk_level is not None and _risk_value(
        safety_profile.risk_level
    ) > _risk_value(policy.max_risk_level):
        raise ToolPolicyError(
            f"Tool {definition.name} risk level {safety_profile.risk_level} "
            f"exceeds policy maximum {policy.max_risk_level}"
        )


def build_tool_policy_audit_metadata(
    *,
    definition: ToolDefinition,
    policy: ToolExecutionPolicy,
    sandbox_used: bool,
    sandbox_mode: str | None = None,
) -> dict[str, object]:
    safety_profile = definition.safety_profile
    return {
        "policy_enforced": True,
        "tool_name": definition.name,
        "risk_level": safety_profile.risk_level.value,
        "permissions": [
            permission.value for permission in safety_profile.permissions
        ],
        "sandbox_required": safety_profile.sandbox_required,
        "timeout_seconds": safety_profile.timeout_seconds,
        "max_output_chars": safety_profile.max_output_chars,
        "allowed_tool_names": policy.allowed_tool_names,
        "denied_tool_names": policy.denied_tool_names,
        "allowed_permissions": (
            [
                permission.value
                for permission in policy.allowed_permissions
            ]
            if policy.allowed_permissions is not None
            else None
        ),
        "max_risk_level": (
            policy.max_risk_level.value
            if policy.max_risk_level is not None
            else None
        ),
        "allow_sandbox_bypass": policy.allow_sandbox_bypass,
        "sandbox_used": sandbox_used,
        "sandbox_mode": sandbox_mode,
    }


def _risk_value(risk_level: ToolRiskLevel) -> int:
    return _RISK_ORDER[risk_level]
