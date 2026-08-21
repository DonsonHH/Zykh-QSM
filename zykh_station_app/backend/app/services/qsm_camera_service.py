from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import BinaryIO, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from ..config import DATA_DIR, settings
from ..db import now_text


class QsmCameraService:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.qsm_api_base).rstrip("/")
        self.capture_dir = DATA_DIR / "captures"
        self.latest_path = self.capture_dir / "qsm-live-latest.jpg"

    def open_stream(
        self,
        *,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        quality: int = 80,
    ) -> tuple[BinaryIO | None, str, str | None]:
        query = urlencode(
            {
                "width": max(320, min(width, 1920)),
                "height": max(240, min(height, 1080)),
                "fps": 30 if fps >= 25 else 15,
                "quality": max(50, min(quality, 92)),
            }
        )
        request = Request(f"{self.base_url}{settings.qsm_camera_stream_path}?{query}", method="GET")
        for attempt in range(4):
            try:
                response = urlopen(request, timeout=12)
                content_type = response.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=zykhframe")
                if "multipart/x-mixed-replace" not in content_type:
                    body = response.read(800).decode("utf-8", errors="replace")
                    response.close()
                    return None, content_type, self._gateway_error(body)
                return response, content_type, None
            except HTTPError as exc:
                if 500 <= exc.code < 600 and attempt < 3:
                    exc.close()
                    time.sleep(0.35 * (attempt + 1))
                    continue
                return None, "", f"外设摄像头 HTTP {exc.code}"
            except URLError as exc:
                return None, "", f"外设摄像头连接失败：{exc.reason}"
            except (TimeoutError, socket.timeout):
                return None, "", "外设摄像头连接超时。"
            except OSError as exc:
                return None, "", f"外设摄像头暂不可用：{exc}"
        return None, "", "外设摄像头视频流暂不可用。"

    def stream_chunks(self, response: BinaryIO) -> Iterator[bytes]:
        buffer = b""
        last_saved = 0.0
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        try:
            while True:
                read_method = getattr(response, "read1", response.read)
                try:
                    chunk = read_method(65536)
                except (TimeoutError, socket.timeout, OSError):
                    break
                if not chunk:
                    break
                buffer = (buffer + chunk)[-3_000_000:]
                frame, buffer = self.extract_latest_jpeg(buffer)
                if frame and time.monotonic() - last_saved >= 0.35:
                    self._save_frame(frame)
                    last_saved = time.monotonic()
                yield chunk
        finally:
            response.close()

    def latest_frame(self, max_age_seconds: float = 3.0) -> Path | None:
        try:
            if self.latest_path.exists() and time.time() - self.latest_path.stat().st_mtime <= max_age_seconds:
                return self.latest_path
        except OSError:
            return None
        return None

    def capture(self) -> dict[str, object]:
        payload, error = self._request_capture()
        if error:
            return self._unavailable(error)
        image_url = str(payload.get("image_url") or "")
        if not image_url:
            return self._unavailable(str(payload.get("error") or payload.get("detail") or "外设摄像头未返回图片地址。"))
        try:
            with urlopen(Request(f"{self.base_url}{image_url}", method="GET"), timeout=10) as response:
                image = response.read()
        except (HTTPError, URLError, TimeoutError, socket.timeout, OSError) as exc:
            return self._unavailable(f"读取外设摄像头图片失败：{exc}")
        if len(image) < 1000 or not image.startswith(b"\xff\xd8"):
            return self._unavailable("外设摄像头返回的图片无效。")
        self._save_frame(image)
        return {
            "ok": True,
            "mode": "real",
            "status": "available",
            "image_available": True,
            "image_path": str(self.latest_path),
            "image_url": "/api/camera/image/latest",
            "error_message": None,
            "captured_at": now_text(),
            "device": "qsm-camera",
        }

    def capabilities(self) -> str:
        try:
            with urlopen(
                Request(f"{self.base_url}{settings.qsm_gateway_health_path}", method="GET"),
                timeout=3,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return "available" if payload.get("ok", True) else "unavailable"
        except (HTTPError, URLError, TimeoutError, socket.timeout, OSError, json.JSONDecodeError):
            return "unavailable"

    def _request_capture(self) -> tuple[dict[str, object], str | None]:
        request = Request(
            f"{self.base_url}{settings.qsm_camera_capture_path}",
            data=b"",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict):
                return payload, None
            return {}, "外设摄像头返回格式不可识别。"
        except HTTPError as exc:
            return {}, f"外设摄像头 HTTP {exc.code}"
        except URLError as exc:
            return {}, f"外设摄像头连接失败：{exc.reason}"
        except (TimeoutError, socket.timeout):
            return {}, "外设摄像头抓拍超时。"
        except (OSError, json.JSONDecodeError) as exc:
            return {}, f"外设摄像头暂不可用：{exc}"

    def _save_frame(self, image: bytes) -> None:
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.latest_path.with_name(
            f".{self.latest_path.name}.{uuid4().hex}.tmp"
        )
        try:
            temporary.write_bytes(image)
            temporary.replace(self.latest_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _unavailable(self, message: str) -> dict[str, object]:
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

    @staticmethod
    def extract_latest_jpeg(buffer: bytes) -> tuple[bytes | None, bytes]:
        latest: bytes | None = None
        search_from = 0
        consumed = 0
        while True:
            start = buffer.find(b"\xff\xd8", search_from)
            if start < 0:
                break
            end = buffer.find(b"\xff\xd9", start + 2)
            if end < 0:
                return latest, buffer[start:]
            latest = buffer[start : end + 2]
            consumed = end + 2
            search_from = consumed
        return latest, buffer[consumed:] if consumed else buffer[-2_000_000:]

    @staticmethod
    def _gateway_error(body: str) -> str:
        try:
            payload = json.loads(body)
            return str(payload.get("error") or payload.get("detail") or "外设摄像头视频流不可用。")
        except json.JSONDecodeError:
            return "外设摄像头视频流不可用。"
