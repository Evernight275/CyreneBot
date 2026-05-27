from openai import (
    APIError as OpenAIAPIError,
    APIResponseValidationError as OpenAIResponseValidationError,
    APIStatusError as OpenAIStatusError,
    APIConnectionError as OpenAIConnectionError,
    APITimeoutError as OpenAITimeoutError,
    BadRequestError as OpenAIBadRequestError,
    AuthenticationError as OpenAIAuthenticationError,
    OAuthError as OpenAIOAuthError,
    PermissionDeniedError as OpenAIPermissionDeniedError,
    NotFoundError as OpenAINotFoundError,
    ConflictError as OpenAIConflictError,
    UnprocessableEntityError as OpenAIUnprocessableEntityError,
    RateLimitError as OpenAIRateLimitError,
    InternalServerError as OpenAIServerError,
    LengthFinishReasonError as OpenAILengthFinishReasonError,
    ContentFilterFinishReasonError as OpenAIContentFilterFinishReasonError,
    InvalidWebhookSignatureError as OpenAIInvalidWebhookSignatureError,
    WebSocketConnectionClosedError as OpenAIWebSocketConnectionClosedError,
    WebSocketQueueFullError as OpenAIWebSocketQueueFullError,
)
from typing import NoReturn
from cyreneAI.core.errors.provider import (
    ProviderError,
    ProviderUnavailableError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderRequestTimeoutError,
    ProviderRateLimitError,
    ProviderAuthorizationError,
)


def translate_openai_error(exc: Exception) -> ProviderError:
    if isinstance(
        exc,
        (
            OpenAIAuthenticationError,
            OpenAIOAuthError,
            OpenAIPermissionDeniedError,
        ),
    ):
        return ProviderAuthorizationError(message=str(exc), cause=exc)

    elif isinstance(exc, OpenAIRateLimitError):
        return ProviderRateLimitError(message=str(exc), cause=exc)
    elif isinstance(exc, OpenAITimeoutError):
        return ProviderRequestTimeoutError(message=str(exc), cause=exc)
    elif isinstance(
        exc,
        (
            OpenAIConnectionError,
            OpenAIServerError,
            OpenAIWebSocketConnectionClosedError,
            OpenAIWebSocketQueueFullError,
        ),
    ):
        return ProviderUnavailableError(message=str(exc), cause=exc)
    elif isinstance(
        exc,
        (
            OpenAIResponseValidationError,
            OpenAILengthFinishReasonError,
            OpenAIContentFilterFinishReasonError,
        ),
    ):
        return ProviderResponseError(message=str(exc), cause=exc)
    elif isinstance(
        exc,
        (
            OpenAIBadRequestError,
            OpenAINotFoundError,
            OpenAIConflictError,
            OpenAIUnprocessableEntityError,
            OpenAIInvalidWebhookSignatureError,
        ),
    ):
        return ProviderRequestError(message=str(exc), cause=exc)
    elif isinstance(exc, OpenAIStatusError):
        if exc.status_code in {401, 403}:
            return ProviderAuthorizationError(message=str(exc), cause=exc)
        elif exc.status_code == 429:
            return ProviderRateLimitError(message=str(exc), cause=exc)
        elif exc.status_code >= 500:
            return ProviderUnavailableError(message=str(exc), cause=exc)
        else:
            return ProviderRequestError(message=str(exc), cause=exc)
    elif isinstance(exc, OpenAIAPIError):
        return ProviderRequestError(message=str(exc), cause=exc)
    else:
        return ProviderError(message=str(exc), cause=exc)


def raise_openai_error(exc: Exception) -> NoReturn:
    raise translate_openai_error(exc) from exc
