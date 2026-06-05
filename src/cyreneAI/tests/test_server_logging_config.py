from __future__ import annotations

import json
import logging

import pytest

from cyreneAI.server.logging_config import (
    CyreneAIJsonFormatter,
    CyreneAILogContextFilter,
    CyreneAITextFormatter,
    bind_log_context,
    build_logging_config,
    build_logging_config_from_env,
    build_request_id_header_from_env,
    build_request_logging_enabled_from_env,
    get_log_context,
)


def test_server_builds_default_logging_config_from_env(monkeypatch) -> None:
    for name in [
        "CYRENEAI_LOG_LEVEL",
        "CYRENEAI_LOG_FORMAT",
        "CYRENEAI_LOG_ACCESS_ENABLED",
        "CYRENEAI_LOG_FILE_PATH",
        "CYRENEAI_LOG_DIR",
        "CYRENEAI_LOG_FILE_LEVEL",
        "CYRENEAI_LOG_FILE_MAX_BYTES",
        "CYRENEAI_LOG_FILE_BACKUP_COUNT",
        "CYRENEAI_LOG_REQUESTS_ENABLED",
        "CYRENEAI_REQUEST_ID_HEADER",
    ]:
        monkeypatch.setenv(name, "")

    config = build_logging_config_from_env()

    assert config["root"]["level"] == "INFO"
    assert config["root"]["handlers"] == ["console"]
    assert "file" not in config["handlers"]
    assert config["handlers"]["console"]["formatter"] == "text"
    assert (
        config["formatters"]["text"]["()"]
        == "cyreneAI.server.logging_config.CyreneAITextFormatter"
    )
    assert config["handlers"]["console"]["filters"] == ["context"]
    assert config["loggers"]["cyreneAI"]["propagate"] is True
    assert config["loggers"]["uvicorn.error"]["level"] == "INFO"
    assert config["loggers"]["uvicorn.access"]["propagate"] is True
    assert config["loggers"]["cyreneAI.server.startup"]["level"] == "INFO"
    assert config["loggers"]["cyreneAI.server.requests"]["level"] == "INFO"
    assert build_request_logging_enabled_from_env() is True
    assert build_request_id_header_from_env() == "X-Request-ID"


def test_server_builds_json_file_logging_config_from_env(
    monkeypatch,
    tmp_path,
) -> None:
    log_path = tmp_path / "log" / "cyreneai.log"
    monkeypatch.setenv("CYRENEAI_LOG_LEVEL", "debug")
    monkeypatch.setenv("CYRENEAI_LOG_FORMAT", "json")
    monkeypatch.setenv("CYRENEAI_LOG_ACCESS_ENABLED", "false")
    monkeypatch.setenv("CYRENEAI_LOG_FILE_PATH", str(log_path))
    monkeypatch.setenv("CYRENEAI_LOG_FILE_LEVEL", "warning")
    monkeypatch.setenv("CYRENEAI_LOG_FILE_MAX_BYTES", "2048")
    monkeypatch.setenv("CYRENEAI_LOG_FILE_BACKUP_COUNT", "2")

    config = build_logging_config_from_env()

    assert log_path.parent.exists()
    assert config["root"]["level"] == "DEBUG"
    assert config["root"]["handlers"] == ["console", "file"]
    assert config["handlers"]["console"]["formatter"] == "json"
    assert config["handlers"]["file"]["filename"] == str(log_path)
    assert config["handlers"]["file"]["level"] == "WARNING"
    assert config["handlers"]["file"]["filters"] == ["context"]
    assert config["handlers"]["file"]["maxBytes"] == 2048
    assert config["handlers"]["file"]["backupCount"] == 2
    assert config["loggers"]["uvicorn.access"]["level"] == "CRITICAL"
    assert config["loggers"]["uvicorn.access"]["propagate"] is False


