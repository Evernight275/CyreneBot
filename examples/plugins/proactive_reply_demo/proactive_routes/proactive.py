import time

from cyreneAI.api import CyreneRouter, Depends, text


router = CyreneRouter()
DEFAULT_FOLLOW_UP_DELAY_SECONDS = 30.0
DEFAULT_FOLLOW_UP_COOLDOWN_SECONDS = 300.0


@router.command("/proactive status")
async def status(request, storage=Depends("storage")):
    """Show proactive reply demo status."""
    session_id = request.event.session_id if request.event else "unknown"
    state = await storage.get(f"last_message_{session_id}", default={})
    last_text = state.get("text") or "none"
    return text(request, f"Proactive reply demo is running. Last message: {last_text}")


@router.event("message")
async def remember_message(request, storage=Depends("storage"), tasks=Depends("tasks")):
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
        payload={"session_id": event.session_id},
        key=task_key,
    )


@router.task("follow_up")
async def follow_up(
    request,
    storage=Depends("storage"),
    assets=Depends("assets"),
    outbox=Depends("outbox"),
):
    session_id = request.payload["session_id"]
    state = await storage.get(f"last_message_{session_id}", default={})
    template = (await assets.read_text("prompts/follow_up.txt")).strip()
    await outbox.send(
        session_id,
        text=template.format(last_text=state.get("text", "")),
        metadata={"kind": "proactive_follow_up"},
    )


def _metadata_float(request, key: str, default: float) -> float:
    value = request.metadata.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
