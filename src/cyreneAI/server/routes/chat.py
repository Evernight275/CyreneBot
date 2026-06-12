from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from cyreneAI.application.chat.orchestrator import (
    ApplicationChatRequest,
    ChatOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.core.errors.chat import ChatStreamError
from cyreneAI.core.schema.chat import ChatStreamEvent, ChatStreamEventType
from cyreneAI.server.dependencies import get_runtime, require_admin
from cyreneAI.server.errors import raise_http_error
from cyreneAI.server.logging_config import bind_log_context
from cyreneAI.server.schemas import ChatRequestBody

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    dependencies=[Depends(require_admin)],
)

logger = logging.getLogger("cyreneAI.server.chat")


def _build_application_request(body: ChatRequestBody) -> ApplicationChatRequest:
    return ApplicationChatRequest(
        session_id=body.metadata.get("session_id", "http"),
        provider_id=body.provider_id,
        model=body.model,
        messages=[message.to_core_message() for message in body.messages],
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        stream=body.stream,
        tool_choice=body.tool_choice,
        allowed_tool_names=body.allowed_tool_names,
        tool_execution_policy=body.tool_execution_policy,
        max_tool_rounds=body.max_tool_rounds,
        metadata=body.metadata.copy(),
    )


@router.post("")
async def chat(
    body: ChatRequestBody,
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict:
    try:
        result = await ChatOrchestrator(runtime).chat(_build_application_request(body))
    except CyreneAIError as exc:
        with bind_log_context(**_chat_error_log_context(body, exc)):
            logger.exception("Chat request failed")
        raise_http_error(exc)
    return result.model_dump(mode="json")


def _sse(event: ChatStreamEvent) -> str:
    payload = event.model_dump(mode="json", exclude_none=True)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def chat_stream(
    body: ChatRequestBody,
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> StreamingResponse:
    orchestrator = ChatOrchestrator(runtime)
    request = _build_application_request(body)

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event in orchestrator.chat_stream(request):
                yield _sse(event)
        except CyreneAIError as exc:
            with bind_log_context(**_chat_error_log_context(body, exc)):
                logger.exception("Chat stream failed")
            yield _sse(ChatStreamEvent(type=ChatStreamEventType.ERROR, detail=str(exc)))
        except Exception as exc:  # noqa: BLE001 - 兜底，避免流中断后前端无反馈
            error = ChatStreamError(str(exc), cause=exc)
            with bind_log_context(**_chat_error_log_context(body, error)):
                logger.exception("Chat stream failed unexpectedly")
            yield _sse(
                ChatStreamEvent(type=ChatStreamEventType.ERROR, detail=str(error))
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _chat_error_log_context(
    body: ChatRequestBody,
    exc: CyreneAIError,
) -> dict[str, object]:
    context: dict[str, object] = {
        "provider_id": body.provider_id,
        "model": body.model,
        "session_id": body.metadata.get("session_id"),
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
    cause = exc.cause or exc.__cause__
    if cause is not None:
        context["cause_type"] = cause.__class__.__name__
        context["cause"] = str(cause)
    return context
