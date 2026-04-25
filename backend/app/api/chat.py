from fastapi import APIRouter
from pydantic import BaseModel

from app.events.bus import bus
from app.events.types import Events

router = APIRouter()


class ChatIn(BaseModel):
    text: str


@router.post("/chat")
async def chat(body: ChatIn):
    bus.emit(Events.CHAT_SUBMITTED, {"text": body.text})
    return {"ok": True}
