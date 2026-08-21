from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
import threading
from typing import Any

from .. import db
from ..config import settings
from ..modules.presentation_mode import PresentationModePolicy
from .qsm_client import QsmClient
from .qwen_realtime_tts import QwenRealtimeTts


_PLAYBACK_LOCK = threading.Lock()


async def _run_blocking(function, /, *args, **kwargs):
    """Run blocking audio I/O without binding completion to another event loop."""

    done = threading.Event()
    result: list[Any] = []
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            result.append(function(*args, **kwargs))
        except BaseException as exc:  # propagate on the caller's event loop
            errors.append(exc)
        finally:
            done.set()

    threading.Thread(
        target=invoke,
        name="zykh-speech-io",
        daemon=True,
    ).start()
    cancelled = False
    while not done.is_set():
        try:
            await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            # A synchronous QSM request cannot be interrupted once its worker
            # thread has entered urllib. Keep the task alive until that worker
            # exits so /audio/stream/stop can issue the final hardware STOP
            # after, rather than before, a stale speech request finishes.
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    if errors:
        raise errors[0]
    return result[0]


class SpeechService:
    """Own cloud/QSM speech routing for every terminal entry point."""

    def __init__(
        self,
        qsm_client: QsmClient | None = None,
        *,
        realtime_tts: QwenRealtimeTts | None = None,
        api_key_reader: Callable[[], str] | None = None,
    ) -> None:
        self.qsm_client = qsm_client or QsmClient()
        self.realtime_tts = realtime_tts or QwenRealtimeTts(self.qsm_client)
        self.api_key_reader = api_key_reader or self._dashscope_api_key

    def route(self):
        configured = db.get_setting(
            "network_mode",
            settings.network_preferred_mode,
        )
        return PresentationModePolicy.resolve(configured)

    async def speak(
        self,
        text: str,
        *,
        volume: int | None = None,
        speed: float | None = None,
    ) -> dict[str, Any]:
        if self.route().tts_mode == "offline":
            return await _run_blocking(
                self._speak_offline_sync,
                text,
                volume,
                speed,
            )
        while not _PLAYBACK_LOCK.acquire(blocking=False):
            await asyncio.sleep(0.01)
        try:
            return await self._speak_cloud_once(text, volume=volume, speed=speed)
        finally:
            _PLAYBACK_LOCK.release()

    def speak_sync(
        self,
        text: str,
        *,
        volume: int | None = None,
        speed: float | None = None,
    ) -> dict[str, Any]:
        if self.route().tts_mode == "offline":
            return self._speak_offline_sync(text, volume, speed)
        _PLAYBACK_LOCK.acquire()
        try:
            return asyncio.run(
                self._speak_cloud_once(text, volume=volume, speed=speed)
            )
        finally:
            _PLAYBACK_LOCK.release()

    def _speak_offline_sync(
        self,
        text: str,
        volume: int | None,
        speed: float | None,
    ) -> dict[str, Any]:
        with _PLAYBACK_LOCK:
            return self.qsm_client.audio_speak(
                text,
                volume,
                speed,
                "offline",
            )

    async def _speak_cloud_once(
        self,
        text: str,
        *,
        volume: int | None,
        speed: float | None,
    ) -> dict[str, Any]:
        result = await self.realtime_tts.speak(
            text,
            self.api_key_reader(),
            volume=volume,
            speed=speed,
        )
        if result.get("ok"):
            return result
        failure = str(result.get("error_message") or "实时语音合成暂不可用。")
        fallback = await self._speak_on_qsm(text, volume=volume, speed=speed)
        fallback["fallback_reason"] = failure
        return fallback

    def status(self) -> dict[str, Any]:
        route = self.route()
        qsm_status = self.qsm_client.audio_status()
        offline = qsm_status.get("offline")
        offline = offline if isinstance(offline, dict) else {}
        offline_available = bool(
            qsm_status.get("offline_available")
            or offline.get("available")
        )
        return {
            "ok": bool(qsm_status.get("ok")),
            "requested_mode": route.tts_mode,
            "tts_owner": "qsm",
            "offline_available": offline_available,
            "cloud_available": bool(self.api_key_reader()),
            "offline": offline,
            "raw": qsm_status,
        }

    async def status_async(self) -> dict[str, Any]:
        return await _run_blocking(self.status)

    async def stop(self) -> dict[str, Any]:
        return await _run_blocking(self.qsm_client.audio_stream_stop)

    def stop_sync(self) -> dict[str, Any]:
        return self.qsm_client.audio_stream_stop()

    async def _speak_on_qsm(
        self,
        text: str,
        *,
        volume: int | None,
        speed: float | None,
    ) -> dict[str, Any]:
        return await _run_blocking(
            self.qsm_client.audio_speak,
            text,
            volume,
            speed,
            "offline",
        )

    @staticmethod
    def _dashscope_api_key() -> str:
        value = str(settings.dashscope_api_key or "").strip()
        if value:
            return value
        path = Path(settings.dashscope_api_key_file)
        try:
            return path.read_text(encoding="utf-8").strip() if path.exists() else ""
        except OSError:
            return ""
