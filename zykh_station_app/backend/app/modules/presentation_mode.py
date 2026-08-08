from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresentationRoute:
    display_mode: str
    ai_mode: str
    tts_mode: str
    realtime_sync_enabled: bool


class PresentationModePolicy:
    """Resolve the kiosk's two demonstration modes behind one stable seam."""

    @staticmethod
    def resolve(configured_mode: object) -> PresentationRoute:
        normalized = str(configured_mode or "").strip().lower()
        if normalized in {"local", "offline"}:
            return PresentationRoute(
                display_mode="local",
                ai_mode="cloud",
                tts_mode="offline",
                realtime_sync_enabled=False,
            )
        return PresentationRoute(
            display_mode="online",
            ai_mode="cloud",
            tts_mode="cloud",
            realtime_sync_enabled=True,
        )
