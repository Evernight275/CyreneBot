from __future__ import annotations

import pytest

from cyreneAI.core.errors.bot import BotConfigurationError, BotInputError
from cyreneAI.infra.adapters.channels.telegram.webhook import (
    TELEGRAM_SECRET_TOKEN_HEADER,
    verify_telegram_secret_token,
)


def test_verify_telegram_secret_token_accepts_matching_header() -> None:
    assert verify_telegram_secret_token(
        {
            "X-Telegram-Bot-Api-Secret-Token": "secret",
        },
        expected_secret="secret",
    )


def test_verify_telegram_secret_token_allows_unconfigured_secret() -> None:
    assert verify_telegram_secret_token(
        {},
        expected_secret=None,
    )


def test_verify_telegram_secret_token_rejects_empty_expected_secret() -> None:
    with pytest.raises(BotConfigurationError):
        verify_telegram_secret_token(
            {},
            expected_secret="",
        )


def test_verify_telegram_secret_token_rejects_missing_header() -> None:
    with pytest.raises(BotInputError):
        verify_telegram_secret_token(
            {},
            expected_secret="secret",
        )


def test_verify_telegram_secret_token_rejects_mismatch() -> None:
    with pytest.raises(BotInputError):
        verify_telegram_secret_token(
            {
                TELEGRAM_SECRET_TOKEN_HEADER: "wrong",
            },
            expected_secret="secret",
        )
