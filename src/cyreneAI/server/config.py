from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any, Literal, cast

from dotenv import load_dotenv

from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.core.schema.server import ServerSettings
from cyreneAI.core.schema.tool import MCPStdioServerConfig


def build_server_settings_from_env() -> ServerSettings:
    load_dotenv()

    return ServerSettings(
        admin_username=os.getenv("CYRENEAI_ADMIN_USERNAME"),
        admin_password=os.getenv("CYRENEAI_ADMIN_PASSWORD"),
        auth_enabled=_env_bool("CYRENEAI_AUTH_ENABLED", default=True),
        session_secret=os.getenv("CYRENEAI_SESSION_SECRET"),
        session_cookie_name=os.getenv(
            "CYRENEAI_SESSION_COOKIE_NAME",
            "cyrene_admin_session",
        ),
        session_ttl_seconds=int(os.getenv("CYRENEAI_SESSION_TTL_SECONDS", "43200")),
    )


def build_telegram_bot_token_from_env() -> str | None:
    load_dotenv()

    return _env_str("TELEGRAM_BOT_TOKEN") or _env_str("BOT_TOKEN")


def build_telegram_webhook_secret_from_env() -> str | None:
    load_dotenv()

    return _env_str("TELEGRAM_SECRET_TOKEN") or _env_str(
        "TELEGRAM_BOT_SECRET_TOKEN"
    )


def build_telegram_webhook_provider_id_from_env() -> str | None:
    load_dotenv()

    telegram_provider_id = _env_str("TELEGRAM_BOT_PROVIDER_ID")
    if telegram_provider_id:
        return telegram_provider_id

    if _env_str("OPENAI_COMPATIBLE_API_KEY") or _env_str("OPENAI_API_KEY"):
        return _env_str("OPENAI_COMPATIBLE_PROVIDER_ID") or "openai-compatible"

    if _env_str("OPENAI_RESPONSES_API_KEY"):
        return _env_str("OPENAI_RESPONSES_PROVIDER_ID") or "openai"

    return _env_str("OPENAI_PROVIDER_ID")


def build_telegram_webhook_model_from_env() -> str | None:
    load_dotenv()

    return (
        _env_str("TELEGRAM_BOT_MODEL")
        or _env_str("OPENAI_COMPATIBLE_MODEL")
        or _env_str("OPENAI_RESPONSES_MODEL")
        or _env_str("OPENAI_MODEL")
    )


def build_telegram_polling_enabled_from_env() -> bool:
    load_dotenv()

    return (_env_str("TELEGRAM_BOT_MODE") or "").lower() == "polling"


def build_telegram_polling_interval_seconds_from_env() -> float:
    load_dotenv()

    return float(os.getenv("TELEGRAM_BOT_POLL_INTERVAL_SECONDS", "1"))


def build_telegram_polling_timeout_seconds_from_env() -> int:
    load_dotenv()

    return int(os.getenv("TELEGRAM_BOT_POLL_TIMEOUT_SECONDS", "30"))


def build_telegram_polling_limit_from_env() -> int | None:
    load_dotenv()

    raw = _env_str("TELEGRAM_BOT_POLL_LIMIT")
    if raw is None:
        return None
    return int(raw)


def build_bot_polling_state_database_path_from_env() -> str | None:
    load_dotenv()

    return _env_str("CYRENEAI_BOT_POLLING_STATE_DATABASE_PATH")


def build_context_database_path_from_env() -> str | None:
    load_dotenv()

    return _env_str("CYRENEAI_CONTEXT_DATABASE_PATH") or "data/context.db"


def build_vector_database_path_from_env() -> str | None:
    load_dotenv()

    return _env_str("CYRENEAI_VECTOR_DATABASE_PATH") or "data/vector.db"


def build_tool_sandbox_mode_from_env() -> Literal["in_process", "subprocess"] | None:
    load_dotenv()

    mode = _env_str("CYRENEAI_TOOL_SANDBOX_MODE")
    if mode is None:
        return None
    if mode not in {"in_process", "subprocess"}:
        raise ValueError("CYRENEAI_TOOL_SANDBOX_MODE must be in_process or subprocess")
    return cast(Literal["in_process", "subprocess"], mode)


