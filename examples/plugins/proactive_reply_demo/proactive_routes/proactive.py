import time

from cyreneAI.api import CyreneRouter, Depends


router = CyreneRouter()
commands = CyreneRouter(prefix="/proactive")
DEFAULT_FOLLOW_UP_DELAY_SECONDS = 30.0
DEFAULT_FOLLOW_UP_COOLDOWN_SECONDS = 300.0


@commands.command
async def status(request, storage=Depends("storage")):
    """Show proactive reply demo status."""
    session_id = request.event.session_id if request.event else "unknown"
    state = await storage.get(f"last_message_{session_id}", default={})
    last_text = state.get("text") or "none"
    return f"Proactive reply demo is running. Last message: {last_text}"


@router.event
async def on_message(request, storage=Depends("storage"), tasks=Depends("tasks")):
    """Schedule a follow-up after a message."""
    event = request.event
    message_text = (event.text or "").strip()
    if not message_text or message_text.startswith("/"):
        return None

    now = time.time()
    cooldown_key = f"follow_up_cooldown_{event.session_id}"
    cooldown_until = await storage.get(cooldown_key, default=0)
    if isinstance(cooldown_until, (int, float)) and now < cooldown_until:
        return None

    cooldown_seconds = _metadata_float(
        request,
        "follow_up_cooldown_seconds",
        DEFAULT_FOLLOW_UP_COOLDOWN_SECONDS,
    )
    await storage.set(
        f"last_message_{event.session_id}",
        {
            "session_id": event.session_id,
            "user_id": event.user_id,
            "text": message_text,
        },
    )
    await storage.set(cooldown_key, now + cooldown_seconds)
    task_key = f"follow_up:{event.session_id}"
    await tasks.cancel_key(task_key)
    await tasks.schedule_once(
        "follow_up",
        delay_seconds=_metadata_float(
            request,
            "follow_up_delay_seconds",
            DEFAULT_FOLLOW_UP_DELAY_SECONDS,
        ),
        payload={
            "session_id": event.session_id,
            "provider_id": request.metadata.get("provider_id"),
            "model": request.metadata.get("model"),
        },
        key=task_key,
    )


@router.task("follow_up")
async def follow_up(
    request,
    storage=Depends("storage"),
    assets=Depends("assets"),
    agent=Depends("agent"),
    outbox=Depends("outbox"),
):
    session_id = request.payload["session_id"]
    state = await storage.get(f"last_message_{session_id}", default={})
    template = (await assets.read_text("prompts/follow_up.txt")).strip()
    prompt = _follow_up_text(template, state)
    provider_id = _payload_string(request, "provider_id")
    model = _payload_string(request, "model")
    message_metadata = {"kind": "proactive_follow_up"}

    if provider_id is None or model is None:
        text = prompt
        message_metadata["fallback"] = "canned"
    else:
        text = await agent.chat(
            prompt,
            provider_id=provider_id,
            model=model,
            session_id=session_id,
            max_steps=4,
            metadata={
                "kind": "proactive_follow_up",
                "source": "proactive_reply_demo",
            },
        )
    await outbox.send(
        session_id,
        text=text,
        metadata=message_metadata,
    )


def _metadata_float(request, key: str, default: float) -> float:
    value = request.metadata.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _payload_string(request, key: str) -> str | None:
    value = request.payload.get(key)
    if isinstance(value, str) and value:
        return value
    value = request.metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _follow_up_text(template: str, state: object) -> str:
    if not isinstance(state, dict):
        return "我先记着这条消息。等你回来我们接着聊。"
    last_text = state.get("text")
    if not isinstance(last_text, str) or not last_text:
        return "我先记着这条消息。等你回来我们接着聊。"
    return template.format(last_text=last_text)


router.include_router(commands)
