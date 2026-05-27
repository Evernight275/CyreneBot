from __future__ import annotations

from typing import NoReturn

import httpx

from cyreneAI.core.errors.bot import BotActionError, BotConfigurationError, BotError


class TelegramBotAPIError(Exception):
    """
    Telegram Bot API 返回 ok=false 时使用的内部异常。
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: int | None = None,
        payload: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.payload = payload or {}


def translate_telegram_error(exc: Exception) -> BotError:
    """
    将 Telegram/httpx 异常翻译成 bot 通用异常。
    """
    if isinstance(exc, TelegramBotAPIError):
        return BotActionError(str(exc), cause=exc)
    if isinstance(exc, httpx.TimeoutException):
        return BotActionError("Telegram request timed out", cause=exc)
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in {401, 403}:
            return BotConfigurationError(
                f"Telegram request authorization failed with "
                f"status {exc.response.status_code}",
                cause=exc,
            )
        return BotActionError(
            f"Telegram request failed with status {exc.response.status_code}",
            cause=exc,
        )
    if isinstance(exc, httpx.HTTPError):
        return BotActionError("Telegram request failed", cause=exc)
    return BotError(str(exc), cause=exc)


def raise_telegram_error(exc: Exception) -> NoReturn:
    raise translate_telegram_error(exc) from exc
