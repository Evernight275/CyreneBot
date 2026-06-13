from __future__ import annotations

import ast
import json
import math
import operator
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol, ToolRegistryProtocol

_MAX_TEXT_LENGTH = 200_000
_MAX_JSON_TEXT_LENGTH = 200_000
_MAX_JSON_PATH_SEGMENTS = 64
_MAX_CALC_NODES = 128
_MAX_CALC_ABS_VALUE = 1_000_000_000_000
_MAX_CALC_RESULT_ABS_VALUE = 1_000_000_000_000_000


def register_core_builtin_tools(registry: ToolRegistryProtocol) -> None:
    """
    Register deterministic, stdlib-only tools that are useful to agents by default.
    """
    _register_if_missing(
        registry,
        ToolDefinition(
            name="get_current_time",
            description=(
                "Get the current date and time. Optionally pass a UTC offset "
                "like +08:00 or -05:30."
            ),
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.READ_ONLY,
                timeout_seconds=2,
                max_output_chars=2048,
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "utc_offset": {
                        "type": "string",
                        "description": "Optional offset in +HH:MM or -HH:MM format.",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["iso", "unix"],
                        "description": "Output format. Defaults to iso.",
                    },
                },
                "additionalProperties": False,
            },
        ),
        _CurrentTimeToolExecutor(),
    )
    _register_if_missing(
        registry,
        ToolDefinition(
            name="calculate",
            description=(
                "Evaluate a safe arithmetic expression with math functions. "
                "Use for deterministic numeric work."
            ),
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.TRUSTED,
                timeout_seconds=2,
                max_output_chars=4096,
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic expression, for example sqrt(9)+2.",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        ),
        _CalculateToolExecutor(),
    )
    _register_if_missing(
        registry,
        ToolDefinition(
            name="json_get",
            description=(
                "Read a value from JSON by path. Path supports dotted object keys "
                "and list indexes, for example users.0.name."
            ),
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.READ_ONLY,
                permissions=[ToolPermission.CONTEXT_READ],
                timeout_seconds=2,
                max_output_chars=16384,
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "json": {
                        "type": "string",
                        "description": "JSON document text.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional dotted path. Empty path returns root.",
                    },
                },
                "required": ["json"],
                "additionalProperties": False,
            },
        ),
        _JsonGetToolExecutor(),
    )
    _register_if_missing(
        registry,
        ToolDefinition(
            name="text_search",
            description=(
                "Search plain text for a substring or regular expression and "
                "return matching spans."
            ),
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.READ_ONLY,
                permissions=[ToolPermission.CONTEXT_READ],
                timeout_seconds=2,
                max_output_chars=16384,
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "query": {"type": "string"},
                    "regex": {"type": "boolean"},
                    "case_sensitive": {"type": "boolean"},
                    "max_matches": {"type": "integer"},
                },
                "required": ["text", "query"],
                "additionalProperties": False,
            },
        ),
        _TextSearchToolExecutor(),
    )


class _CurrentTimeToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        tz = _timezone(arguments.get("utc_offset"))
        now = datetime.now(tz)
        output_format = _optional_string(arguments.get("format"), default="iso")
        if output_format not in {"iso", "unix"}:
            raise ToolExecutionError("format must be iso or unix")
        payload: dict[str, Any] = {
            "utc_offset": _format_utc_offset(now.utcoffset()),
            "timezone": "UTC" if tz is UTC else str(tz),
        }
        if output_format == "unix":
            payload["unix"] = now.timestamp()
        else:
            payload["iso"] = now.isoformat()
        return _json_result(call, payload)


class _CalculateToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        expression = _required_string(arguments, "expression")
        result = _evaluate_expression(expression)
        return _json_result(
            call,
            {
                "expression": expression,
                "result": result,
            },
        )


class _JsonGetToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        json_text = _required_string(arguments, "json")
        if len(json_text) > _MAX_JSON_TEXT_LENGTH:
            raise ToolExecutionError("json is too large")
        try:
            value = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("json must be valid JSON", cause=exc) from exc
        path = _optional_string(arguments.get("path"), default="")
        selected = _select_json_path(value, path)
        return _json_result(
            call,
            {
                "path": path,
                "value": selected,
            },
        )


