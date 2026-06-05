from __future__ import annotations

import json
import logging
import logging.config
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv

LogFormat = Literal["text", "json"]

_LOG_CONTEXT: ContextVar[dict[str, object]] = ContextVar(
    "cyreneai_log_context",
    default={},
)
_LOG_LEVELS = {
    "CRITICAL",
    "ERROR",
    "WARNING",
    "INFO",
    "DEBUG",
    "NOTSET",
}
_DEFAULT_FILE_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_FILE_BACKUP_COUNT = 5
_DEFAULT_REQUEST_ID_HEADER = "X-Request-ID"
_SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}
_LOG_RECORD_FIELDS = set(
    logging.LogRecord(
        name="",
        level=0,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    ).__dict__
)


class CyreneAILogContextFilter(logging.Filter):
    """
    Add contextvars-backed fields to every log record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        context = get_log_context()
        record.cyreneai_log_context = context
        record.request_id = str(context.get("request_id") or "")
        return True


class CyreneAITextFormatter(logging.Formatter):
    """
    Human-readable formatter that shows context only when it exists.
    """

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)s%(cyreneai_text_context)s "
            "[%(name)s] %(message)s"
        )

    def format(self, record: logging.LogRecord) -> str:
        had_text_context = hasattr(record, "cyreneai_text_context")
        old_text_context = getattr(record, "cyreneai_text_context", "")
        record.cyreneai_text_context = _format_text_context(_record_context(record))
        try:
            return super().format(record)
        finally:
            if had_text_context:
                record.cyreneai_text_context = old_text_context
            else:
                delattr(record, "cyreneai_text_context")


class CyreneAIJsonFormatter(logging.Formatter):
    """
    JSON formatter for production logs.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _record_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        payload.update(_record_context(record))
        extras = _record_extras(record)
        if extras:
            payload["extra"] = extras
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging_from_env() -> None:
    """
    Configure process logging from environment variables.
    """
    logging.config.dictConfig(build_logging_config_from_env())


@contextmanager
def bind_log_context(**fields: object) -> Iterator[None]:
    """
    Temporarily add fields to the current async/task logging context.
    """
    current = get_log_context()
    next_context = {
        **current,
        **{
            key: value
            for key, value in fields.items()
            if value is not None and value != ""
        },
    }
    token: Token[dict[str, object]] = _LOG_CONTEXT.set(next_context)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


def get_log_context() -> dict[str, object]:
    return dict(_LOG_CONTEXT.get())


def build_logging_config_from_env() -> dict[str, Any]:
    load_dotenv()

    level = _env_log_level("CYRENEAI_LOG_LEVEL", default="INFO")
    log_format = _env_log_format("CYRENEAI_LOG_FORMAT", default="text")
    access_enabled = _env_bool("CYRENEAI_LOG_ACCESS_ENABLED", default=True)
    file_path = _env_str("CYRENEAI_LOG_FILE_PATH")
    log_dir = _env_str("CYRENEAI_LOG_DIR")
    if file_path is None and log_dir is not None:
        file_path = str(Path(log_dir) / "cyreneai.log")

    return build_logging_config(
        level=level,
        log_format=log_format,
        access_enabled=access_enabled,
        file_path=file_path,
        file_level=_env_log_level("CYRENEAI_LOG_FILE_LEVEL", default=level),
        file_max_bytes=_env_int(
            "CYRENEAI_LOG_FILE_MAX_BYTES",
            default=_DEFAULT_FILE_MAX_BYTES,
        ),
        file_backup_count=_env_int(
            "CYRENEAI_LOG_FILE_BACKUP_COUNT",
            default=_DEFAULT_FILE_BACKUP_COUNT,
        ),
    )


def build_request_logging_enabled_from_env() -> bool:
    load_dotenv()

    return _env_bool("CYRENEAI_LOG_REQUESTS_ENABLED", default=True)


def build_request_id_header_from_env() -> str:
    load_dotenv()

    return _env_str("CYRENEAI_REQUEST_ID_HEADER") or _DEFAULT_REQUEST_ID_HEADER


