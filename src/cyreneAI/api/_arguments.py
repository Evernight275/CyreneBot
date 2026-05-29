from __future__ import annotations

from inspect import Parameter, Signature
from typing import Annotated, Any, TypeAlias, get_args, get_origin, get_type_hints

from cyreneAI.api._depends import PluginDependency, _resolve_dependency
from cyreneAI.core.errors.plugin import PluginConfigurationError, PluginInputError
from cyreneAI.core.schema.plugin import (
    PluginCommandArgumentKind,
    PluginCommandArgumentDefinition,
    PluginCommandRequest,
    PluginEventRequest,
    PluginTaskRequest,
)


class _RestMarker:
    """
    标记命令参数吃掉剩余输入。
    """


class _OptionMarker:
    """
    标记命令参数从 --name 形式解析。
    """


class _FlagMarker:
    """
    标记命令参数从 --name 布尔开关解析。
    """


class _ChoiceMarker:
    """
    标记命令参数只接受一组固定取值。
    """

    def __init__(self, choices: tuple[Any, ...]) -> None:
        self.choices = choices


_REST_MARKER = _RestMarker()
_OPTION_MARKER = _OptionMarker()
_FLAG_MARKER = _FlagMarker()


class Arg:
    """
    补充命令参数展示信息。
    """

    def __init__(
        self,
        *,
        alias: str | None = None,
        aliases: list[str] | tuple[str, ...] = (),
        description: str = "",
    ) -> None:
        self.aliases = _dedupe_aliases(alias, aliases)
        self.description = description


class Rest:
    """
    声明命令参数吃掉剩余输入，同时让类型检查器看到原始类型。
    """

    def __class_getitem__(cls, item: Any) -> Any:
        return Annotated[item, _REST_MARKER]


class Option:
    """
    声明命令参数从 --name 形式读取。
    """

    def __class_getitem__(cls, item: Any) -> Any:
        return Annotated[item, _OPTION_MARKER]


class Choice:
    """
    声明命令参数只接受一组固定取值。
    """

    def __class_getitem__(cls, item: Any) -> Any:
        choices = item if isinstance(item, tuple) else (item,)
        if not choices:
            raise TypeError("Choice[...] requires at least one value")
        base_type = _choice_base_type(choices)
        return Annotated[base_type, _ChoiceMarker(tuple(choices))]


Flag: TypeAlias = Annotated[bool, _FLAG_MARKER]


def _default_usage(path: str) -> str:
    normalized = _normalize_command_path(path)
    if not normalized:
        return ""
    return f"/{normalized}"


def _usage_from_arguments(
    path: str,
    arguments: list[PluginCommandArgumentDefinition],
) -> str:
    base_usage = _default_usage(path)
    parts = [base_usage] if base_usage else []
    for argument in arguments:
        parts.append(_usage_argument(argument))
    return " ".join(parts)


def _usage_argument(argument: PluginCommandArgumentDefinition) -> str:
    name = argument.name
    argument_type = _usage_argument_type(argument)
    type_suffix = "" if argument_type == "str" else f":{argument_type}"
    if argument.kind == PluginCommandArgumentKind.OPTION:
        option_name = _option_token(name)
        aliases = [option_name, *argument.aliases]
        option_display = "|".join(aliases)
        if argument.required:
            return f"<{option_display}{type_suffix}>"
        default = _format_usage_default(argument.default)
        if default is None:
            return f"[{option_display}{type_suffix}]"
        return f"[{option_display}{type_suffix}={default}]"
    if argument.kind == PluginCommandArgumentKind.FLAG:
        aliases = [_option_token(name), *argument.aliases]
        return f"[{'|'.join(aliases)}]"
    rest_suffix = "..." if argument.kind == PluginCommandArgumentKind.REST else ""
    if argument.required:
        return f"<{name}{type_suffix}{rest_suffix}>"
    default = _format_usage_default(argument.default)
    if default is None:
        return f"[{name}{type_suffix}{rest_suffix}]"
    return f"[{name}{type_suffix}{rest_suffix}={default}]"


