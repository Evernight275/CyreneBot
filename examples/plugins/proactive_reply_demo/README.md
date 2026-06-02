# Proactive Reply Demo Plugin

Minimal proactive reply plugin for CyreneAI.

It demonstrates the active-reply path without global context, raw database access,
manual `asyncio.create_task`, or channel/platform adapters in plugin code. The
delayed follow-up runs through the host-managed agent loop before sending.

```text
proactive_reply_demo/
  plugin.json
  main.py
  proactive_routes/
  assets/prompts/follow_up.txt
```

It also exposes a tiny inspection command:

```text
/proactive status
```

```python
@router.event("message")
async def remember_message(event, storage=Depends("storage"), tasks=Depends("tasks")):
    await storage.set(f"last_message_{event.session_id}", {"text": event.text})
    await tasks.cancel_key(f"follow_up:{event.session_id}")
    await tasks.schedule_once(
        "follow_up",
        delay_seconds=0.05,
        payload={"session_id": event.session_id},
        key=f"follow_up:{event.session_id}",
    )
```

The delayed task runs an agent-mode follow-up and sends through the host-managed
outbox:

```python
@router.task("follow_up")
async def follow_up(request, agent=Depends("agent"), outbox=Depends("outbox")):
    text = await agent.chat("...", session_id=request.payload["session_id"])
    await outbox.send(request.payload["session_id"], text=text)
```

The plugin only sees `PluginEvent.session_id`; the host resolves channel/user/thread
from the bot session store.
