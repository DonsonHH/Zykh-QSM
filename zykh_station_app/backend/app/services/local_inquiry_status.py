from __future__ import annotations

from typing import Any

from ..config import settings


def local_inquiry_status(model_status: dict[str, Any]) -> dict[str, Any]:
    """Report QSM model health separately from the deterministic fallback."""
    status = dict(model_status)
    model_ready = bool(status.get("ready"))
    primary = "rules" if settings.offline_inquiry_mode == "rules" else "model"
    return {
        **status,
        "ready": model_ready,
        "model_ready": model_ready,
        "rules_fallback_ready": True,
        "primary": primary,
        "fallback": "" if primary == "rules" else "rules",
        "mode": "offline_rules" if primary == "rules" else "local_llm",
        "runtime_ready": model_ready,
        "runtime_status": str(status.get("status") or "unavailable"),
    }
