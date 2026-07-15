from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re
import socket
import subprocess
import wave
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..config import settings
from ..db import now_text
from ..repositories.device_action_repository import DeviceActionRecord, DeviceActionRepository
from ..services.local_asr_client import LocalAsrClient
from ..services.network_service import NetworkService
from ..services.qsm_client import QsmClient
from ..services.qwen_realtime_tts import QwenRealtimeTts

router = APIRouter(prefix="/api/audio", tags=["audio"])


class SpeakRequest(BaseModel):
    text: str
    volume: int | None = None
    speed: float | None = None
    mode: str | None = None


class AsrRequest(BaseModel):
    duration: int = 4


class RelayTestRequest(BaseModel):
    text: str = "外放测试，声音链路正常。"
    volume: int = 230


class BeepRequest(BaseModel):
    volume: int | None = None


class HostMicVolumeRequest(BaseModel):
    volume: int = 70


class PlayAudioRequest(BaseModel):
    audio_base64: str
    format: str = "wav"
    volume: int = 230


class AudioStreamRequest(BaseModel):
    port: int | None = None
    volume: int = 230
    rate: int = 16000
    channels: int = 1


@router.get("/host/status")
def host_audio_status() -> dict[str, object]:
    microphone = _qsm_mic_request(settings.qsm_mic_status_path)
    microphone_available = bool(microphone.get("ok"))
    microphones = (
        [{"id": "qsm:FF Camera", "label": "外设摄像头麦克风"}]
        if microphone_available
        else []
    )
    speaker_available = _tcp_available(settings.qsm_api_base, timeout=0.45)
    return {
        "ok": microphone_available,
        "microphone_available": microphone_available,
        "preferred_device": settings.host_mic_device,
        "microphones": microphones,
        "microphone_source": "qsm",
        "microphone_status": microphone,
        "speaker_route": "qsm",
        "speaker_available": speaker_available,
        "relay_supported": True,
        "relay_note": "主机系统声音外放只使用低延迟 PCM 实时流；语音合成播报仍走外设播报接口。",
    }


@router.post("/host/mic-volume")
def set_host_mic_volume(request: HostMicVolumeRequest) -> dict[str, object]:
    volume = max(0, min(int(request.volume), 100))
    result = _qsm_mic_request(settings.qsm_mic_volume_path, method="POST", payload={"volume": volume})
    return {
        "ok": bool(result.get("ok")),
        "volume": volume,
        "message": "外设麦克风音量已更新。" if result.get("ok") else str(result.get("error_message") or "未能调整外设麦克风音量。"),
        "method": "qsm-ff-camera",
        "raw": result,
    }


@router.post("/asr")
def audio_asr(request: AsrRequest) -> dict[str, object]:
    result = QsmClient().audio_asr(request.duration)
    text = str(result.get("text") or result.get("transcript") or result.get("result", {}).get("text") or "")
    _record("语音识别", "语音输入", "已返回识别文本。" if text else "未识别到有效语音。", bool(result.get("ok")))
    return {"ok": bool(result.get("ok")), "text": text, "duration": request.duration, "raw": result}


@router.get("/status")
def audio_status() -> dict[str, object]:
    requested_mode = _tts_mode_for_network()
    result = QsmClient().audio_status()
    local_asr = LocalAsrClient().status()
    return {
        "ok": bool(result.get("ok")),
        "requested_mode": requested_mode,
        "offline_available": bool(result.get("offline_available") or result.get("offline", {}).get("available")),
        "cloud_available": bool(result.get("cloud_available") or result.get("cloud", {}).get("available")),
        "local_asr": local_asr,
        "realtime_tts_configured": bool(_read_api_key(settings.dashscope_api_key, settings.dashscope_api_key_file)),
        "raw": result,
    }