def build_tool_sandbox_commands_from_env() -> dict[str, list[str]] | None:
    load_dotenv()

    raw = _env_str("CYRENEAI_TOOL_SANDBOX_COMMANDS_JSON")
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("CYRENEAI_TOOL_SANDBOX_COMMANDS_JSON must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("CYRENEAI_TOOL_SANDBOX_COMMANDS_JSON must be a JSON object")

    commands: dict[str, list[str]] = {}
    for name, command in cast(dict[str, Any], parsed).items():
        if not isinstance(name, str) or not name:
            raise ValueError("tool sandbox command names must be non-empty strings")
        if not isinstance(command, list) or not command:
            raise ValueError("tool sandbox commands must be non-empty arrays")
        command_items: list[str] = []
        for item in cast(list[Any], command):
            if not isinstance(item, str) or not item:
                raise ValueError("tool sandbox command items must be non-empty strings")
            command_items.append(item)
        commands[name] = command_items
    return commands


def build_tool_sandbox_timeout_seconds_from_env() -> float | None:
    load_dotenv()

    raw = _env_str("CYRENEAI_TOOL_SANDBOX_TIMEOUT_SECONDS")
    if raw is None:
        return None
    return float(raw)


def build_mcp_stdio_servers_from_env() -> list[MCPStdioServerConfig]:
    load_dotenv()

    raw = _env_str("CYRENEAI_MCP_STDIO_SERVERS_JSON")
    if raw is None:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("CYRENEAI_MCP_STDIO_SERVERS_JSON must be valid JSON") from exc
    if not isinstance(parsed, list):
        raise ValueError("CYRENEAI_MCP_STDIO_SERVERS_JSON must be a JSON array")
    return [
        MCPStdioServerConfig.model_validate(item)
        for item in parsed
        if isinstance(item, dict)
    ]


def build_web_search_url_template_from_env() -> str | None:
    load_dotenv()

    return _env_str("CYRENEAI_WEB_SEARCH_URL_TEMPLATE")


def build_web_search_api_key_from_env() -> str | None:
    load_dotenv()

    return _env_str("CYRENEAI_WEB_SEARCH_API_KEY")


def build_web_search_api_key_header_from_env() -> str:
    load_dotenv()

    return _env_str("CYRENEAI_WEB_SEARCH_API_KEY_HEADER") or "Authorization"


def build_web_search_timeout_seconds_from_env() -> float:
    load_dotenv()

    raw = _env_str("CYRENEAI_WEB_SEARCH_TIMEOUT_SECONDS")
    if raw is None:
        return 10.0
    return float(raw)


def build_plugin_paths_from_env() -> list[str]:
    load_dotenv()

    raw = _env_str("CYRENEAI_PLUGIN_PATH")
    if raw is None:
        return []
    separator = ";" if ";" in raw else os.pathsep
    return [
        part.strip()
        for part in raw.split(separator)
        if part.strip()
    ]


def build_plugin_storage_path_from_env() -> str | None:
    load_dotenv()

    return _env_str("CYRENEAI_PLUGIN_STORAGE_PATH")


def build_plugin_task_database_path_from_env() -> str | None:
    load_dotenv()

    return _env_str("CYRENEAI_PLUGIN_TASK_DATABASE_PATH")


def build_disabled_plugin_ids_from_env() -> list[str]:
    load_dotenv()

    raw = _env_str("CYRENEAI_DISABLED_PLUGINS")
    if raw is None:
        return []
    return [
        part.strip()
        for part in raw.replace(";", ",").split(",")
        if part.strip()
    ]


def build_provider_configs_from_env() -> list[ProviderConfig]:
    load_dotenv()

    configs: list[ProviderConfig] = []
    timeout = timedelta(seconds=int(os.getenv("CYRENE_PROVIDER_TIMEOUT_SECONDS", "60")))

    openai_compatible_key = os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv(
        "OPENAI_API_KEY"
    )
    if openai_compatible_key:
        configs.append(
            ProviderConfig(
                provider_id=os.getenv(
                    "OPENAI_COMPATIBLE_PROVIDER_ID",
                    "openai-compatible",
                ),
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key=openai_compatible_key,
                base_url=os.getenv("OPENAI_COMPATIBLE_BASE_URL")
                or os.getenv("OPENAI_BASE_URL"),
                timeout=timeout,
            )
        )

    openai_responses_key = os.getenv("OPENAI_RESPONSES_API_KEY") or os.getenv(
        "OPENAI_API_KEY"
    )
    if openai_responses_key:
        configs.append(
            ProviderConfig(
                provider_id=os.getenv("OPENAI_RESPONSES_PROVIDER_ID", "openai"),
                provider_type=ProviderType.OPENAI_RESPONSES,
                api_key=openai_responses_key,
                base_url=os.getenv("OPENAI_RESPONSES_BASE_URL")
                or os.getenv("OPENAI_BASE_URL"),
                timeout=timeout,
            )
        )

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        configs.append(
            ProviderConfig(
                provider_id=os.getenv("ANTHROPIC_PROVIDER_ID", "anthropic"),
                provider_type=ProviderType.ANTHROPIC,
                api_key=anthropic_key,
                base_url=os.getenv("ANTHROPIC_BASE_URL"),
                timeout=timeout,
            )
        )

    google_key = os.getenv("GOOGLE_GENAI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if google_key:
        configs.append(
            ProviderConfig(
                provider_id=os.getenv("GOOGLE_GENAI_PROVIDER_ID", "google"),
                provider_type=ProviderType.GOOGLE,
                api_key=google_key,
                base_url=os.getenv("GOOGLE_GENAI_BASE_URL")
                or os.getenv("GOOGLE_BASE_URL"),
                timeout=timeout,
            )
        )

    return configs


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None
