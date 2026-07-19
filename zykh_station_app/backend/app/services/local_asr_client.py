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


def build_paraformer_payload(data: bytes, sample_rate: int = 16000) -> bytes:
    """Build the binary request expected by sherpa's offline WebSocket server."""
    float_samples = pcm16le_to_float32le(data)
    return struct.pack("<II", sample_rate, len(float_samples)) + float_samples


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
    final_fields = ("final", "is_final", "is_endpoint")
    final = (
        any(bool(data.get(field)) for field in final_fields)
        if any(field in data for field in final_fields)
        else True
    )
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
            "model": settings.qsm_local_asr_model,
        }

    async def recognize(
        self,
        microphone: asyncio.StreamReader,
        stopped: asyncio.Event,
    ) -> AsyncIterator[tuple[str, bool]]:
        async with self.connection() as upstream:
            async for result in self.recognize_connected(upstream, microphone, stopped):
                yield result

    def connection(self):
        return websockets.connect(
            self.url,
            open_timeout=settings.qsm_local_asr_timeout_seconds,
            ping_interval=None,
            max_size=2 * 1024 * 1024,
        )

    async def recognize_connected(
        self,
        upstream: Any,
        microphone: asyncio.StreamReader,
        stopped: asyncio.Event,
    ) -> AsyncIterator[tuple[str, bool]]:
        pcm = await self._collect_audio(microphone, stopped)
        if not pcm:
            return
        payload = build_paraformer_payload(pcm)
        try:
            chunk_size = 10_240
            for offset in range(0, len(payload), chunk_size):
                await upstream.send(payload[offset : offset + chunk_size])
            raw = await asyncio.wait_for(
                upstream.recv(),
                timeout=settings.qsm_local_asr_timeout_seconds,
            )
            result = sherpa_transcript(raw)
            if result is not None:
                yield result[0], True
        finally:
            stopped.set()

    @staticmethod
    async def _collect_audio(microphone: asyncio.StreamReader, stopped: asyncio.Event) -> bytes:
        chunks: list[bytes] = []
        while True:
            if stopped.is_set():
                break
            try:
                audio = await asyncio.wait_for(microphone.read(3200), timeout=0.25)
            except TimeoutError:
                continue
            if not audio:
                break
            chunks.append(audio)
        return b"".join(chunks)
