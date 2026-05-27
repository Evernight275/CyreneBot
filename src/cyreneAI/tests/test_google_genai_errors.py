from __future__ import annotations

import pytest
from google.genai import errors as genai_errors

from cyreneAI.core.errors.provider import (
    ProviderAuthorizationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderRequestTimeoutError,
    ProviderUnavailableError,
)
from cyreneAI.infra.adapters.providers.google_genai.errors import (
    raise_google_genai_error,
    translate_google_genai_error,
)


class _StatusCodeError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


@pytest.mark.parametrize(
    ("status_code", "expected_type"),
    [
        (401, ProviderAuthorizationError),
        (403, ProviderAuthorizationError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
    ],
)
def test_translate_google_genai_status_code_errors(
    status_code: int,
    expected_type: type[ProviderError],
) -> None:
    exc = _StatusCodeError(status_code)

    translated = translate_google_genai_error(exc)

    assert isinstance(translated, expected_type)
    assert translated.cause is exc


def test_translate_google_genai_timeout_error() -> None:
    exc = TimeoutError("timed out")

    translated = translate_google_genai_error(exc)

    assert isinstance(translated, ProviderRequestTimeoutError)
    assert translated.cause is exc


def test_translate_google_genai_api_error_to_request_error() -> None:
    exc = genai_errors.APIError(
        400,
        {
            "error": {
                "message": "bad request",
                "status": "INVALID_ARGUMENT",
            }
        },
    )

    translated = translate_google_genai_error(exc)

    assert isinstance(translated, ProviderRequestError)
    assert translated.cause is exc


def test_translate_google_genai_unknown_error_to_provider_error() -> None:
    exc = RuntimeError("boom")

    translated = translate_google_genai_error(exc)

    assert isinstance(translated, ProviderError)
    assert translated.cause is exc


def test_raise_google_genai_error_raises_translated_error() -> None:
    exc = RuntimeError("boom")

    with pytest.raises(ProviderError) as caught:
        raise_google_genai_error(exc)

    assert caught.value.cause is exc
    assert caught.value.__cause__ is exc
