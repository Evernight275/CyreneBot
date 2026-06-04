from __future__ import annotations

import httpx
import pytest
from openai import (
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from cyreneAI.core.errors.provider import (
    ProviderAuthorizationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderRequestTimeoutError,
    ProviderUnavailableError,
)
from cyreneAI.infra.adapters.providers.openai_compatible.errors import (
    translate_openai_error,
)


def _response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    return httpx.Response(status_code, request=request)


def test_translate_openai_timeout_error() -> None:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    translated = translate_openai_error(APITimeoutError(request))

    assert isinstance(translated, ProviderRequestTimeoutError)
    assert isinstance(translated.cause, APITimeoutError)


def test_translate_openai_rate_limit_error() -> None:
    exc = RateLimitError("rate limited", response=_response(429), body=None)
    translated = translate_openai_error(exc)

    assert isinstance(translated, ProviderRateLimitError)
    assert translated.cause is exc


def test_translate_openai_authorization_error() -> None:
    exc = AuthenticationError("unauthorized", response=_response(401), body=None)
    translated = translate_openai_error(exc)

    assert isinstance(translated, ProviderAuthorizationError)
    assert translated.cause is exc


def test_translate_openai_status_error_by_status_code() -> None:
    unauthorized = APIStatusError("unauthorized", response=_response(401), body=None)
    unavailable = APIStatusError("server error", response=_response(500), body=None)
    request_error = APIStatusError("bad request", response=_response(400), body=None)

    assert isinstance(translate_openai_error(unauthorized), ProviderAuthorizationError)
    assert isinstance(translate_openai_error(unavailable), ProviderUnavailableError)
    assert isinstance(translate_openai_error(request_error), ProviderRequestError)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Function calling is not enabled for this model",
            "Provider does not support the requested tool calling behavior",
        ),
        (
            "The model is not a VLM",
            "Provider does not support the requested vision input",
        ),
        (
            "maximum context length exceeded",
            "Provider context length exceeded",
        ),
    ],
)
def test_translate_known_openai_compatible_request_errors(
    message: str,
    expected: str,
) -> None:
    exc = BadRequestError(
        message,
        response=_response(400),
        body={
            "error": {
                "message": message,
                "type": "invalid_request_error",
            }
        },
    )

    translated = translate_openai_error(exc)

    assert isinstance(translated, ProviderRequestError)
    assert str(translated) == expected
    assert translated.cause is exc


def test_translate_unknown_error_to_provider_error() -> None:
    exc = RuntimeError("boom")
    translated = translate_openai_error(exc)

    assert isinstance(translated, ProviderError)
    assert translated.cause is exc
