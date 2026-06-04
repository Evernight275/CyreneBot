from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.asymmetric import ed25519
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


QQ_VALIDATION_OPCODE = 13

router = APIRouter(
    prefix="/qq",
    tags=["qq"],
)


@router.post("/webhook")
async def handle_qq_webhook(
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
    if _is_qq_validation_payload(payload):
        return _build_qq_validation_response(
            payload,
            secret=request.app.state.qq_webhook_secret,
        )

    runtime_provider_id = provider_id or request.app.state.qq_provider_id
    runtime_model = model or request.app.state.qq_model
    if not runtime_provider_id or not runtime_model:
        raise HTTPException(
            status_code=400,
            detail="QQ webhook provider_id and model are required",
        )

    try:
        result = await ChannelWebhookHandler(runtime).handle(
            ApplicationChannelWebhookRequest(
                channel_id="qq",
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
                    "qq_event_id": str(payload.get("id") or ""),
                    "qq_event_type": str(payload.get("t") or ""),
                },
            )
        )
    except CyreneAIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")


def _is_qq_validation_payload(payload: dict[str, Any]) -> bool:
    return payload.get("op") == QQ_VALIDATION_OPCODE


def _build_qq_validation_response(
    payload: dict[str, Any],
    *,
    secret: str | None,
) -> dict[str, str]:
    if not secret:
        raise HTTPException(
            status_code=400,
            detail="QQ webhook secret is required for validation",
        )

    data = payload.get("d")
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400,
            detail="QQ webhook validation payload is missing d",
        )

    plain_token = str(data.get("plain_token") or "")
    event_ts = str(data.get("event_ts") or "")
    if not plain_token or not event_ts:
        raise HTTPException(
            status_code=400,
            detail="QQ webhook validation payload is missing plain_token or event_ts",
        )

    seed = _repeat_seed_to_32_bytes(secret)
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    signature = private_key.sign((event_ts + plain_token).encode("utf-8")).hex()
    return {
        "plain_token": plain_token,
        "signature": signature,
    }


def _repeat_seed_to_32_bytes(secret: str) -> bytes:
    seed = secret.encode("utf-8")
    while len(seed) < 32:
        seed += seed
    return seed[:32]
