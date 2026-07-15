from __future__ import annotations

import asyncio
import json
import socket
import struct
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import websockets

from ..config import settings


def pcm16le_to_float32le(data: bytes) -> bytes:
    """Convert QSM microphone S16_LE frames to sherpa-onnx float PCM."""
    sample_count = len(data) // 2
    if sample_count == 0:
        return b""
    samples = struct.unpack(f"<{sample_count}h", data[: sample_count * 2])
    return struct.pack(f"<{sample_count}f", *(sample / 32768.0 for sample in samples))


def sherpa_transcript(raw: str | bytes) -> tuple[str, bool] | None:
    if raw == "Done!" or raw == b"Done!":
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    text = str(data.get("text") or data.get("transcript") or "").strip()
    if not text:
        return None
    final = bool(data.get("final") or data.get("is_final") or data.get("is_endpoint"))
    return text, final


class LocalAsrClient:
    def __init__(self, url: str | None = None) -> None:
        self.url = (url or settings.qsm_local_asr_url).rstrip("/")

    def status(self) -> dict[str, Any]:
        parsed = urlparse(self.url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        try:
            with socket.create_connection((host, port), timeout=0.7):
                pass
        except OSError as exc:
            return {
                "ok": False,
                "ready": False,
                "source": "qsm-local-asr",
                "error_message": str(exc),
            }
        return {
            "ok": True,
            "ready": True,
            "source": "qsm-local-asr",
            "model": "sherpa-onnx-streaming-zipformer-small-ctc-zh-int8",
        }

    async def recognize(
        self,
        microphone: asyncio.StreamReader,
        stopped: asyncio.Event,
    ) -> AsyncIterator[tuple[str, bool]]:
        async with websockets.connect(
            self.url,
            open_timeout=settings.qsm_local_asr_timeout_seconds,
            ping_interval=20,
            ping_timeout=20,
            max_size=2 * 1024 * 1024,
        ) as upstream:
            producer = asyncio.create_task(self._send_audio(upstream, microphone, stopped))
            try:
                async for raw in upstream:
                    result = sherpa_transcript(raw)
                    if result is None:
                        continue
                    yield result
                    if result[1]:
                        stopped.set()
                        return
            finally:
                stopped.set()
                await asyncio.gather(producer, return_exceptions=True)

    @staticmethod
    async def _send_audio(upstream, microphone: asyncio.StreamReader, stopped: asyncio.Event) -> None:
        try:
            while not stopped.is_set():
                audio = await microphone.read(3200)
                if not audio:
                    break
                converted = pcm16le_to_float32le(audio)
                if converted:
                    await upstream.send(converted)
        finally:
            try:
                await upstream.send("Done")
            except Exception:
                pass
