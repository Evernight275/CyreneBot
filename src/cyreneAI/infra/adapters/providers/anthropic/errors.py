from typing import NoReturn

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


def translate_anthropic_error(exc: Exception) -> ProviderError:
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return ProviderAuthorizationError(message=str(exc), cause=exc)
    if isinstance(exc, RateLimitError):
        return ProviderRateLimitError(message=str(exc), cause=exc)
    if isinstance(exc, APITimeoutError):
        return ProviderRequestTimeoutError(message=str(exc), cause=exc)
    if isinstance(exc, APIConnectionError):
        return ProviderUnavailableError(message=str(exc), cause=exc)
    if isinstance(exc, (BadRequestError, NotFoundError)):
        return ProviderRequestError(message=str(exc), cause=exc)
    if isinstance(exc, APIStatusError):
        if exc.status_code in {401, 403}:
            return ProviderAuthorizationError(message=str(exc), cause=exc)
        if exc.status_code == 429:
            return ProviderRateLimitError(message=str(exc), cause=exc)
        if exc.status_code >= 500:
            return ProviderUnavailableError(message=str(exc), cause=exc)
        return ProviderRequestError(message=str(exc), cause=exc)
    if isinstance(exc, APIError):
        return ProviderRequestError(message=str(exc), cause=exc)
    return ProviderError(message=str(exc), cause=exc)


def raise_anthropic_error(exc: Exception) -> NoReturn:
    raise translate_anthropic_error(exc) from exc
