from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from cyreneAI.application.channels.webhook_handler import (
    ApplicationChannelWebhookRequest,
    ChannelWebhookHandler,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.core.schema.application import (
    BotMessageResponseMode,
    BotMessageTriggerMode,
)
from cyreneAI.server.dependencies import get_runtime

TELEGRAM_SECRET_TOKEN_HEADER = "x-telegram-bot-api-secret-token"

router = APIRouter(
    prefix="/telegram",
    tags=["telegram"],
)


@router.post("/webhook")
async def handle_telegram_webhook(
    request: Request,
    payload: dict[str, Any] = Body(...),
    provider_id: str | None = Query(default=None),
    model: str | None = Query(default=None),
    temperature: float | None = Query(default=None),
    max_tokens: int | None = Query(default=None),
    max_agent_steps: int = Query(default=4, ge=1),
    max_agent_tool_calls_per_step: int | None = Query(default=None, ge=1),
    max_agent_total_tool_calls: int | None = Query(default=None, ge=1),
    max_agent_tool_result_chars: int | None = Query(default=None, ge=1),
    message_response_mode: BotMessageResponseMode = Query(
        default=BotMessageResponseMode.CHAT
    ),
    message_trigger_mode: BotMessageTriggerMode = Query(
        default=BotMessageTriggerMode.ALWAYS
    ),
    message_trigger_keyword: list[str] = Query(default=[]),
    message_trigger_mention: list[str] = Query(default=[]),
    runtime: CyreneAIRuntime = Depends(get_runtime),
) -> dict:
    _verify_telegram_secret_token(
        request,
        expected_secret=request.app.state.telegram_webhook_secret,
    )

    runtime_provider_id = provider_id or request.app.state.telegram_provider_id
    runtime_model = model or request.app.state.telegram_model
    if not runtime_provider_id or not runtime_model:
        raise HTTPException(
            status_code=400,
            detail="Telegram webhook provider_id and model are required",
        )

    try:
        result = await ChannelWebhookHandler(runtime).handle(
            ApplicationChannelWebhookRequest(
                channel_id="telegram",
                payload=payload.copy(),
                provider_id=runtime_provider_id,
                model=runtime_model,
                temperature=temperature,
                max_tokens=max_tokens,
                max_agent_steps=max_agent_steps,
                max_agent_tool_calls_per_step=max_agent_tool_calls_per_step,
                max_agent_total_tool_calls=max_agent_total_tool_calls,
                max_agent_tool_result_chars=max_agent_tool_result_chars,
                message_response_mode=message_response_mode,
                message_trigger_mode=message_trigger_mode,
                message_trigger_keywords=message_trigger_keyword,
                message_trigger_mentions=message_trigger_mention,
                metadata={
                    "telegram_update_id": str(payload.get("update_id") or ""),
                },
            )
        )
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")


def _verify_telegram_secret_token(
    request: Request,
    *,
    expected_secret: str | None,
) -> None:
    if expected_secret is None:
        return

    actual_secret = request.headers.get(TELEGRAM_SECRET_TOKEN_HEADER)
    if actual_secret != expected_secret:
        raise HTTPException(
            status_code=401,
            detail="Invalid Telegram webhook secret token",
        )
