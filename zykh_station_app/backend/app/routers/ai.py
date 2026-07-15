from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.ai_service import AiService

router = APIRouter(prefix="/api/ai", tags=["ai"])


class AiChatRequest(BaseModel):
    message: str = ""
    messages: list[dict[str, str]] = Field(default_factory=list)
    context: dict[str, object] = Field(default_factory=dict)

    def text(self) -> str:
        if self.message.strip():
            return self.message.strip()
        for item in reversed(self.messages):
            if item.get("role") == "user" and item.get("content", "").strip():
                return item["content"].strip()
        return ""


@router.get("/status")
def ai_status() -> dict[str, object]:
    return AiService().status()


@router.post("/warm-local")
def warm_local_ai() -> dict[str, object]:
    return AiService().warm_local()


@router.post("/chat")
def ai_chat(request: AiChatRequest) -> dict[str, object]:
    return AiService().chat(request.text())


@router.post("/chat/stream")
def ai_chat_stream(request: AiChatRequest):
    def events():
        for event in AiService().stream(request.text(), context=request.context):
            event_type = str(event.get("type") or "message")
            payload = {key: value for key, value in event.items() if key != "type"}
            yield f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
