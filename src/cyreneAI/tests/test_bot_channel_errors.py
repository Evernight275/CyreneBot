from __future__ import annotations

import httpx
import pytest

from cyreneAI.core.errors.bot import BotActionError, BotConfigurationError, BotError
from cyreneAI.infra.adapters.channels.qq.errors import (
    QQBotAPIError,
    raise_qq_error,
    translate_qq_error,
)
from cyreneAI.infra.adapters.channels.telegram.errors import (
    TelegramBotAPIError,
    raise_telegram_error,
    translate_telegram_error,
)


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://bot.example/test")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("bad status", request=request, response=response)


@pytest.mark.parametrize(
    "exc, expected_type, expected_message",
    [
        (QQBotAPIError("unauthorized", error_code=401), BotConfigurationError, "unauthorized"),
        (QQBotAPIError("forbidden", error_code="403"), BotConfigurationError, "forbidden"),
        (QQBotAPIError("bad request", error_code=400), BotActionError, "bad request"),
        (httpx.TimeoutException("slow"), BotActionError, "QQ request timed out"),
        (
            _status_error(401),
            BotConfigurationError,
            "QQ request authorization failed with status 401",
        ),
        (_status_error(500), BotActionError, "QQ request failed with status 500"),
        (httpx.ConnectError("offline"), BotActionError, "QQ request failed"),
        (RuntimeError("surprise"), BotError, "surprise"),
    ],
)
def test_translate_qq_error_maps_common_failures(
    exc,
    expected_type,
    expected_message,
) -> None:
    translated = translate_qq_error(exc)

    assert isinstance(translated, expected_type)
    assert str(translated) == expected_message
    assert translated.cause is exc


def test_raise_qq_error_raises_translated_error() -> None:
    with pytest.raises(BotConfigurationError, match="forbidden") as caught:
        raise_qq_error(QQBotAPIError("forbidden", error_code=403))

    assert isinstance(caught.value.__cause__, QQBotAPIError)


@pytest.mark.parametrize(
    "exc, expected_type, expected_message",
    [
        (TelegramBotAPIError("bad request", error_code=400), BotActionError, "bad request"),
        (httpx.TimeoutException("slow"), BotActionError, "Telegram request timed out"),
        (
            _status_error(403),
            BotConfigurationError,
            "Telegram request authorization failed with status 403",
        ),
        (
            _status_error(500),
            BotActionError,
            "Telegram request failed with status 500",
        ),
        (httpx.ConnectError("offline"), BotActionError, "Telegram request failed"),
        (RuntimeError("surprise"), BotError, "surprise"),
    ],
)
def test_translate_telegram_error_maps_common_failures(
    exc,
    expected_type,
    expected_message,
) -> None:
    translated = translate_telegram_error(exc)

    assert isinstance(translated, expected_type)
    assert str(translated) == expected_message
    assert translated.cause is exc


def test_raise_telegram_error_raises_translated_error() -> None:
    with pytest.raises(BotActionError, match="bad request") as caught:
        raise_telegram_error(TelegramBotAPIError("bad request", error_code=400))

    assert isinstance(caught.value.__cause__, TelegramBotAPIError)
