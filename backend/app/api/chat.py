from fastapi import APIRouter
from pydantic import BaseModel

from app.events.bus import bus
from app.events.types import Events

router = APIRouter()


class ChatIn(BaseModel):
    text: str
    # Frontend FormatPicker selections — e.g. ["linkedin", "instagram-post",
    # "carousel"]. Optional; absent / empty means "let the agent decide
    # based on brand handles + keyword detection in `text`."
    formats: list[str] | None = None


@router.post("/chat")
async def chat(body: ChatIn):
    payload: dict = {"text": body.text}
    if body.formats:
        payload["formats"] = body.formats
    bus.emit(Events.CHAT_SUBMITTED, payload)
    return {"ok": True}