def build_logging_config(
    *,
    level: str = "INFO",
    log_format: LogFormat = "text",
    access_enabled: bool = True,
    file_path: str | None = None,
    file_level: str | None = None,
    file_max_bytes: int = _DEFAULT_FILE_MAX_BYTES,
    file_backup_count: int = _DEFAULT_FILE_BACKUP_COUNT,
) -> dict[str, Any]:
    normalized_level = _normalize_log_level(level)
    normalized_file_level = _normalize_log_level(file_level or normalized_level)
    formatter_name = _normalize_log_format(log_format)
    handlers: dict[str, dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "level": normalized_level,
            "formatter": formatter_name,
            "filters": ["context"],
            "stream": "ext://sys.stderr",
        }
    }
    root_handlers = ["console"]

    if file_path is not None:
        _ensure_log_parent(file_path)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": normalized_file_level,
            "formatter": formatter_name,
            "filters": ["context"],
            "filename": file_path,
            "maxBytes": file_max_bytes,
            "backupCount": file_backup_count,
            "encoding": "utf-8",
        }
        root_handlers.append("file")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "context": {
                "()": "cyreneAI.server.logging_config.CyreneAILogContextFilter",
            },
        },
        "formatters": {
            "text": {
                "()": "cyreneAI.server.logging_config.CyreneAITextFormatter",
            },
            "json": {
                "()": "cyreneAI.server.logging_config.CyreneAIJsonFormatter",
            },
        },
        "handlers": handlers,
        "root": {
            "level": normalized_level,
            "handlers": root_handlers,
        },
        "loggers": {
            "cyreneAI": {
                "level": normalized_level,
                "handlers": [],
                "propagate": True,
            },
            "uvicorn": {
                "level": normalized_level,
                "handlers": [],
                "propagate": True,
            },
            "uvicorn.error": {
                "level": normalized_level,
                "handlers": [],
                "propagate": True,
            },
            "uvicorn.access": {
                "level": normalized_level if access_enabled else "CRITICAL",
                "handlers": [],
                "propagate": access_enabled,
            },
        },
    }


def _record_timestamp(record: logging.LogRecord) -> str:
    return (
        datetime.fromtimestamp(record.created, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    context_keys = set(_record_context(record))
    for key, value in record.__dict__.items():
        if (
            key in _LOG_RECORD_FIELDS
            or key in context_keys
            or key == "cyreneai_log_context"
            or key.startswith("_")
        ):
            continue
        extras[key] = _redact_value(key, value)
    return extras


def _record_context(record: logging.LogRecord) -> dict[str, Any]:
    context = getattr(record, "cyreneai_log_context", None)
    if not isinstance(context, dict):
        context = {}
    return {
        key: _redact_value(key, value)
        for key, value in cast(dict[str, object], context).items()
        if value is not None and value != ""
    }


def _format_text_context(context: dict[str, Any]) -> str:
    if not context:
        return ""
    ordered_keys = [
        "request_id",
        "http_method",
        "http_path",
        "client_ip",
        "status_code",
        "duration_ms",
    ]
    keys = [
        *[key for key in ordered_keys if key in context],
        *sorted(key for key in context if key not in ordered_keys),
    ]
    return "".join(f" {key}={context[key]}" for key in keys)


def _redact_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        items = cast(dict[object, object], value).items()
        return {
            str(item_key): _redact_value(str(item_key), item_value)
            for item_key, item_value in items
        }
    if isinstance(value, list):
        return [_redact_value(key, item) for item in cast(list[object], value)]
    if isinstance(value, tuple):
        values = cast(tuple[object, ...], value)
        return tuple(_redact_value(key, item) for item in values)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _ensure_log_parent(file_path: str) -> None:
    parent = Path(file_path).expanduser().parent
    if str(parent) in {"", "."}:
        return
    parent.mkdir(parents=True, exist_ok=True)


def _env_log_level(name: str, *, default: str) -> str:
    return _normalize_log_level(_env_str(name) or default)


def _normalize_log_level(value: str) -> str:
    level = value.strip().upper()
    if level not in _LOG_LEVELS:
        raise ValueError(f"{value} is not a valid log level")
    return level


def _env_log_format(name: str, *, default: LogFormat) -> LogFormat:
    return _normalize_log_format(_env_str(name) or default)


def _normalize_log_format(value: str) -> LogFormat:
    log_format = value.strip().lower()
    if log_format not in {"text", "json"}:
        raise ValueError("log format must be text or json")
    return cast(LogFormat, log_format)


def _env_bool(name: str, *, default: bool) -> bool:
    raw = _env_str(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int) -> int:
    raw = _env_str(name)
    if raw is None:
        return default
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _env_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


__all__ = [
    "CyreneAILogContextFilter",
    "CyreneAIJsonFormatter",
    "CyreneAITextFormatter",
    "bind_log_context",
    "build_logging_config",
    "build_logging_config_from_env",
    "build_request_id_header_from_env",
    "build_request_logging_enabled_from_env",
    "configure_logging_from_env",
    "get_log_context",
]
