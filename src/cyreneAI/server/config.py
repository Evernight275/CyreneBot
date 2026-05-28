from __future__ import annotations

import os
from datetime import timedelta

from dotenv import load_dotenv

from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.core.schema.server import ServerSettings


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


def build_plugin_paths_from_env() -> list[str]:
    load_dotenv()

    raw = _env_str("CYRENEAI_PLUGIN_PATH")
    if raw is None:
        return []
    return [
        part.strip()
        for part in raw.split(os.pathsep)
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
