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

    def adb_shell(self, command: str, timeout: float = 5.0) -> dict[str, Any]:
        cmd = ["adb", "shell", command]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return {
                "ok": proc.returncode == 0,
                "command": " ".join(cmd),
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "returncode": proc.returncode,
            }
        except Exception as exc:
            return {"ok": False, "command": " ".join(cmd), "error": str(exc)}

    def forward_list(self) -> dict[str, Any]:
        try:
            proc = subprocess.run(["adb", "forward", "--list"], capture_output=True, text=True, timeout=5)
            text = proc.stdout.strip()
            expected = f"tcp:{QSM_ADB_LOCAL_PORT} tcp:{QSM_ADB_REMOTE_PORT}"
            return {
                "ok": proc.returncode == 0,
                "active": expected in text,
                "expected": expected,
                "output": text,
                "stderr": proc.stderr.strip(),
            }
        except Exception as exc:
            return {"ok": False, "active": False, "error": str(exc)}

    def gateway_diagnostics(self) -> dict[str, Any]:
        return {
            "adb": self.adb_devices(),
            "forward": self.ensure_forward(),
            "forward_list": self.forward_list(),
            "script": self.adb_shell(
                "ls -l /userdata/zykh_app/scripts/start_zykh_server.sh /userdata/zykh_app/server.pl 2>/dev/null",
                timeout=4,
            ),
            "process": self.adb_shell("ps | grep -E 'server.pl|perl|zykh' | grep -v grep", timeout=4),
            "port_8080": self.adb_shell(
                "netstat -ltnp 2>/dev/null | grep ':8080' || ss -ltnp 2>/dev/null | grep ':8080'",
                timeout=4,
            ),
        }

    def start_gateway(self) -> dict[str, Any]:
        start = self.adb_shell("sh /userdata/zykh_app/scripts/start_zykh_server.sh", timeout=8)
        status = self.get("/api/status", timeout=5.0)
        return {
            "ok": bool(status.get("ok")),
            "start": start,
            "peripheral": status,
            "diagnostics": self.gateway_diagnostics(),
        }

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=kwargs.pop("timeout", 20.0), trust_env=False) as client:
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
        with httpx.stream("GET", url, timeout=None, trust_env=False) as res:
            res.raise_for_status()
            for chunk in res.iter_bytes():
                if chunk:
                    yield chunk

    def get_bytes(self, path: str) -> tuple[bytes, str]:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=20.0, trust_env=False) as client:
            res = client.get(url)
            res.raise_for_status()
            return res.content, res.headers.get("content-type", "application/octet-stream")


qsm = QsmClient()
