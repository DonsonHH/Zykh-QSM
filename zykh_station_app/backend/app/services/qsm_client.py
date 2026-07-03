from __future__ import annotations

import json
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from ..config import settings
from ..schemas.qsm import QsmStatus


class QsmClient:
    def __init__(self, mode: str | None = None, base_url: str | None = None) -> None:
        self.mode = (mode or settings.qsm_mode or "mock").lower()
        self.base_url = (base_url or settings.qsm_api_base).rstrip("/")

    def health_check(self) -> dict[str, Any]:
        if self.mode != "real":
            return {"ok": True, "mode": "mock", "detail": "mock gateway ready"}
        status = self.get_qsm_status()
        return {"ok": status.ok, "mode": "real", "detail": status.detail}

    def get_qsm_status(self) -> QsmStatus:
        if self.mode != "real":
            return self._mock_status()
        try:
            with urlopen(f"{self.base_url}/api/status", timeout=settings.qsm_timeout_seconds) as res:
                body = res.read().decode("utf-8")
            payload = json.loads(body)
            ok = bool(payload.get("ok", False))
            return QsmStatus(
                ok=ok,
                mode="real",
                status_label="可用" if ok else "部分可用",
                vitals=self.read_vitals(),
                devices=self.get_device_status(payload),
                detail="外设网关已响应" if ok else "外设网关返回异常状态",
            )
        except (OSError, URLError, json.JSONDecodeError) as exc:
            return QsmStatus(
                ok=False,
                mode="real",
                status_label="部分可用",
                vitals=self.read_vitals(),
                devices=self.get_device_status(),
                detail=f"外设网关暂不可用：{exc}",
            )

    def read_vitals(self) -> dict[str, Any]:
        if self.mode != "real":
            return {"temperature_c": 35.7, "heart_rate": None, "spo2": None, "source": "mock"}
        try:
            with urlopen(f"{self.base_url}/api/vitals/read_all", timeout=settings.qsm_timeout_seconds) as res:
                payload = json.loads(res.read().decode("utf-8"))
            vitals = payload.get("vitals") or payload
            if isinstance(vitals, dict):
                return {
                    "temperature_c": vitals.get("temperature") or vitals.get("temperature_c") or 0,
                    "heart_rate": vitals.get("heart_rate"),
                    "spo2": vitals.get("spo2"),
                    "source": "real",
                }
        except (OSError, URLError, json.JSONDecodeError):
            pass
        return {"temperature_c": 35.7, "heart_rate": None, "spo2": None, "source": "fallback"}

    def get_device_status(self, payload: dict[str, Any] | None = None) -> dict[str, str]:
        if self.mode != "real":
            return {
                "camera": "mock",
                "vitals": "mock",
                "dispense": "dry-run",
                "voice": "mock",
            }
        if not payload:
            return {
                "camera": "unknown",
                "vitals": "unknown",
                "dispense": "dry-run" if settings.dispense_dry_run else "ready",
                "voice": "unknown",
            }
        return {
            "camera": "available" if payload.get("ok") else "unknown",
            "vitals": "available" if payload.get("ok") else "unknown",
            "dispense": "dry-run" if settings.dispense_dry_run else "ready",
            "voice": "available" if payload.get("ok") else "unknown",
        }

    def dispense(self, slot: str, quantity: int, dry_run: bool = True) -> dict[str, Any]:
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "slot": slot,
                "quantity": quantity,
                "detail": "dry-run only",
            }
        return {
            "ok": False,
            "dry_run": False,
            "slot": slot,
            "quantity": quantity,
            "detail": "real dispense is reserved for a later integration stage",
        }

    def _mock_status(self) -> QsmStatus:
        return QsmStatus(
            ok=True,
            mode="mock",
            status_label="部分可用",
            vitals=self.read_vitals(),
            devices=self.get_device_status(),
            detail="mock 模式用于本机首页闭环演示",
        )
