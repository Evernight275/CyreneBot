from __future__ import annotations

import httpx
import pytest
from anthropic import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
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
from cyreneAI.infra.adapters.providers.anthropic.errors import (
    raise_anthropic_error,
    translate_anthropic_error,
)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_request())


@pytest.mark.parametrize(
    ("exc", "expected_type"),
    [
        (
            AuthenticationError(
                "unauthorized",
                response=_response(401),
                body=None,
            ),
            ProviderAuthorizationError,
        ),
        (
            PermissionDeniedError(
                "forbidden",
                response=_response(403),
                body=None,
            ),
            ProviderAuthorizationError,
        ),
        (
            RateLimitError(
                "rate limited",
                response=_response(429),
                body=None,
            ),
            ProviderRateLimitError,
        ),
        (
            APITimeoutError(_request()),
            ProviderRequestTimeoutError,
        ),
        (
            APIConnectionError(request=_request()),
            ProviderUnavailableError,
        ),
        (
            BadRequestError(
                "bad request",
                response=_response(400),
                body=None,
            ),
            ProviderRequestError,
        ),
        (
            NotFoundError(
                "missing",
                response=_response(404),
                body=None,
            ),
            ProviderRequestError,
        ),
    ],
)
def test_translate_anthropic_specific_errors(
    exc: Exception,
    expected_type: type[ProviderError],
) -> None:
    translated = translate_anthropic_error(exc)

    assert isinstance(translated, expected_type)
    assert translated.cause is exc


@pytest.mark.parametrize(
    ("status_code", "expected_type"),
    [
        (401, ProviderAuthorizationError),
        (403, ProviderAuthorizationError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
        (400, ProviderRequestError),
    ],
)
def test_translate_anthropic_status_error_by_status_code(
    status_code: int,
    expected_type: type[ProviderError],
) -> None:
    exc = APIStatusError(
        f"status {status_code}",
        response=_response(status_code),
        body=None,
    )

    translated = translate_anthropic_error(exc)

    assert isinstance(translated, expected_type)
    assert translated.cause is exc


def test_translate_anthropic_api_error_to_request_error() -> None:
    exc = APIError("api error", _request(), body=None)

    translated = translate_anthropic_error(exc)

    assert isinstance(translated, ProviderRequestError)
    assert translated.cause is exc


def test_translate_anthropic_unknown_error_to_provider_error() -> None:
    exc = RuntimeError("boom")

    translated = translate_anthropic_error(exc)

    assert isinstance(translated, ProviderError)
    assert translated.cause is exc


def test_raise_anthropic_error_raises_translated_error() -> None:
    exc = RuntimeError("boom")

    with pytest.raises(ProviderError) as caught:
        raise_anthropic_error(exc)

    assert caught.value.cause is exc
    assert caught.value.__cause__ is exc
