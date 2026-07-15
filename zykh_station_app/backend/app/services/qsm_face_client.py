from __future__ import annotations

import json
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import settings


class QsmFaceClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.qsm_face_api_base).rstrip("/")

    def status(self) -> dict[str, Any]:
        return self._request(settings.qsm_face_status_path)

    def list_faces(self) -> dict[str, Any]:
        return self._request(settings.qsm_face_list_path)

    def identify(self, frames: int = 75) -> dict[str, Any]:
        return self._request(settings.qsm_face_identify_path, method="POST", payload={"frames": frames})

    def enroll(self, subject: str, samples: int = 18) -> dict[str, Any]:
        return self._request(
            settings.qsm_face_enroll_path,
            method="POST",
            payload={"subject": subject, "samples": samples},
            timeout=max(settings.qsm_face_timeout_seconds, 45),
        )

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        data = None
        headers: dict[str, str] = {}
        if method != "GET":
            data = urlencode(payload or {}).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout or settings.qsm_face_timeout_seconds) as response:
                body = response.read().decode("utf-8")
            result = json.loads(body)
            if not isinstance(result, dict):
                return self._error("人脸识别网关返回格式不可识别。")
            return result
        except HTTPError as exc:
            return self._error(f"人脸识别网关 HTTP {exc.code}")
        except URLError as exc:
            return self._error(f"人脸识别网关连接失败：{exc.reason}")
        except (TimeoutError, socket.timeout):
            return self._error("人脸识别超时，请正对摄像头后重试。")
        except (OSError, json.JSONDecodeError) as exc:
            return self._error(f"人脸识别暂不可用：{exc}")

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"ok": False, "status": "unavailable", "error_message": message}
