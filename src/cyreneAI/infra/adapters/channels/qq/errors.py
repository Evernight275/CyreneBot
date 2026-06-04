from __future__ import annotations

from typing import NoReturn

import httpx

from cyreneAI.core.errors.bot import BotActionError, BotConfigurationError, BotError


class QQBotAPIError(Exception):
    """
    QQ Bot API error wrapper.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: int | str | None = None,
        payload: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.payload = payload or {}


def translate_qq_error(exc: Exception) -> BotError:
    """
    Translate QQ/httpx errors to common bot errors.
    """
    if isinstance(exc, QQBotAPIError):
        if exc.error_code in {401, 403, "401", "403"}:
            return BotConfigurationError(str(exc), cause=exc)
        return BotActionError(str(exc), cause=exc)
    if isinstance(exc, httpx.TimeoutException):
        return BotActionError("QQ request timed out", cause=exc)
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in {401, 403}:
            return BotConfigurationError(
                f"QQ request authorization failed with status {exc.response.status_code}",
                cause=exc,
            )
        return BotActionError(
            f"QQ request failed with status {exc.response.status_code}",
            cause=exc,
        )
    if isinstance(exc, httpx.HTTPError):
        return BotActionError("QQ request failed", cause=exc)
    return BotError(str(exc), cause=exc)


def raise_qq_error(exc: Exception) -> NoReturn:
    raise translate_qq_error(exc) from exc