@router.post("/speak")
async def audio_speak(request: SpeakRequest) -> dict[str, object]:
    client = QsmClient()
    network_mode = _tts_mode_for_network()
    requested_mode = "offline" if network_mode == "offline" else _normalize_tts_mode(request.mode) or network_mode
    result: dict[str, object]
    realtime_failure = ""
    if requested_mode != "offline":
        api_key = _read_api_key(settings.dashscope_api_key, settings.dashscope_api_key_file)
        result = await QwenRealtimeTts(client).speak(
            request.text,
            api_key,
            volume=request.volume,
            speed=request.speed,
        )
        if not result.get("ok"):
            realtime_failure = str(result.get("error_message") or "实时语音合成暂不可用。")
            result = await asyncio.to_thread(
                client.audio_speak,
                request.text,
                request.volume,
                request.speed,
                "offline",
            )
            result["fallback_reason"] = realtime_failure
    else:
        await asyncio.to_thread(client.audio_stream_stop)
        result = await asyncio.to_thread(
            client.audio_speak,
            request.text,
            request.volume,
            request.speed,
            "offline",
        )
    actual_mode = str(result.get("mode") or "")
    description = (
        "已使用板端离线语音播报。"
        if actual_mode.startswith("offline")
        else "实时语音已发送到外设喇叭。"
        if result.get("ok")
        else str(result.get("error_message") or result.get("detail") or "播报失败。")
    )
    _record("语音播报", "语音播报", description, bool(result.get("ok")))
    return {
        "ok": bool(result.get("ok")),
        "message": result.get("detail") or result.get("error_message") or "",
        "requested_mode": requested_mode,
        "engine": actual_mode,
        "offline": bool(result.get("offline")),
        "first_audio_ms": result.get("first_audio_ms"),
        "total_ms": result.get("total_ms"),
        "fallback_reason": realtime_failure or result.get("fallback_reason") or "",
        "raw": result,
    }


@router.post("/beep")
def audio_beep(request: BeepRequest | None = None) -> dict[str, object]:
    client = QsmClient()
    client.audio_stream_stop()
    result = client.audio_beep(request.volume if request else None)
    _record("提示音", "提示音测试", "已请求外设播放提示音。" if result.get("ok") else str(result.get("error_message") or "提示音失败。"), bool(result.get("ok")))
    return {"ok": bool(result.get("ok")), "message": result.get("detail") or result.get("error_message") or "", "raw": result}


@router.post("/relay-test")
def audio_relay_test(request: RelayTestRequest) -> dict[str, object]:
    text = request.text.strip() or "外放测试，声音链路正常。"
    audio_b64 = base64.b64encode(_notice_wav_bytes()).decode("ascii")
    volume = max(0, min(int(request.volume), 255))
    client = QsmClient()
    client.audio_stream_stop()
    result = client.audio_play_base64(audio_b64, "wav", volume)
    mode = "uploaded-audio"
    if not result.get("ok"):
        result = client.audio_speak(text, volume, tts_mode=_tts_mode_for_network())
        mode = "tts"
    if not result.get("ok"):
        result = client.audio_beep(volume)
        mode = "beep"
    ok = bool(result.get("ok"))
    _record("外放测试", "外设外放", "已请求外设播放声音。" if ok else str(result.get("error_message") or "外放测试失败。"), ok)
    return {
        "ok": ok,
        "message": result.get("detail") or result.get("error_message") or "",
        "raw": result,
        "relay_mode": mode,
        "relay_supported": True,
        "relay_note": "优先发送本机音频到外设喇叭播放，失败时退回文字播报或提示音。",
    }


@router.post("/play")
def audio_play(request: PlayAudioRequest) -> dict[str, object]:
    volume = max(0, min(int(request.volume), 255))
    client = QsmClient()
    client.audio_stream_stop()
    result = client.audio_play_base64(request.audio_base64, request.format, volume)
    ok = bool(result.get("ok"))
    _record("音频转发", "外设外放", "已发送音频到外设喇叭。" if ok else str(result.get("error_message") or "音频转发失败。"), ok)
    return {
        "ok": ok,
        "message": result.get("detail") or result.get("error_message") or "",
        "raw": result,
    }


@router.post("/stream/start")
def audio_stream_start(request: AudioStreamRequest) -> dict[str, object]:
    result = QsmClient().audio_stream_start(
        port=request.port or settings.qsm_audio_stream_port,
        volume=request.volume,
        rate=request.rate,
        channels=request.channels,
    )
    ok = bool(result.get("ok"))
    _record("音频实时流", "外设实时外放", "已启动音频实时流。" if ok else str(result.get("error_message") or "实时流启动失败。"), ok)
    return {"ok": ok, "message": result.get("detail") or result.get("error_message") or "", "raw": result}


@router.post("/stream/stop")
def audio_stream_stop() -> dict[str, object]:
    result = QsmClient().audio_stream_stop()
    ok = bool(result.get("ok"))
    return {"ok": ok, "message": result.get("detail") or result.get("error_message") or "", "raw": result}


