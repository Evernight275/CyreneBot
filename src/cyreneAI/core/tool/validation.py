from __future__ import annotations

import json
from typing import Any, cast

from cyreneAI.core.errors.tool import ToolInputError
from cyreneAI.core.schema.tool import ToolCall, ToolDefinition


def validate_tool_call_arguments(
    *,
    definition: ToolDefinition,
    call: ToolCall,
) -> dict[str, Any]:
    """
    Validate tool-call arguments before dispatching to an executor.
    """
    arguments = _parse_tool_arguments(call.arguments)
    if definition.parameters_schema is None:
        return arguments

    _validate_json_schema_value(
        value=arguments,
        schema=definition.parameters_schema,
        path="arguments",
    )
    return arguments


def _parse_tool_arguments(arguments: str | None) -> dict[str, Any]:
    if not arguments:
        return {}

    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ToolInputError("Tool arguments must be valid JSON", cause=exc) from exc

    if not isinstance(parsed, dict):
        raise ToolInputError("Tool arguments must be a JSON object")
    return cast(dict[str, Any], parsed)


def _validate_json_schema_value(
    *,
    value: Any,
    schema: dict[str, Any],
    path: str,
) -> None:
    expected_type = schema.get("type")
    if expected_type is not None:
        _validate_type(value=value, expected_type=expected_type, path=path)

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        raise ToolInputError(f"{path} must be one of {enum_values!r}")

    if expected_type == "object" or "properties" in schema or "required" in schema:
        _validate_object(value=value, schema=schema, path=path)
        return

    if expected_type == "array" or "items" in schema:
        _validate_array(value=value, schema=schema, path=path)


def _validate_type(
    *,
    value: Any,
    expected_type: Any,
    path: str,
) -> None:
    if isinstance(expected_type, str):
        expected_types = [expected_type]
    elif isinstance(expected_type, list):
        expected_types = [
            item for item in cast(list[Any], expected_type) if isinstance(item, str)
        ]
    else:
        return
    if not expected_types:
        return
    if any(_matches_type(value, candidate) for candidate in expected_types):
        return
    raise ToolInputError(f"{path} has invalid type")


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _validate_object(
    *,
    value: Any,
    schema: dict[str, Any],
    path: str,
) -> None:
    if not isinstance(value, dict):
        raise ToolInputError(f"{path} must be a JSON object")
    value_object = cast(dict[str, Any], value)

    required: list[str] = []
    raw_required = schema.get("required")
    if isinstance(raw_required, list):
        required = [
            key for key in cast(list[Any], raw_required) if isinstance(key, str)
        ]
    for key in required:
        if key not in value_object:
            raise ToolInputError(f"{path}.{key} is required")

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    property_schemas = cast(dict[str, Any], properties)
    if schema.get("additionalProperties") is False:
        unexpected_keys = sorted(set(value_object) - set(property_schemas))
        if unexpected_keys:
            raise ToolInputError(
                f"{path} has unexpected properties: {', '.join(unexpected_keys)}"
            )

    for key, property_schema in property_schemas.items():
        if key not in value_object or not isinstance(property_schema, dict):
            continue
        _validate_json_schema_value(
            value=value_object[key],
            schema=cast(dict[str, Any], property_schema),
            path=f"{path}.{key}",
        )


def _validate_array(
    *,
    value: Any,
    schema: dict[str, Any],
    path: str,
) -> None:
    if not isinstance(value, list):
        raise ToolInputError(f"{path} must be a JSON array")
    values = cast(list[Any], value)

    item_schema = schema.get("items")
    if not isinstance(item_schema, dict):
        return

    for index, item in enumerate(values):
        _validate_json_schema_value(
            value=item,
            schema=item_schema,
            path=f"{path}[{index}]",
        )
