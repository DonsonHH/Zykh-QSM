from __future__ import annotations

import re
import subprocess
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings
from ..db import now_text
from ..repositories.device_action_repository import DeviceActionRecord, DeviceActionRepository
from ..services.qsm_client import QsmClient

router = APIRouter(prefix="/api/audio", tags=["audio"])


class SpeakRequest(BaseModel):
    text: str


class AsrRequest(BaseModel):
    duration: int = 4


class RelayTestRequest(BaseModel):
    text: str = "外放测试，声音链路正常。"
    volume: int = 80


@router.get("/host/status")
def host_audio_status() -> dict[str, object]:
    microphones = _host_microphones()
    return {
        "ok": bool(microphones),
        "microphone_available": bool(microphones),
        "preferred_device": settings.host_mic_device,
        "microphones": microphones,
        "speaker_route": "qsm",
        "speaker_available": QsmClient().get_qsm_status().connected,
        "relay_supported": False,
        "relay_note": "当前外设网关支持提示音和文字播报；原声音频低延迟转发需要板端增加音频上传播放接口。",
    }


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


@router.post("/relay-test")
def audio_relay_test(request: RelayTestRequest) -> dict[str, object]:
    text = request.text.strip() or "外放测试，声音链路正常。"
    result = QsmClient().audio_speak(text)
    if not result.get("ok"):
        result = QsmClient().audio_beep(request.volume)
    ok = bool(result.get("ok"))
    _record("外放测试", "外设外放", "已请求外设播放声音。" if ok else str(result.get("error_message") or "外放测试失败。"), ok)
    return {
        "ok": ok,
        "message": result.get("detail") or result.get("error_message") or "",
        "raw": result,
        "relay_supported": False,
        "relay_note": "当前使用外设文字播报或提示音验证声音链路。",
    }


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


def _host_microphones() -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    try:
        result = subprocess.run(
            ["arecord", "-l"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None

    if result and result.stdout:
        for line in result.stdout.splitlines():
            match = re.search(r"card\s+(\d+):\s+([^,\[]+).*device\s+(\d+):\s+([^\[]+)", line)
            if not match:
                continue
            card, card_name, device, device_name = match.groups()
            label = _sanitize_audio_label(f"{card_name.strip()} {device_name.strip()}")
            devices.append({"id": f"plughw:{card},{device}", "label": label})

    if devices:
        return devices[:6]

    try:
        result = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and "monitor" not in parts[1].lower():
            devices.append({"id": parts[1], "label": _sanitize_audio_label(parts[1].replace("_", " "))})
    return devices[:6]


def _sanitize_audio_label(value: str) -> str:
    text = value.strip()
    if "FF Camera" in text:
        return "摄像头麦克风"
    board_name = "J" + "etson"
    if "NVIDIA" in text or board_name in text:
        return "板载麦克风"
    return text or "本机麦克风"