@router.websocket("/asr/realtime")
async def audio_asr_realtime(websocket: WebSocket) -> None:
    await websocket.accept()
    if _asr_mode_for_network() == "local":
        await _audio_asr_local(websocket)
        return
    api_key = _read_api_key(settings.dashscope_api_key, settings.dashscope_api_key_file)
    if not api_key:
        await _audio_asr_local(websocket, fallback_reason="云端语音密钥未配置。")
        return

    model = "qwen3-asr-flash-realtime"
    url = f"wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={model}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "OpenAI-Beta": "realtime=v1",
    }
    try:
        async with websockets.connect(url, additional_headers=headers, ping_interval=20, ping_timeout=20) as upstream:
            await upstream.send(
                json.dumps(
                    {
                        "event_id": f"event-{uuid4().hex[:10]}",
                        "type": "session.update",
                        "session": {
                            "modalities": ["text"],
                            "input_audio_format": "pcm",
                            "sample_rate": 16000,
                            "input_audio_transcription": {"language": "zh"},
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.2,
                                "silence_duration_ms": 800,
                            },
                        },
                    },
                    ensure_ascii=False,
                )
            )
            try:
                mic_reader, mic_writer = await _open_qsm_mic_stream()
            except Exception as exc:
                await websocket.send_json({"type": "error", "message": f"外设麦克风连接失败：{exc}"})
                await websocket.close(code=1011)
                return

            await websocket.send_json({"type": "ready", "model": model, "source": "qsm-ff-camera"})
            send_lock = asyncio.Lock()
            stopped = asyncio.Event()
            committed = False

            async def commit_audio() -> None:
                nonlocal committed
                if committed:
                    return
                committed = True
                async with send_lock:
                    await upstream.send(
                        json.dumps(
                            {
                                "event_id": f"event-{uuid4().hex[:10]}",
                                "type": "input_audio_buffer.commit",
                            }
                        )
                    )

            async def qsm_to_upstream() -> None:
                try:
                    while not stopped.is_set():
                        audio = await mic_reader.read(3200)
                        if not audio:
                            break
                        encoded = base64.b64encode(audio).decode("ascii")
                        async with send_lock:
                            await upstream.send(
                                json.dumps(
                                    {
                                        "event_id": f"event-{uuid4().hex[:10]}",
                                        "type": "input_audio_buffer.append",
                                        "audio": encoded,
                                    }
                                )
                            )
                finally:
                    await commit_audio()

            async def client_control() -> str:
                while True:
                    message = await websocket.receive()
                    text = message.get("text")
                    if text:
                        try:
                            payload = json.loads(text)
                        except json.JSONDecodeError:
                            payload = {}
                        if payload.get("type") == "stop":
                            stopped.set()
                            mic_writer.close()
                            await mic_writer.wait_closed()
                            await commit_audio()
                            continue
                    if message.get("type") == "websocket.disconnect":
                        return "disconnect"

            async def upstream_to_client() -> str:
                async for raw in upstream:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    text, final = _extract_transcript(event)
                    if text:
                        await websocket.send_json(
                            {
                                "type": "transcript",
                                "text": text,
                                "final": final,
                                "event_type": event.get("type", ""),
                            }
                        )
                        if final:
                            return "final"
                    elif event.get("type") in {"error", "session.error"} or event.get("error"):
                        await websocket.send_json({"type": "error", "message": _event_error_message(event)})
                        return "error"
                return "closed"

            producer = asyncio.create_task(qsm_to_upstream())
            control = asyncio.create_task(client_control())
            consumer = asyncio.create_task(upstream_to_client())
            active = {producer, control, consumer}
            try:
                while active:
                    done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        active.remove(task)
                        task.result()
                        if task is control or task is consumer:
                            return
            finally:
                stopped.set()
                mic_writer.close()
                for task in active:
                    task.cancel()
                await asyncio.gather(*active, return_exceptions=True)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await _audio_asr_local(websocket, fallback_reason=f"云端语音识别不可用：{exc}")
        except Exception:
            pass