class _TextSearchToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(call)
        text = _required_string(arguments, "text")
        query = _required_string(arguments, "query")
        if len(text) > _MAX_TEXT_LENGTH:
            raise ToolExecutionError("text is too large")
        regex = _optional_bool(arguments.get("regex"), default=False)
        case_sensitive = _optional_bool(
            arguments.get("case_sensitive"),
            default=False,
        )
        max_matches = _positive_int(
            arguments.get("max_matches"), default=20, maximum=100
        )
        matches = (
            _regex_matches(
                text=text,
                query=query,
                case_sensitive=case_sensitive,
                max_matches=max_matches,
            )
            if regex
            else _substring_matches(
                text=text,
                query=query,
                case_sensitive=case_sensitive,
                max_matches=max_matches,
            )
        )
        return _json_result(
            call,
            {
                "query": query,
                "regex": regex,
                "case_sensitive": case_sensitive,
                "match_count": len(matches),
                "matches": matches,
            },
        )


def _register_if_missing(
    registry: ToolRegistryProtocol,
    definition: ToolDefinition,
    executor: ToolExecutorProtocol,
) -> None:
    if registry.exists(definition.name):
        return
    registry.register(definition, executor)


def _parse_arguments(call: ToolCall) -> dict[str, Any]:
    if not call.arguments:
        return {}
    try:
        parsed = json.loads(call.arguments)
    except json.JSONDecodeError as exc:
        raise ToolExecutionError(
            "Tool arguments must be valid JSON", cause=exc
        ) from exc
    if not isinstance(parsed, dict):
        raise ToolExecutionError("Tool arguments must be a JSON object")
    return cast(dict[str, Any], parsed)


