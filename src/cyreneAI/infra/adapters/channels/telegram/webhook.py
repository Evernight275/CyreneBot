from __future__ import annotations

import hmac
from collections.abc import Mapping

from cyreneAI.core.errors.bot import BotConfigurationError, BotInputError

TELEGRAM_SECRET_TOKEN_HEADER = "x-telegram-bot-api-secret-token"


def verify_telegram_secret_token(
    headers: Mapping[str, str],
    *,
    expected_secret: str | None,
) -> bool:
    """
    校验 Telegram webhook secret token。
    """
    if expected_secret is None:
        return True
    if not expected_secret:
        raise BotConfigurationError("Telegram webhook expected secret cannot be empty")

    actual_secret = _get_header(headers, TELEGRAM_SECRET_TOKEN_HEADER)
    if actual_secret is None:
        raise BotInputError("Telegram webhook secret token header is required")
    if not hmac.compare_digest(actual_secret, expected_secret):
        raise BotInputError("Telegram webhook secret token mismatch")
    return True


def _get_header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None
