from __future__ import annotations

from cyreneAI.core.errors.tool import ToolPolicyError
from cyreneAI.core.schema.tool import ToolDefinition, ToolExecutionPolicy
from cyreneAI.core.tool.policy import enforce_tool_execution_policy


def build_effective_tool_execution_policy(
    *,
    policy: ToolExecutionPolicy | None,
    allowed_tool_names: list[str] | set[str] | None = None,
    constrained_tool_names: list[str] | set[str] | None = None,
    additional_denied_tool_names: list[str] | set[str] | None = None,
) -> ToolExecutionPolicy:
    """
    Compose legacy tool-name allowlists and richer execution policy fields.
    """
    effective_policy = policy or ToolExecutionPolicy()
    return effective_policy.model_copy(
        update={
            "allowed_tool_names": _intersect_allowed_tool_names(
                effective_policy.allowed_tool_names,
                allowed_tool_names,
                constrained_tool_names,
            ),
            "denied_tool_names": _merge_tool_names(
                effective_policy.denied_tool_names,
                additional_denied_tool_names,
            ),
        }
    )


def filter_tool_definitions_for_policy(
    *,
    definitions: list[ToolDefinition],
    policy: ToolExecutionPolicy,
    sandbox_available: bool,
) -> list[ToolDefinition]:
    """
    Hide tools the current policy would reject, so the model sees usable tools.
    """
    allowed_definitions: list[ToolDefinition] = []
    for definition in definitions:
        try:
            enforce_tool_execution_policy(
                definition=definition,
                policy=policy,
                sandbox_available=sandbox_available,
            )
        except ToolPolicyError:
            continue
        allowed_definitions.append(definition)
    return allowed_definitions


def _intersect_allowed_tool_names(
    *values: list[str] | set[str] | None,
) -> list[str] | None:
    allowed: set[str] | None = None
    for value in values:
        if value is None:
            continue
        value_set = set(value)
        allowed = value_set if allowed is None else allowed & value_set
    if allowed is None:
        return None
    return sorted(allowed)


def _merge_tool_names(
    *values: list[str] | set[str] | None,
) -> list[str]:
    names: set[str] = set()
    for value in values:
        if value is not None:
            names.update(value)
    return sorted(names)