def test_server_builds_file_logging_config_from_log_dir(monkeypatch, tmp_path) -> None:
    log_dir = tmp_path / "log"
    monkeypatch.setenv("CYRENEAI_LOG_FILE_PATH", "")
    monkeypatch.setenv("CYRENEAI_LOG_DIR", str(log_dir))

    config = build_logging_config_from_env()

    assert config["handlers"]["file"]["filename"] == str(log_dir / "cyreneai.log")


def test_server_builds_request_logging_settings_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_LOG_REQUESTS_ENABLED", "false")
    monkeypatch.setenv("CYRENEAI_REQUEST_ID_HEADER", "X-Trace-ID")

    assert build_request_logging_enabled_from_env() is False
    assert build_request_id_header_from_env() == "X-Trace-ID"


def test_server_logging_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        build_logging_config(level="loud")

    with pytest.raises(ValueError):
        build_logging_config(log_format="xml")  # type: ignore[arg-type]


def test_server_json_formatter_includes_extra_fields_and_redacts_sensitive_values() -> (
    None
):
    record = logging.LogRecord(
        name="cyreneAI.demo",
        level=logging.INFO,
        pathname="demo.py",
        lineno=7,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.request_id = "req-1"
    record.plugin_id = "demo.hello"
    record.api_key = "secret-key"
    record.payload = {
        "authorization": "Bearer secret",
        "safe": "visible",
    }

    payload = json.loads(CyreneAIJsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "cyreneAI.demo"
    assert payload["message"] == "hello world"
    assert payload["line"] == 7
    assert payload["extra"]["request_id"] == "req-1"
    assert payload["extra"]["plugin_id"] == "demo.hello"
    assert payload["extra"]["api_key"] == "[REDACTED]"
    assert payload["extra"]["payload"] == {
        "authorization": "[REDACTED]",
        "safe": "visible",
    }


def test_server_log_context_filter_injects_context_fields() -> None:
    record = logging.LogRecord(
        name="cyreneAI.demo",
        level=logging.INFO,
        pathname="demo.py",
        lineno=7,
        msg="hello",
        args=(),
        exc_info=None,
    )

    with bind_log_context(
        request_id="req-2",
        http_method="GET",
        api_token="secret-token",
    ):
        assert get_log_context()["request_id"] == "req-2"
        assert CyreneAILogContextFilter().filter(record) is True

    payload = json.loads(CyreneAIJsonFormatter().format(record))

    assert payload["request_id"] == "req-2"
    assert payload["http_method"] == "GET"
    assert payload["api_token"] == "[REDACTED]"
    assert "extra" not in payload


def test_server_text_formatter_omits_empty_request_context() -> None:
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname="server.py",
        lineno=1,
        msg="Application startup complete.",
        args=(),
        exc_info=None,
    )
    assert CyreneAILogContextFilter().filter(record) is True

    text = CyreneAITextFormatter().format(record)

    assert "Application startup complete." in text
    assert "[uvicorn.server]" in text
    assert "[uvicorn.error]" not in text
    assert "request_id=-" not in text
    assert "request_id=" not in text


def test_server_json_formatter_aliases_uvicorn_error_logger() -> None:
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname="server.py",
        lineno=1,
        msg="Application startup complete.",
        args=(),
        exc_info=None,
    )

    payload = json.loads(CyreneAIJsonFormatter().format(record))

    assert payload["logger"] == "uvicorn.server"
    assert payload["logger_name"] == "uvicorn.error"


def test_server_text_formatter_includes_request_context_when_present() -> None:
    record = logging.LogRecord(
        name="cyreneAI.server.requests",
        level=logging.INFO,
        pathname="server.py",
        lineno=1,
        msg="HTTP request completed",
        args=(),
        exc_info=None,
    )

    with bind_log_context(
        request_id="req-3",
        http_method="GET",
        http_path="/health",
    ):
        assert CyreneAILogContextFilter().filter(record) is True

    text = CyreneAITextFormatter().format(record)

    assert "request_id=req-3" in text
    assert "http_method=GET" in text
    assert "http_path=/health" in text
