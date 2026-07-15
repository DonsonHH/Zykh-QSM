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


@router.post("/chat")
def ai_chat(request: AiChatRequest) -> dict[str, object]:
    return AiService().chat(request.text())


@router.post("/chat/stream")
def ai_chat_stream(request: AiChatRequest):
    def events():
        result = AiService().chat(request.text())
        source = str(result.get("source") or "rules_fallback")
        model = str(result.get("model") or "")
        reply = str(result.get("reply") or "")
        yield f"event: meta\ndata: {json.dumps({'ok': True, 'source': source, 'model': model}, ensure_ascii=False)}\n\n"
        chunks = [reply[index : index + 18] for index in range(0, len(reply), 18)] or [""]
        for chunk in chunks:
            yield f"event: delta\ndata: {json.dumps({'text': chunk, 'source': source}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {\"ok\":true}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
