import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.events.bus import bus
from app.events.types import KNOWN_EVENTS, Events

router = APIRouter()

# chat.submitted is an *internal* trigger event consumed by the backend agent
# loop. Re-broadcasting it over SSE would cause the frontend's chatBridge to
# re-POST it to /api/chat, looping the agent forever.
_SSE_EXCLUDE = frozenset({Events.CHAT_SUBMITTED})
_SSE_FORWARD_EVENTS = tuple(e for e in KNOWN_EVENTS if e not in _SSE_EXCLUDE)


@router.get("/events")
async def events(request: Request):
    queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

    def make_listener(event_name: str):
        def listener(payload):
            queue.put_nowait((event_name, payload))

        return listener

    listeners = {name: make_listener(name) for name in _SSE_FORWARD_EVENTS}
    for name, fn in listeners.items():
        bus.on(name, fn)

    async def stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_name, payload = await asyncio.wait_for(
                        queue.get(), timeout=15
                    )
                    yield {
                        "data": json.dumps({"type": event_name, "payload": payload})
                    }
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            for name, fn in listeners.items():
                bus.remove_listener(name, fn)

    return EventSourceResponse(stream())
