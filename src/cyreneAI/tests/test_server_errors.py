from __future__ import annotations

import pytest
from fastapi import HTTPException, status

from cyreneAI.core.errors.base import (
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    CyreneAIError,
    DependencyError,
    NotFoundError,
    RateLimitError,
    RequestError,
    RequestTimeoutError,
    ResponseError,
    StateError,
    UnavailableError,
    UnsupportedError,
    ValidationError,
)
from cyreneAI.core.errors.plugin import PluginExecutionError
from cyreneAI.core.errors.provider import ProviderError
from cyreneAI.server.errors import http_status_for_error, raise_http_error


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (NotFoundError("missing"), status.HTTP_404_NOT_FOUND),
        (ConflictError("conflict"), status.HTTP_409_CONFLICT),
        (RateLimitError("slow down"), status.HTTP_429_TOO_MANY_REQUESTS),
        (RequestTimeoutError("timed out"), status.HTTP_504_GATEWAY_TIMEOUT),
        (AuthorizationError("forbidden"), status.HTTP_401_UNAUTHORIZED),
        (StateError("Provider registry is not configured"), status.HTTP_503_SERVICE_UNAVAILABLE),
        (StateError("already stopped"), status.HTTP_409_CONFLICT),
        (ValidationError("invalid"), 422),
        (UnsupportedError("unsupported"), 422),
        (RequestError("bad request"), status.HTTP_400_BAD_REQUEST),
        (ResponseError("bad upstream"), status.HTTP_502_BAD_GATEWAY),
        (DependencyError("dependency down"), status.HTTP_503_SERVICE_UNAVAILABLE),
        (UnavailableError("unavailable"), status.HTTP_503_SERVICE_UNAVAILABLE),
        (ProviderError("provider failed"), 422),
        (PluginExecutionError("plugin failed"), 422),
        (ConfigurationError("bad config"), status.HTTP_503_SERVICE_UNAVAILABLE),
        (CyreneAIError("generic"), status.HTTP_400_BAD_REQUEST),
    ],
)
def test_http_status_for_error_maps_core_error_types(
    error: CyreneAIError,
    expected_status: int,
) -> None:
    assert http_status_for_error(error) == expected_status


def test_raise_http_error_preserves_detail_headers_and_cause() -> None:
    error = ConflictError("already exists")

    with pytest.raises(HTTPException) as caught:
        raise_http_error(
            error,
            status_code=status.HTTP_418_IM_A_TEAPOT,
            headers={"x-test": "yes"},
        )

    assert caught.value.status_code == status.HTTP_418_IM_A_TEAPOT
    assert caught.value.detail == "already exists"
    assert caught.value.headers == {"x-test": "yes"}
    assert caught.value.__cause__ is error
