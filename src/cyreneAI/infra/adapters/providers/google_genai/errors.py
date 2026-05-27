from typing import NoReturn

from google.genai import errors as genai_errors

from cyreneAI.core.errors.provider import (
    ProviderAuthorizationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderRequestTimeoutError,
    ProviderUnavailableError,
)


def translate_google_genai_error(exc: Exception) -> ProviderError:
    if isinstance(exc, TimeoutError):
        return ProviderRequestTimeoutError(message=str(exc), cause=exc)

    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status_code in {401, 403}:
        return ProviderAuthorizationError(message=str(exc), cause=exc)
    if status_code == 429:
        return ProviderRateLimitError(message=str(exc), cause=exc)
    if isinstance(status_code, int) and status_code >= 500:
        return ProviderUnavailableError(message=str(exc), cause=exc)
    if isinstance(exc, genai_errors.APIError):
        return ProviderRequestError(message=str(exc), cause=exc)
    return ProviderError(message=str(exc), cause=exc)


def raise_google_genai_error(exc: Exception) -> NoReturn:
    raise translate_google_genai_error(exc) from exc
