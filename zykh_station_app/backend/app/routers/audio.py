from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from ..db import now_text
from ..repositories.device_action_repository import DeviceActionRecord, DeviceActionRepository
from ..services.qsm_client import QsmClient

router = APIRouter(prefix="/api/audio", tags=["audio"])


class SpeakRequest(BaseModel):
    text: str


class AsrRequest(BaseModel):
    duration: int = 4


@router.post("/asr")
def audio_asr(request: AsrRequest) -> dict[str, object]:
    result = QsmClient().audio_asr(request.duration)
    text = str(result.get("text") or result.get("transcript") or result.get("result", {}).get("text") or "")
    _record("语音识别", "语音输入", "已返回识别文本。" if text else "未识别到有效语音。", bool(result.get("ok")))
    return {"ok": bool(result.get("ok")), "text": text, "duration": request.duration, "raw": result}


@router.post("/speak")
def audio_speak(request: SpeakRequest) -> dict[str, object]:
    result = QsmClient().audio_speak(request.text)
    _record("语音播报", "语音播报", "已请求外设播报。" if result.get("ok") else str(result.get("error_message") or "播报失败。"), bool(result.get("ok")))
    return {"ok": bool(result.get("ok")), "message": result.get("detail") or result.get("error_message") or "", "raw": result}


@router.post("/beep")
def audio_beep() -> dict[str, object]:
    result = QsmClient().audio_beep()
    _record("提示音", "提示音测试", "已请求外设播放提示音。" if result.get("ok") else str(result.get("error_message") or "提示音失败。"), bool(result.get("ok")))
    return {"ok": bool(result.get("ok")), "message": result.get("detail") or result.get("error_message") or "", "raw": result}


def _record(record_type: str, title: str, description: str, ok: bool) -> None:
    DeviceActionRepository().append(
        DeviceActionRecord(
            id=f"device-{uuid4().hex[:12]}",
            created_at=now_text(),
            type=record_type,
            title=title,
            description=description,
            status="已记录" if ok else "暂不可用",
        )
    )
