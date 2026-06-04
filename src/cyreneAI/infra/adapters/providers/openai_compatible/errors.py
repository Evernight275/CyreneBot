import json
from typing import Any, NoReturn, cast

from openai import (
    APIConnectionError as OpenAIConnectionError,
)
from openai import (
    APIError as OpenAIAPIError,
)
from openai import (
    APIResponseValidationError as OpenAIResponseValidationError,
)
from openai import (
    APIStatusError as OpenAIStatusError,
)
from openai import (
    APITimeoutError as OpenAITimeoutError,
)
from openai import (
    AuthenticationError as OpenAIAuthenticationError,
)
from openai import (
    BadRequestError as OpenAIBadRequestError,
)
from openai import (
    ConflictError as OpenAIConflictError,
)
from openai import (
    ContentFilterFinishReasonError as OpenAIContentFilterFinishReasonError,
)
from openai import (
    InternalServerError as OpenAIServerError,
)
from openai import (
    InvalidWebhookSignatureError as OpenAIInvalidWebhookSignatureError,
)
from openai import (
    LengthFinishReasonError as OpenAILengthFinishReasonError,
)
from openai import (
    NotFoundError as OpenAINotFoundError,
)
from openai import (
    OAuthError as OpenAIOAuthError,
)
from openai import (
    PermissionDeniedError as OpenAIPermissionDeniedError,
)
from openai import (
    RateLimitError as OpenAIRateLimitError,
)
from openai import (
    UnprocessableEntityError as OpenAIUnprocessableEntityError,
)
from openai import (
    WebSocketConnectionClosedError as OpenAIWebSocketConnectionClosedError,
)
from openai import (
    WebSocketQueueFullError as OpenAIWebSocketQueueFullError,
)

from cyreneAI.core.errors.provider import (
    ProviderAuthorizationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderRequestTimeoutError,
    ProviderResponseError,
    ProviderUnavailableError,
)


def translate_openai_error(exc: Exception) -> ProviderError:
    known_request_error = translate_known_request_error(exc)
    if known_request_error is not None:
        return known_request_error

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


def translate_known_request_error(exc: Exception) -> ProviderRequestError | None:
    text = " ".join(candidate.casefold() for candidate in _error_text_candidates(exc))

    if _contains_any(
        text,
        [
            "function calling is not enabled",
            "tool calling is not enabled",
            "does not support tool",
            "do not support tool",
            "tools are not supported",
            "tool_choice",
        ],
    ):
        return ProviderRequestError(
            message="Provider does not support the requested tool calling behavior",
            cause=exc,
        )

    if _contains_any(
        text,
        [
            "model is not a vlm",
            "does not support image",
            "do not support image",
            "vision is not supported",
            "invalid image",
            "image input",
        ],
    ):
        return ProviderRequestError(
            message="Provider does not support the requested vision input",
            cause=exc,
        )

    if _contains_any(
        text,
        [
            "maximum context length",
            "context length",
            "context_length_exceeded",
            "too many tokens",
            "exceeds the token limit",
        ],
    ):
        return ProviderRequestError(
            message="Provider context length exceeded",
            cause=exc,
        )

    return None


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _error_text_candidates(exc: Exception) -> list[str]:
    candidates: list[str] = []

    def append(value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if text:
            candidates.append(text)

    append(str(exc))
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        body_data = cast(dict[str, Any], body)
        append(_safe_json_dump(body_data))
        error = body_data.get("error")
        if isinstance(error, dict):
            error_data = cast(dict[str, Any], error)
            for field in ("message", "type", "code", "param"):
                append(error_data.get(field))
    else:
        append(body)

    response = getattr(exc, "response", None)
    if response is not None:
        append(getattr(response, "text", None))

    return candidates


def _safe_json_dump(value: Any) -> str | None:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return None


def raise_openai_error(exc: Exception) -> NoReturn:
    raise translate_openai_error(exc) from exc