def _normalize_tts_mode(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in {"auto", "cloud", "offline"} else ""


def _tts_mode_for_network() -> str:
    try:
        network = NetworkService().status()
    except Exception:
        return "auto"
    return "offline" if str(network.get("mode") or "").lower() in {"local", "offline"} else "auto"


def _asr_mode_for_network() -> str:
    try:
        network = NetworkService().status()
    except Exception:
        return "cloud"
    return "local" if str(network.get("mode") or "").lower() in {"local", "offline"} else "cloud"


async def _audio_asr_local(websocket: WebSocket, fallback_reason: str = "") -> None:
    client = LocalAsrClient()
    status = client.status()
    if not status.get("ready"):
        await websocket.send_json(
            {
                "type": "error",
                "message": "本地实时语音识别尚未启动，请检查外设语音服务。",
                "detail": status.get("error_message") or fallback_reason,
            }
        )
        await websocket.close(code=1011)
        return

    try:
        mic_reader, mic_writer = await _open_qsm_mic_stream()
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": f"外设麦克风连接失败：{exc}"})
        await websocket.close(code=1011)
        return

    stopped = asyncio.Event()
    await websocket.send_json(
        {
            "type": "ready",
            "model": status.get("model"),
            "source": "qsm-local-asr",
            "offline": True,
            "fallback_reason": fallback_reason,
        }
    )

    async def local_to_client() -> None:
        async for text, final in client.recognize(mic_reader, stopped):
            await websocket.send_json(
                {
                    "type": "transcript",
                    "text": text,
                    "final": final,
                    "source": "qsm-local-asr",
                }
            )
            if final:
                return

    async def client_control() -> None:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                stopped.set()
                return
            text = message.get("text")
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {}
            if payload.get("type") == "stop":
                stopped.set()
                mic_writer.close()
                await mic_writer.wait_closed()

    consumer = asyncio.create_task(local_to_client())
    control = asyncio.create_task(client_control())
    try:
        done, pending = await asyncio.wait({consumer, control}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        return
    finally:
        stopped.set()
        if not mic_writer.is_closing():
            mic_writer.close()
            await mic_writer.wait_closed()


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


def _qsm_mic_request(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    url = f"{settings.qsm_mic_api_base}{path}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urlopen(request, timeout=settings.qsm_mic_timeout_seconds) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result if isinstance(result, dict) else {"ok": False, "error_message": "麦克风接口返回格式错误。"}
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "status": "unavailable", "error_message": str(exc)}


async def _open_qsm_mic_stream() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    parsed = urlparse(settings.qsm_mic_api_base)
    if parsed.scheme != "http":
        raise RuntimeError("麦克风采集地址仅支持 http")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    base_path = parsed.path.rstrip("/")
    path = f"{base_path}{settings.qsm_mic_stream_path}?rate=16000&duration=45"
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port),
        timeout=settings.qsm_mic_timeout_seconds,
    )
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Accept: application/octet-stream\r\n"
        "Connection: close\r\n\r\n"
    )
    writer.write(request.encode("ascii"))
    await writer.drain()
    try:
        headers = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"),
            timeout=settings.qsm_mic_timeout_seconds,
        )
    except Exception:
        writer.close()
        await writer.wait_closed()
        raise
    status_line = headers.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    if " 200 " not in status_line:
        detail = (await reader.read(512)).decode("utf-8", errors="replace")
        writer.close()
        await writer.wait_closed()
        raise RuntimeError(f"{status_line}: {detail[:160]}")
    return reader, writer


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


def _tcp_available(url: str, timeout: float = 0.5) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _read_api_key(value: str, path) -> str:
    if value.strip():
        return value.strip()
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def _extract_transcript(event: dict[str, object]) -> tuple[str, bool]:
    event_type = str(event.get("type") or "")
    final = any(token in event_type for token in ("completed", "final", "done"))
    for key in ("transcript", "text", "delta"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), final
    for key in ("response", "item", "conversation", "input_audio_transcription"):
        value = event.get(key)
        text = _find_text(value)
        if text:
            return text, final
    return "", final


def _find_text(value: object) -> str:
    if isinstance(value, dict):
        for key in ("transcript", "text", "delta"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        for nested in value.values():
            text = _find_text(nested)
            if text:
                return text
    if isinstance(value, list):
        for nested in value:
            text = _find_text(nested)
            if text:
                return text
    return ""


def _event_error_message(event: dict[str, object]) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "实时语音识别返回错误")
    if isinstance(error, str):
        return error
    return "实时语音识别返回错误"


def _notice_wav_bytes() -> bytes:
    rate = 16000
    duration = 0.72
    samples = int(rate * duration)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for index in range(samples):
            freq = 660 if index < samples * 0.52 else 980
            amp = int(11000 * math.sin(2 * math.pi * freq * index / rate))
            frames.extend(int(amp).to_bytes(2, byteorder="little", signed=True))
        wav.writeframes(bytes(frames))
    return buffer.getvalue()