def _required_string(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolExecutionError(f"{name} is required")
    return value.strip()


def _optional_string(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ToolExecutionError("value must be a string")
    return value.strip()


def _optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ToolExecutionError("value must be a boolean")
    return value


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ToolExecutionError("value must be a positive integer")
    return min(value, maximum)


def _timezone(value: Any) -> timezone:
    if value is None:
        return UTC
    if not isinstance(value, str):
        raise ToolExecutionError("utc_offset must be a string")
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value.strip())
    if match is None:
        raise ToolExecutionError("utc_offset must match +HH:MM or -HH:MM")
    sign, hours_text, minutes_text = match.groups()
    hours = int(hours_text)
    minutes = int(minutes_text)
    if hours > 23 or minutes > 59:
        raise ToolExecutionError("utc_offset is out of range")
    delta = timedelta(hours=hours, minutes=minutes)
    if sign == "-":
        delta = -delta
    return timezone(delta)


def _format_utc_offset(value: timedelta | None) -> str:
    if value is None:
        return "+00:00"
    total_minutes = int(value.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    absolute_minutes = abs(total_minutes)
    hours, minutes = divmod(absolute_minutes, 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _math_abs(value: float) -> float:
    return abs(value)


def _math_ceil(value: float) -> float:
    return float(math.ceil(value))


def _math_floor(value: float) -> float:
    return float(math.floor(value))


def _math_max(first: float, *values: float) -> float:
    return max(first, *values)


def _math_min(first: float, *values: float) -> float:
    return min(first, *values)


def _math_pow(base: float, exponent: float) -> float:
    return float(pow(base, exponent))


def _math_round(value: float, digits: float = 0) -> float:
    return float(round(value, int(digits)))


def _math_sqrt(value: float) -> float:
    return math.sqrt(value)


_FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": _math_abs,
    "ceil": _math_ceil,
    "floor": _math_floor,
    "max": _math_max,
    "min": _math_min,
    "pow": _math_pow,
    "round": _math_round,
    "sqrt": _math_sqrt,
}
_CONSTANTS = {
    "e": math.e,
    "pi": math.pi,
    "tau": math.tau,
}


def _evaluate_expression(expression: str) -> float | int:
    if len(expression) > 512:
        raise ToolExecutionError("expression is too large")
    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolExecutionError(
            "expression must be valid arithmetic", cause=exc
        ) from exc
    node_count = sum(1 for _ in ast.walk(parsed))
    if node_count > _MAX_CALC_NODES:
        raise ToolExecutionError("expression is too complex")
    result = _eval_node(parsed.body)
    if not math.isfinite(float(result)):
        raise ToolExecutionError("calculation result is not finite")
    if abs(float(result)) > _MAX_CALC_RESULT_ABS_VALUE:
        raise ToolExecutionError("calculation result is too large")
    if isinstance(result, float) and result.is_integer():
        return int(result)
    return result


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        value = node.value
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ToolExecutionError("expression constants must be numbers")
        numeric_value = float(value)
        if abs(numeric_value) > _MAX_CALC_ABS_VALUE:
            raise ToolExecutionError("expression number is too large")
        return numeric_value

    if isinstance(node, ast.Name):
        if node.id not in _CONSTANTS:
            raise ToolExecutionError(f"unknown constant: {node.id}")
        return _CONSTANTS[node.id]

    if isinstance(node, ast.BinOp):
        operator_type = type(node.op)
        if operator_type not in _BINARY_OPERATORS:
            raise ToolExecutionError("unsupported arithmetic operator")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ToolExecutionError("exponent is too large")
        try:
            return float(_BINARY_OPERATORS[operator_type](left, right))
        except (OverflowError, ValueError, ZeroDivisionError) as exc:
            raise ToolExecutionError("calculation failed", cause=exc) from exc

    if isinstance(node, ast.UnaryOp):
        operator_type = type(node.op)
        if operator_type not in _UNARY_OPERATORS:
            raise ToolExecutionError("unsupported unary operator")
        return float(_UNARY_OPERATORS[operator_type](_eval_node(node.operand)))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ToolExecutionError("only direct math function calls are allowed")
        function = _FUNCTIONS.get(node.func.id)
        if function is None:
            raise ToolExecutionError(f"unknown function: {node.func.id}")
        if node.keywords:
            raise ToolExecutionError("keyword arguments are not supported")
        args = [_eval_node(arg) for arg in node.args]
        if len(args) > 8:
            raise ToolExecutionError("too many function arguments")
        try:
            return float(function(*args))
        except (OverflowError, ValueError, ZeroDivisionError) as exc:
            raise ToolExecutionError("calculation failed", cause=exc) from exc

    raise ToolExecutionError("unsupported expression node")


def _select_json_path(value: Any, path: str) -> Any:
    if not path:
        return value
    segments = path.split(".")
    if len(segments) > _MAX_JSON_PATH_SEGMENTS:
        raise ToolExecutionError("path is too deep")
    current = value
    for segment in segments:
        if segment == "":
            raise ToolExecutionError("path cannot contain empty segments")
        if isinstance(current, dict):
            current_dict = cast(dict[str, Any], current)
            if segment not in current_dict:
                raise ToolExecutionError(f"path segment not found: {segment}")
            current = current_dict[segment]
            continue
        if isinstance(current, list):
            current_list = cast(list[Any], current)
            if not segment.isdigit():
                raise ToolExecutionError("list path segment must be an index")
            index = int(segment)
            if index >= len(current_list):
                raise ToolExecutionError(f"list index out of range: {segment}")
            current = current_list[index]
            continue
        raise ToolExecutionError(f"path cannot descend into: {segment}")
    return current


def _substring_matches(
    *,
    text: str,
    query: str,
    case_sensitive: bool,
    max_matches: int,
) -> list[dict[str, Any]]:
    haystack = text if case_sensitive else text.casefold()
    needle = query if case_sensitive else query.casefold()
    matches: list[dict[str, Any]] = []
    start = 0
    while len(matches) < max_matches:
        index = haystack.find(needle, start)
        if index < 0:
            break
        end = index + len(needle)
        matches.append(_match_payload(text, index, end))
        start = max(end, index + 1)
    return matches


def _regex_matches(
    *,
    text: str,
    query: str,
    case_sensitive: bool,
    max_matches: int,
) -> list[dict[str, Any]]:
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query, flags=flags)
    except re.error as exc:
        raise ToolExecutionError(
            "query must be a valid regular expression", cause=exc
        ) from exc
    matches: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        matches.append(_match_payload(text, match.start(), match.end()))
        if len(matches) >= max_matches:
            break
    return matches


def _match_payload(text: str, start: int, end: int) -> dict[str, Any]:
    preview_start = max(0, start - 40)
    preview_end = min(len(text), end + 40)
    return {
        "start": start,
        "end": end,
        "match": text[start:end],
        "preview": text[preview_start:preview_end],
    }


def _json_result(call: ToolCall, payload: dict[str, Any]) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


__all__ = ["register_core_builtin_tools"]
