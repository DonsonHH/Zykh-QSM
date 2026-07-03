from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config import DATA_DIR, settings
from ..db import now_text


class LocalCameraService:
    """Host-side camera seam.

    The current hardware split keeps camera capture on the host. Real mode
    captures an actual still image. If the camera or capture command fails,
    callers receive a structured error instead of a sample result.
    """

    def __init__(self, mode: str | None = None, device: str | None = None) -> None:
        self.mode = (mode or settings.local_camera_mode or "mock").lower()
        self.device = device or settings.local_camera_device

    def capture(self) -> dict[str, Any]:
        if self.mode != "real":
            return self._unavailable("本机摄像头真实模式未启用。")

        check = self.check()
        if not check["ok"]:
            return self._unavailable(check["error_message"])

        image_dir = DATA_DIR / "captures"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / f"capture-{now_text().replace(' ', '-').replace(':', '')}.jpg"
        device = str(check["device"])
        command = self._capture_command(device, image_path)
        if not command:
            return self._unavailable("未找到可用摄像头抓拍命令，请配置 LOCAL_CAMERA_CAPTURE_CMD。")

        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return self._unavailable(f"摄像头抓拍失败：{exc}")

        if image_path.exists() and image_path.stat().st_size > 0:
            return {
                "ok": True,
                "mode": "real",
                "status": "available",
                "image_available": True,
                "image_path": str(image_path),
                "image_url": None,
                "error_message": None,
                "captured_at": now_text(),
                "command": " ".join(command),
            }
        stderr = (result.stderr or result.stdout or "").strip()
        return self._unavailable(f"摄像头未生成图片：{stderr[:240]}")

    def _unavailable(self, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "mode": "real",
            "status": "unavailable",
            "image_available": False,
            "image_path": None,
            "image_url": None,
            "error_message": message,
            "captured_at": now_text(),
        }

    def check(self) -> dict[str, Any]:
        if self.mode != "real":
            return {"ok": False, "mode": self.mode, "status": "unavailable", "device": self.device, "error_message": "摄像头真实模式未启用。"}

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
            return "unavailable"
        return "available" if self.check()["ok"] else "unavailable"

    def _resolve_device_path(self) -> Path | None:
        if self.device == "auto":
            return self._auto_device_path()
        if self.device.isdigit():
            if os.name == "nt":
                return None
            return Path(f"/dev/video{self.device}")
        return Path(self.device)

    @staticmethod
    def _auto_device_path() -> Path | None:
        preferred = [Path("/dev/video23"), Path("/dev/video0"), Path("/dev/video5"), Path("/dev/video-camera0")]
        for path in preferred:
            if path.exists():
                return path
        for path in sorted(Path("/dev").glob("video*")):
            if path.exists():
                return path
        return None

    def _capture_command(self, device: str, image_path: Path) -> list[str] | None:
        if settings.local_camera_capture_cmd:
            command = settings.local_camera_capture_cmd.format(device=device, out=str(image_path))
            return ["sh", "-c", command]
        if shutil.which("gst-launch-1.0"):
            return [
                "gst-launch-1.0",
                "-q",
                "v4l2src",
                f"device={device}",
                "num-buffers=1",
                "!",
                "videoconvert",
                "!",
                "jpegenc",
                "!",
                "filesink",
                f"location={image_path}",
            ]
        if shutil.which("ffmpeg"):
            return [
                "ffmpeg",
                "-y",
                "-f",
                "v4l2",
                "-i",
                device,
                "-frames:v",
                "1",
                str(image_path),
            ]
        return None