def _format_usage_default(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _handler_description(handler: Any) -> str:
    doc = getattr(handler, "__doc__", None)
    if not doc:
        return ""
    return doc.strip().splitlines()[0].strip()


def _command_arguments_metadata(
    handler_signature: Signature,
    type_hints: dict[str, Any] | None = None,
) -> list[PluginCommandArgumentDefinition]:
    arguments: list[PluginCommandArgumentDefinition] = []
    seen_rest = False
    for parameter in handler_signature.parameters.values():
        if not _is_command_argument_parameter(parameter, type_hints):
            continue
        argument_kind = _command_argument_kind_for_parameter(parameter, type_hints)
        if seen_rest:
            if argument_kind in {
                PluginCommandArgumentKind.POSITIONAL,
                PluginCommandArgumentKind.REST,
            }:
                raise PluginConfigurationError(
                    f"插件命令 handler 的 Rest 参数后不能再声明位置参数: {parameter.name}"
                )

        argument_type = _command_argument_type_for_parameter(parameter, type_hints)
        if argument_type is None:
            continue

        metadata = _command_argument_metadata(parameter, type_hints)
        item = PluginCommandArgumentDefinition(
            name=parameter.name,
            type=argument_type.__name__,
            kind=argument_kind,
            required=parameter.default is _empty,
            aliases=list(metadata.aliases),
            choices=list(metadata.choices),
            description=metadata.description,
        )
        if parameter.default is not _empty:
            item = item.model_copy(
                update={"default": _metadata_default(parameter.default)}
            )
        arguments.append(item)
        seen_rest = seen_rest or argument_kind == PluginCommandArgumentKind.REST
    return arguments


def _metadata_default(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _build_handler_arguments(
    handler_signature: Signature,
    request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest,
    runtime_context: Any,
    *,
    usage: str | None = None,
    type_hints: dict[str, Any] | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    slot_index = 0
    command_arg_index = 0
    has_command_arguments = False
    parsed_command_args = None
    if isinstance(request, PluginCommandRequest):
        parsed_command_args = _parse_command_arguments(
            handler_signature,
            request,
            type_hints,
            usage,
        )

    for parameter in handler_signature.parameters.values():
        if parameter.kind in {
            Parameter.VAR_POSITIONAL,
            Parameter.VAR_KEYWORD,
        }:
            raise PluginConfigurationError("插件命令 handler 不支持 *args 或 **kwargs")

        value = _resolve_handler_parameter(
            parameter,
            request,
            runtime_context,
            slot_index,
            command_arg_index,
            usage,
            type_hints,
            parsed_command_args,
        )
        if value is _UNSET:
            continue

        is_command_argument = _is_command_argument_value(parameter, request, type_hints)
        if is_command_argument:
            argument_kind = _command_argument_kind_for_parameter(parameter, type_hints)
            if argument_kind == PluginCommandArgumentKind.REST:
                command_arg_index = len(parsed_command_args.positionals)
            elif argument_kind in {
                PluginCommandArgumentKind.OPTION,
                PluginCommandArgumentKind.FLAG,
            }:
                pass
            else:
                command_arg_index += 1
            has_command_arguments = True

        if parameter.default is _empty and not is_command_argument:
            slot_index = _advance_slot_index(
                slot_index,
                value,
                request,
                runtime_context,
            )

        if parameter.kind is Parameter.POSITIONAL_ONLY:
            args.append(value)
        else:
            kwargs[parameter.name] = value

    if (
        has_command_arguments
        and isinstance(request, PluginCommandRequest)
        and parsed_command_args is not None
        and command_arg_index < len(parsed_command_args.positionals)
    ):
        raise PluginInputError(
            _format_command_input_error(
                f"插件命令 {request.command.name} 参数过多: "
                f"{' '.join(parsed_command_args.positionals[command_arg_index:])}",
                usage,
            )
        )

    return args, kwargs


def _validate_handler_signature(
    handler_signature: Signature,
    runtime_context: Any,
    handler_label: str = "插件命令",
    type_hints: dict[str, Any] | None = None,
) -> None:
    slot_index = 0
    for parameter in handler_signature.parameters.values():
        if parameter.kind in {
            Parameter.VAR_POSITIONAL,
            Parameter.VAR_KEYWORD,
        }:
            raise PluginConfigurationError(
                f"{handler_label} handler 不支持 *args 或 **kwargs"
            )
        if isinstance(parameter.default, PluginDependency):
            _resolve_dependency(parameter.default, runtime_context)
            continue
        if (
            handler_label == "插件命令"
            and _command_argument_type_for_parameter(parameter, type_hints) is not None
        ):
            continue
        if parameter.default is not _empty:
            continue
        if parameter.name == "request":
            slot_index = max(slot_index, 1)
            continue
        if parameter.name in {"ctx", "context"}:
            slot_index = max(slot_index, 2)
            continue
        if slot_index < 2:
            slot_index += 1
            continue
        raise PluginConfigurationError(
            f"{handler_label} handler 参数 {parameter.name} 无法注入"
        )


def _resolve_handler_parameter(
    parameter: Parameter,
    request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest,
    runtime_context: Any,
    slot_index: int,
    command_arg_index: int,
    usage: str | None,
    type_hints: dict[str, Any] | None,
    parsed_command_args: "_ParsedCommandArguments | None",
) -> Any:
    if isinstance(parameter.default, PluginDependency):
        return _resolve_dependency(parameter.default, runtime_context, request)

    if parameter.name == "request":
        return request
    if parameter.name == "event" and isinstance(request, PluginEventRequest):
        return request.event
    if parameter.name in {"ctx", "context"}:
        return runtime_context
    if _is_command_argument_value(parameter, request, type_hints):
        if parsed_command_args is None:
            raise PluginConfigurationError("插件命令参数解析状态缺失")
        return _resolve_command_argument(
            parameter,
            request,
            command_arg_index,
            usage,
            type_hints,
            parsed_command_args,
        )
    if parameter.default is not _empty:
        return _UNSET

    positional_slots = (request, runtime_context)
    if slot_index >= len(positional_slots):
        raise PluginConfigurationError(
            f"插件命令 handler 参数 {parameter.name} 无法注入"
        )
    return positional_slots[slot_index]


def _resolve_command_argument(
    parameter: Parameter,
    request: PluginCommandRequest,
    command_arg_index: int,
    usage: str | None,
    type_hints: dict[str, Any] | None,
    parsed_command_args: "_ParsedCommandArguments",
) -> Any:
    argument_type = _command_argument_type_for_parameter(parameter, type_hints)
    if argument_type is None:
        raise PluginConfigurationError(
            f"插件命令 handler 参数 {parameter.name} 不支持从命令参数解析"
        )
    argument_kind = _command_argument_kind_for_parameter(parameter, type_hints)
    if argument_kind == PluginCommandArgumentKind.REST:
        return _resolve_rest_command_argument(
            parameter,
            request,
            command_arg_index,
            usage,
            type_hints,
            parsed_command_args,
        )
    if argument_kind in {
        PluginCommandArgumentKind.OPTION,
        PluginCommandArgumentKind.FLAG,
    }:
        return _resolve_named_command_argument(
            parameter,
            request,
            usage,
            type_hints,
            parsed_command_args,
        )
    if command_arg_index >= len(parsed_command_args.positionals):
        if parameter.default is not _empty:
            return _UNSET
        raise PluginInputError(
            _format_command_input_error(
                f"插件命令 {request.command.name} 缺少参数 {parameter.name}",
                usage,
            )
        )

    raw_value = parsed_command_args.positionals[command_arg_index]
    try:
        value = _parse_command_argument(raw_value, argument_type)
    except ValueError as exc:
        raise PluginInputError(
            _format_command_input_error(
                f"插件命令 {request.command.name} 参数 {parameter.name} "
                f"应为 {argument_type.__name__}，收到 {raw_value!r}",
                usage,
            )
        ) from exc
    _validate_command_argument_choice(parameter, request, value, usage, type_hints)
    return value


def _resolve_rest_command_argument(
    parameter: Parameter,
    request: PluginCommandRequest,
    command_arg_index: int,
    usage: str | None,
    type_hints: dict[str, Any] | None,
    parsed_command_args: "_ParsedCommandArguments",
) -> Any:
    argument_type = _command_argument_type_for_parameter(parameter, type_hints)
    if argument_type is not str:
        raise PluginConfigurationError(
            f"插件命令 Rest 参数 {parameter.name} 目前只支持 Rest[str]"
        )
    if command_arg_index >= len(parsed_command_args.positionals):
        if parameter.default is not _empty:
            return _UNSET
        raise PluginInputError(
            _format_command_input_error(
                f"插件命令 {request.command.name} 缺少参数 {parameter.name}",
                usage,
            )
        )
    return " ".join(parsed_command_args.positionals[command_arg_index:])


def _resolve_named_command_argument(
    parameter: Parameter,
    request: PluginCommandRequest,
    usage: str | None,
    type_hints: dict[str, Any] | None,
    parsed_command_args: "_ParsedCommandArguments",
) -> Any:
    argument_kind = _command_argument_kind_for_parameter(parameter, type_hints)
    argument_type = _command_argument_type_for_parameter(parameter, type_hints)
    if argument_kind == PluginCommandArgumentKind.FLAG:
        if parameter.name not in parsed_command_args.options:
            return _UNSET
        raw_value = parsed_command_args.options[parameter.name]
        try:
            return _parse_command_argument(raw_value, bool)
        except ValueError as exc:
            raise PluginInputError(
                _format_command_input_error(
                    f"插件命令 {request.command.name} 参数 {parameter.name} "
                    f"应为 bool，收到 {raw_value!r}",
                    usage,
                )
            ) from exc

    if parameter.name not in parsed_command_args.options:
        if parameter.default is not _empty:
            return _UNSET
        raise PluginInputError(
            _format_command_input_error(
                f"插件命令 {request.command.name} 缺少参数 {parameter.name}",
                usage,
            )
        )

    raw_value = parsed_command_args.options[parameter.name]
    try:
        value = _parse_command_argument(raw_value, argument_type)
    except ValueError as exc:
        raise PluginInputError(
            _format_command_input_error(
                f"插件命令 {request.command.name} 参数 {parameter.name} "
                f"应为 {argument_type.__name__}，收到 {raw_value!r}",
                usage,
            )
        ) from exc
    _validate_command_argument_choice(parameter, request, value, usage, type_hints)
    return value


def _parse_command_arguments(
    handler_signature: Signature,
    request: PluginCommandRequest,
    type_hints: dict[str, Any] | None,
    usage: str | None,
) -> "_ParsedCommandArguments":
    option_names: dict[str, Parameter] = {}
    option_parameters: set[str] = set()
    flag_parameters: set[str] = set()
    for parameter in handler_signature.parameters.values():
        if not _is_command_argument_parameter(parameter, type_hints):
            continue
        argument_kind = _command_argument_kind_for_parameter(parameter, type_hints)
        if argument_kind not in {
            PluginCommandArgumentKind.OPTION,
            PluginCommandArgumentKind.FLAG,
        }:
            continue
        option_parameters.add(parameter.name)
        if argument_kind == PluginCommandArgumentKind.FLAG:
            flag_parameters.add(parameter.name)
        for option_name in _command_option_names(parameter, type_hints):
            option_names[option_name] = parameter

    positionals: list[str] = []
    options: dict[str, str] = {}
    raw_args = list(request.command.args)
    index = 0
    while index < len(raw_args):
        raw_arg = raw_args[index]
        option_token, separator, inline_value = raw_arg.partition("=")
        parameter = option_names.get(option_token)
        if parameter is None:
            if option_names and _looks_like_option_token(option_token):
                raise PluginInputError(
                    _format_command_input_error(
                        f"插件命令 {request.command.name} 未知参数 {option_token}",
                        usage,
                    )
                )
            positionals.append(raw_arg)
            index += 1
            continue

        if parameter.name in options:
            raise PluginInputError(
                _format_command_input_error(
                    f"插件命令 {request.command.name} 参数 {parameter.name} 重复",
                    usage,
                )
            )

        if parameter.name in flag_parameters:
            options[parameter.name] = inline_value if separator else "true"
            index += 1
            continue

        if separator:
            if inline_value == "":
                raise PluginInputError(
                    _format_command_input_error(
                        f"插件命令 {request.command.name} 参数 {parameter.name} 缺少值",
                        usage,
                    )
                )
            options[parameter.name] = inline_value
            index += 1
            continue

        value_index = index + 1
        if value_index >= len(raw_args):
            raise PluginInputError(
                _format_command_input_error(
                    f"插件命令 {request.command.name} 参数 {parameter.name} 缺少值",
                    usage,
                )
            )
        if _looks_like_option_token(raw_args[value_index]):
            raise PluginInputError(
                _format_command_input_error(
                    f"插件命令 {request.command.name} 参数 {parameter.name} 缺少值",
                    usage,
                )
            )
        options[parameter.name] = raw_args[value_index]
        index += 2

    return _ParsedCommandArguments(
        positionals=tuple(positionals),
        options=options,
    )


def _command_option_names(
    parameter: Parameter,
    type_hints: dict[str, Any] | None,
) -> tuple[str, ...]:
    metadata = _command_argument_metadata(parameter, type_hints)
    return (_option_token(parameter.name), *metadata.aliases)


def _format_command_input_error(message: str, usage: str | None) -> str:
    if not usage:
        return message
    return f"{message}；用法: {usage}"


def _parse_command_argument(raw_value: str, argument_type: type) -> Any:
    if argument_type is str:
        return raw_value
    if argument_type is int:
        return int(raw_value)
    if argument_type is float:
        return float(raw_value)
    if argument_type is bool:
        return _parse_bool_argument(raw_value)
    raise ValueError(f"unsupported argument type: {argument_type}")


def _parse_bool_argument(raw_value: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid bool value: {raw_value}")


def _validate_command_argument_choice(
    parameter: Parameter,
    request: PluginCommandRequest,
    value: Any,
    usage: str | None,
    type_hints: dict[str, Any] | None,
) -> None:
    choices = _command_argument_metadata(parameter, type_hints).choices
    if not choices or value in choices:
        return
    expected = ", ".join(repr(choice) for choice in choices)
    raise PluginInputError(
        _format_command_input_error(
            f"插件命令 {request.command.name} 参数 {parameter.name} "
            f"必须是 {expected}，收到 {value!r}",
            usage,
        )
    )


def _is_command_argument_value(
    parameter: Parameter,
    request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest,
    type_hints: dict[str, Any] | None,
) -> bool:
    return (
        isinstance(request, PluginCommandRequest)
        and _is_command_argument_parameter(parameter, type_hints)
    )


def _is_command_argument_parameter(
    parameter: Parameter,
    type_hints: dict[str, Any] | None = None,
) -> bool:
    return (
        _command_argument_type_for_parameter(parameter, type_hints) is not None
        and not isinstance(parameter.default, PluginDependency)
        and parameter.kind
        in {
            Parameter.POSITIONAL_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
            Parameter.KEYWORD_ONLY,
        }
    )


def _command_argument_type_for_parameter(
    parameter: Parameter,
    type_hints: dict[str, Any] | None = None,
) -> type | None:
    if parameter.name in {"request", "ctx", "context"}:
        return None
    annotation = _parameter_annotation(parameter, type_hints)
    marked_argument_type = _marked_argument_type(annotation)
    if marked_argument_type is _INVALID_MARKED_ARGUMENT:
        raise PluginConfigurationError(
            f"插件命令参数 {parameter.name} 的标记类型不支持"
        )
    if marked_argument_type is not None:
        return marked_argument_type
    return _command_argument_type(
        annotation
    ) or _command_argument_type_from_default(parameter) or str


def _command_argument_kind_for_parameter(
    parameter: Parameter,
    type_hints: dict[str, Any] | None = None,
) -> PluginCommandArgumentKind:
    metadata = _command_argument_metadata(parameter, type_hints)
    if metadata.is_rest:
        return PluginCommandArgumentKind.REST
    if metadata.is_option:
        return PluginCommandArgumentKind.OPTION
    if metadata.is_flag:
        return PluginCommandArgumentKind.FLAG
    return PluginCommandArgumentKind.POSITIONAL


def _command_argument_metadata(
    parameter: Parameter,
    type_hints: dict[str, Any] | None = None,
) -> "_CommandArgumentMetadata":
    annotation = _parameter_annotation(parameter, type_hints)
    metadata = _annotation_metadata(annotation)
    if metadata.invalid_marker:
        raise PluginConfigurationError(
            f"插件命令参数 {parameter.name} 的标记类型不支持"
        )
    return metadata


def _marked_argument_type(annotation: Any) -> type | object | None:
    metadata = _annotation_metadata(annotation)
    if metadata.invalid_marker:
        return _INVALID_MARKED_ARGUMENT
    if metadata.base_type is not None:
        return metadata.base_type
    return _string_marked_argument_type(annotation)


def _annotation_metadata(annotation: Any) -> "_CommandArgumentMetadata":
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if not args:
            return _CommandArgumentMetadata()
        base_type = args[0]
        metadata = args[1:]
        result = _CommandArgumentMetadata()
        if any(isinstance(item, _RestMarker) for item in metadata):
            result.is_rest = True
            result.base_type = base_type
        if any(isinstance(item, _OptionMarker) for item in metadata):
            result.is_option = True
            result.base_type = base_type
        if any(isinstance(item, _FlagMarker) for item in metadata):
            result.is_flag = True
            result.base_type = bool
        for item in metadata:
            if isinstance(item, _ChoiceMarker):
                result.choices = item.choices
                result.base_type = _choice_base_type(item.choices)
        for item in metadata:
            if isinstance(item, Arg):
                result.aliases = item.aliases
                result.description = item.description
        if result.is_rest and result.base_type is not str:
            result.invalid_marker = True
        if result.is_flag and result.base_type is not bool:
            result.invalid_marker = True
        if result.choices and result.base_type not in {str, int, float, bool}:
            result.invalid_marker = True
        return result
    if isinstance(annotation, str):
        normalized = annotation.replace(" ", "")
        result = _CommandArgumentMetadata()
        if "Rest[" in normalized or normalized.endswith("Rest"):
            result.is_rest = True
            marked_type = _string_generic_argument_type(normalized, "Rest")
            result.base_type = marked_type if isinstance(marked_type, type) else str
            result.invalid_marker = marked_type is _INVALID_MARKED_ARGUMENT
        if "Option[" in normalized:
            result.is_option = True
            marked_type = _string_generic_argument_type(normalized, "Option")
            result.base_type = marked_type if isinstance(marked_type, type) else None
            result.invalid_marker = marked_type is _INVALID_MARKED_ARGUMENT
        if normalized.endswith("Flag") or "Flag," in normalized or "Flag]" in normalized:
            result.is_flag = True
            result.base_type = bool
        return result
    return _CommandArgumentMetadata()


def _string_marked_argument_type(annotation: Any) -> type | object | None:
    if isinstance(annotation, str):
        normalized = annotation.replace(" ", "")
        if normalized.endswith("Rest") or "Flag" in normalized:
            return bool if "Flag" in normalized else str
        if "Rest[" in normalized:
            return _string_generic_argument_type(normalized, "Rest")
        if "Option[" in normalized:
            return _string_generic_argument_type(normalized, "Option")
    return None


def _string_generic_argument_type(annotation: str, name: str) -> type | object | None:
    prefix = f"{name}["
    index = annotation.find(prefix)
    if index < 0:
        return None
    start = index + len(prefix)
    end = annotation.find("]", start)
    if end < 0:
        return _INVALID_MARKED_ARGUMENT
    inner = annotation[start:end]
    if inner in {"str", "builtins.str"}:
        return str
    if inner in {"int", "builtins.int"}:
        return int
    if inner in {"float", "builtins.float"}:
        return float
    if inner in {"bool", "builtins.bool"}:
        return bool
    return _INVALID_MARKED_ARGUMENT


def _parameter_annotation(
    parameter: Parameter,
    type_hints: dict[str, Any] | None,
) -> Any:
    if type_hints and parameter.name in type_hints:
        return type_hints[parameter.name]
    return parameter.annotation


def _handler_type_hints(handler: Any) -> dict[str, Any]:
    try:
        return get_type_hints(handler, include_extras=True)
    except Exception:
        return {}


def _option_token(name: str) -> str:
    return f"--{name.replace('_', '-')}"


def _usage_argument_type(argument: PluginCommandArgumentDefinition) -> str:
    if not argument.choices:
        return argument.type
    return "|".join(str(choice) for choice in argument.choices)


def _dedupe_aliases(
    alias: str | None,
    aliases: list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    values = [item for item in (alias, *aliases) if item]
    return tuple(dict.fromkeys(values))


def _choice_base_type(choices: tuple[Any, ...]) -> type:
    first_type = type(choices[0])
    if first_type is bool:
        return bool
    if first_type in {str, int, float} and all(
        type(choice) is first_type for choice in choices
    ):
        return first_type
    return str


def _looks_like_option_token(value: str) -> bool:
    if value.startswith("--") and len(value) > 2:
        return True
    if not value.startswith("-") or len(value) <= 1:
        return False
    return not _looks_like_number(value)


def _looks_like_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


class _CommandArgumentMetadata:
    def __init__(self) -> None:
        self.is_rest = False
        self.is_option = False
        self.is_flag = False
        self.invalid_marker = False
        self.base_type: type | None = None
        self.aliases: tuple[str, ...] = ()
        self.choices: tuple[Any, ...] = ()
        self.description = ""


class _ParsedCommandArguments:
    def __init__(
        self,
        *,
        positionals: tuple[str, ...],
        options: dict[str, str],
    ) -> None:
        self.positionals = positionals
        self.options = options


def _command_argument_type(annotation: Any) -> type | None:
    if annotation in {str, int, float, bool}:
        return annotation
    if isinstance(annotation, str):
        return {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
        }.get(annotation.strip())
    return None


def _command_argument_type_from_default(parameter: Parameter) -> type | None:
    if parameter.default is _empty:
        return None
    if isinstance(parameter.default, bool):
        return bool
    if isinstance(parameter.default, int):
        return int
    if isinstance(parameter.default, float):
        return float
    if isinstance(parameter.default, str):
        return str
    return str


def _normalize_command_path(value: str) -> str:
    stripped = value.strip().removeprefix("/")
    if not stripped:
        return ""
    return " ".join(stripped.replace("/", " ").split()).lower()


def _advance_slot_index(
    slot_index: int,
    value: Any,
    request: PluginCommandRequest | PluginTaskRequest | PluginEventRequest,
    runtime_context: Any,
) -> int:
    if value is request:
        return max(slot_index, 1)
    if value is runtime_context:
        return max(slot_index, 2)
    return slot_index + 1


class _Unset:
    pass


_UNSET = _Unset()
_INVALID_MARKED_ARGUMENT = object()
_empty = Signature.empty
