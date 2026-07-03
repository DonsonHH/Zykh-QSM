from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import settings
from ..db import now_text


MOCK_RECOGNITION_RESULT = {
    "medicine_id": "lianhua-qingwen",
    "name": "连花清瘟胶囊",
    "match_percent": 98,
    "barcode": "6901070303888",
    "spec": "24粒/盒",
    "quantity": "18盒",
    "expire_date": "2026-12-20",
    "slot": "B02",
}


class LocalCameraService:
    """Host-side camera seam.

    The current hardware split keeps camera capture on the host. Stage six only
    needs a stable capture/scan entry, so real mode performs a lightweight
    device availability check and returns a structured unavailable response
    instead of depending on a camera library.
    """

    def __init__(self, device_path: str | None = None) -> None:
        self.device_path = device_path or settings.local_camera_device

    def capture(self, mode: str) -> dict[str, Any]:
        if mode != "real":
            return self._mock_capture()

        device = Path(self.device_path)
        if not device.exists():
            return {
                "ok": False,
                "mode": "real",
                "status": "unavailable",
                "image_available": False,
                "image_path": None,
                "mock_recognition_result": None,
                "error_message": "本机摄像头暂不可用。",
                "captured_at": now_text(),
            }

        return {
            "ok": True,
            "mode": "real",
            "status": "available",
            "image_available": False,
            "image_path": None,
            "mock_recognition_result": None,
            "error_message": "本阶段仅验证本机摄像头入口，未保存真实图片。",
            "captured_at": now_text(),
        }

    def capabilities(self, mode: str) -> str:
        if mode != "real":
            return "mock"
        return "available" if Path(self.device_path).exists() else "unavailable"

    @staticmethod
    def _mock_capture() -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "mock",
            "status": "mock",
            "image_available": False,
            "image_path": None,
            "mock_recognition_result": MOCK_RECOGNITION_RESULT,
            "error_message": None,
            "captured_at": now_text(),
        }
