from __future__ import annotations

import json
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import settings


class QsmFingerprintClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.qsm_fingerprint_api_base).rstrip("/")

    def status(self) -> dict[str, Any]:
        return self._request(settings.qsm_fingerprint_status_path, timeout=10)

    def identify(self, timeout: int = 45) -> dict[str, Any]:
        return self._request(
            settings.qsm_fingerprint_identify_path,
            payload={"timeout": timeout},
            timeout=max(settings.qsm_fingerprint_timeout_seconds, timeout + 15),
        )

    def enroll(self, template_id: int, timeout: int = 45) -> dict[str, Any]:
        return self._request(
            settings.qsm_fingerprint_enroll_path,
            payload={"template_id": template_id, "timeout": timeout},
            timeout=max(settings.qsm_fingerprint_timeout_seconds, (timeout * 3) + 20),
        )

    def start_enrollment(self, template_id: int, timeout: int = 60) -> dict[str, Any]:
        return self._request(
            settings.qsm_fingerprint_enroll_start_path,
            payload={"template_id": template_id, "timeout": timeout},
            timeout=12,
        )

    def enrollment_progress(self, job_id: str) -> dict[str, Any]:
        from urllib.parse import quote

        path = f"{settings.qsm_fingerprint_enroll_progress_path}?job_id={quote(job_id, safe='')}"
        return self._request(path, timeout=8)

    def delete(self, template_id: int) -> dict[str, Any]:
        return self._request(settings.qsm_fingerprint_delete_path, payload={"template_id": template_id}, timeout=12)

    def _request(
        self,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method="POST" if data is not None else "GET",
        )
        try:
            with urlopen(request, timeout=timeout or settings.qsm_fingerprint_timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
            return result if isinstance(result, dict) else self._error("指纹网关返回格式不可识别。")
        except HTTPError as exc:
            return self._error(f"指纹网关 HTTP {exc.code}")
        except URLError as exc:
            return self._error(f"指纹网关连接失败：{exc.reason}")
        except (TimeoutError, socket.timeout):
            return self._error("指纹确认超时，请重新放置手指。", "timeout")
        except (OSError, json.JSONDecodeError) as exc:
            return self._error(f"指纹模块暂不可用：{exc}")

    @staticmethod
    def _error(message: str, status: str = "unavailable") -> dict[str, Any]:
        return {"ok": False, "status": status, "error_message": message}
