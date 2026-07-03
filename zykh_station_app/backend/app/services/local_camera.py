from __future__ import annotations

import os
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

    The current hardware split keeps camera capture on the host. This service
    intentionally avoids hard dependencies on camera libraries; real mode uses
    a lightweight device availability check and returns structured status.
    """

    def __init__(self, mode: str | None = None, device: str | None = None) -> None:
        self.mode = (mode or settings.local_camera_mode or "mock").lower()
        self.device = device or settings.local_camera_device

    def capture(self) -> dict[str, Any]:
        if self.mode != "real":
            return self._mock_capture()

        check = self.check()
        if not check["ok"]:
            return {
                "ok": False,
                "mode": "real",
                "status": "unavailable",
                "image_available": False,
                "image_path": None,
                "mock_recognition_result": None,
                "error_message": check["error_message"],
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

    def check(self) -> dict[str, Any]:
        if self.mode != "real":
            return {
                "ok": True,
                "mode": "mock",
                "status": "mock",
                "device": self.device,
                "error_message": None,
            }

        device_path = self._resolve_device_path()
        if device_path is None and os.name == "nt":
            return {
                "ok": True,
                "mode": "real",
                "status": "available",
                "device": self.device,
                "error_message": None,
            }
        if device_path and device_path.exists():
            return {
                "ok": True,
                "mode": "real",
                "status": "available",
                "device": str(device_path),
                "error_message": None,
            }
        return {
            "ok": False,
            "mode": "real",
            "status": "unavailable",
            "device": str(device_path or self.device),
            "error_message": "本机摄像头暂不可用。",
        }

    def capabilities(self) -> str:
        if self.mode != "real":
            return "mock"
        return "available" if self.check()["ok"] else "unavailable"

    def _resolve_device_path(self) -> Path | None:
        if self.device.isdigit():
            if os.name == "nt":
                return None
            return Path(f"/dev/video{self.device}")
        return Path(self.device)

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
