from __future__ import annotations

from typing import Any

from ..config import settings


def local_inquiry_status(model_status: dict[str, Any]) -> dict[str, Any]:
    """Describe the usable offline inquiry path without hiding model health."""
    status = dict(model_status)
    if settings.offline_inquiry_mode != "rules":
        return status

    runtime_ready = bool(status.get("ready"))
    return {
        **status,
        "ready": True,
        "status": "ready",
        "mode": "offline_rules",
        "model": "本地离线问询",
        "runtime_ready": runtime_ready,
        "runtime_status": str(status.get("status") or "unavailable"),
    }
