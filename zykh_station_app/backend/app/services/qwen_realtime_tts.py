from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any
from uuid import uuid4

import websockets

from ..config import settings
from .qsm_client import QsmClient


def session_update_event(speed: float | None = None) -> dict[str, Any]:
    speech_rate = max(0.5, min(float(speed or settings.qwen_realtime_tts_speed), 2.0))
    return {
        "event_id": f"event_{uuid4().hex}",
        "type": "session.update",
        "session": {
            "voice": settings.qwen_realtime_tts_voice,
            "mode": "commit",
            "response_format": "pcm",
            "sample_rate": 24000,
            "speech_rate": speech_rate,
            "instructions": settings.qwen_realtime_tts_instructions,
            "optimize_instructions": False,
        },
    }


def audio_delta(event: dict[str, Any]) -> bytes:
    if event.get("type") != "response.audio.delta":
        return b""
    encoded = event.get("delta")
    if not isinstance(encoded, str) or not encoded:
        return b""
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return b""


class QwenRealtimeTts:
    def __init__(self, qsm_client: QsmClient | None = None) -> None:
        self.qsm_client = qsm_client or QsmClient()

    async def speak(
        self,
        text: str,
        api_key: str,
        *,
        volume: int | None = None,
        speed: float | None = None,
    ) -> dict[str, Any]:
        clean = " ".join(text.strip().split())[:320]
        if not clean:
            return {"ok": False, "error_message": "播报文本为空。"}
        if not api_key:
            return {"ok": False, "error_message": "未配置 DashScope API Key。"}

        volume = max(0, min(int(volume if volume is not None else 230), 255))
        await asyncio.to_thread(self.qsm_client.audio_stream_stop)
        start_result = await asyncio.to_thread(
            self.qsm_client.audio_stream_start,
            port=settings.qsm_audio_stream_port,
            volume=volume,
            rate=24000,
            channels=1,
        )
        if not start_result.get("ok"):
            return {
                "ok": False,
                "error_message": start_result.get("error_message") or start_result.get("detail") or "外设音频流启动失败。",
                "raw": start_result,
            }

        writer: asyncio.StreamWriter | None = None
        started_at = time.monotonic()
        first_audio_at: float | None = None
        audio_bytes = 0
        session_id = ""
        model = settings.qwen_realtime_tts_model
        url = f"{settings.qwen_realtime_tts_url}?model={model}"
        try:
            _, writer = await self._open_qsm_output()
            headers = {"Authorization": f"Bearer {api_key}"}
            async with websockets.connect(
                url,
                additional_headers=headers,
                open_timeout=8,
                ping_interval=20,
                ping_timeout=20,
                max_size=4 * 1024 * 1024,
            ) as upstream:
                await upstream.send(json.dumps(session_update_event(speed), ensure_ascii=False))
                await upstream.send(
                    json.dumps(
                        {
                            "event_id": f"event_{uuid4().hex}",
                            "type": "input_text_buffer.append",
                            "text": clean,
                        },
                        ensure_ascii=False,
                    )
                )
                await upstream.send(json.dumps({"event_id": f"event_{uuid4().hex}", "type": "input_text_buffer.commit"}))
                await upstream.send(json.dumps({"event_id": f"event_{uuid4().hex}", "type": "session.finish"}))

                async def receive_audio() -> None:
                    nonlocal session_id, first_audio_at, audio_bytes
                    async for raw in upstream:
                        try:
                            event = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if event.get("type") == "session.created":
                            session_id = str(event.get("session", {}).get("id") or "")
                        chunk = audio_delta(event)
                        if chunk:
                            if first_audio_at is None:
                                first_audio_at = time.monotonic()
                            writer.write(chunk)
                            await writer.drain()
                            audio_bytes += len(chunk)
                        if event.get("type") in {"error", "session.error"} or event.get("error"):
                            message = event.get("error", {}).get("message") if isinstance(event.get("error"), dict) else event.get("message")
                            raise RuntimeError(str(message or "实时语音合成失败。"))
                        if event.get("type") == "session.finished":
                            break
                await asyncio.wait_for(
                    receive_audio(),
                    timeout=settings.qwen_realtime_tts_timeout_seconds,
                )
            return {
                "ok": audio_bytes > 0,
                "mode": "qwen-realtime-pcm",
                "engine": "qwen-realtime-pcm",
                "model": model,
                "session_id": session_id,
                "audio_bytes": audio_bytes,
                "first_audio_ms": round(((first_audio_at or time.monotonic()) - started_at) * 1000),
                "total_ms": round((time.monotonic() - started_at) * 1000),
                "speed": session_update_event(speed)["session"]["speech_rate"],
                "volume": volume,
                "offline": False,
                "detail": "实时语音已边生成边发送到外设喇叭。" if audio_bytes else "实时语音未返回音频。",
            }
        except Exception as exc:
            return {
                "ok": False,
                "mode": "qwen-realtime-pcm",
                "model": model,
                "audio_bytes": audio_bytes,
                "error_message": str(exc),
            }
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await asyncio.to_thread(self.qsm_client.audio_stream_stop)

    @staticmethod
    async def _open_qsm_output() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        last_error: Exception | None = None
        for _ in range(12):
            try:
                return await asyncio.open_connection(
                    settings.qsm_audio_stream_host,
                    settings.qsm_audio_stream_port,
                )
            except OSError as exc:
                last_error = exc
                await asyncio.sleep(0.1)
        raise RuntimeError(f"无法连接外设 PCM 播放端口：{last_error}")
