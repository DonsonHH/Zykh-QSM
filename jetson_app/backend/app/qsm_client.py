from __future__ import annotations

import subprocess
from typing import Any, Iterator

import httpx

from .config import QSM_ADB_AUTO_FORWARD, QSM_ADB_LOCAL_PORT, QSM_ADB_REMOTE_PORT, QSM_API_BASE


class QsmClient:
    def __init__(self, base_url: str = QSM_API_BASE) -> None:
        self.base_url = base_url.rstrip("/")

    def ensure_forward(self) -> dict[str, Any]:
        if not QSM_ADB_AUTO_FORWARD:
            return {"ok": True, "enabled": False, "detail": "ADB auto-forward disabled"}
        cmd = ["adb", "forward", f"tcp:{QSM_ADB_LOCAL_PORT}", f"tcp:{QSM_ADB_REMOTE_PORT}"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return {
                "ok": proc.returncode == 0,
                "command": " ".join(cmd),
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        except Exception as exc:
            return {"ok": False, "command": " ".join(cmd), "stderr": str(exc)}

    def adb_devices(self) -> dict[str, Any]:
        try:
            proc = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, timeout=5)
            text = proc.stdout.strip()
            connected = any(" device " in f" {line} " for line in text.splitlines()[1:])
            return {"ok": proc.returncode == 0, "connected": connected, "output": text}
        except Exception as exc:
            return {"ok": False, "connected": False, "error": str(exc)}

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=kwargs.pop("timeout", 20.0)) as client:
                res = client.request(method, url, **kwargs)
                content_type = res.headers.get("content-type", "")
                if "application/json" in content_type:
                    data = res.json()
                else:
                    data = {"ok": res.is_success, "body": res.text[:1200]}
                if isinstance(data, dict):
                    data.setdefault("qsm_status", res.status_code)
                return data
        except Exception as exc:
            return {"ok": False, "error": f"外设设备请求失败: {exc}", "url": url}

    def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.request("POST", path, data=data or {}, **kwargs)

    def stream_bytes(self, path: str) -> Iterator[bytes]:
        url = f"{self.base_url}{path}"
        with httpx.stream("GET", url, timeout=None) as res:
            res.raise_for_status()
            for chunk in res.iter_bytes():
                if chunk:
                    yield chunk

    def get_bytes(self, path: str) -> tuple[bytes, str]:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=20.0) as client:
            res = client.get(url)
            res.raise_for_status()
            return res.content, res.headers.get("content-type", "application/octet-stream")


qsm = QsmClient()
