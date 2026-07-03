from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from ..config import settings
from ..schemas.qsm import QsmStatus


class QsmClient:
    def __init__(self, mode: str | None = None, base_url: str | None = None) -> None:
        self.mode = (mode or settings.qsm_mode or "mock").lower()
        self.base_url = (base_url or settings.qsm_api_base).rstrip("/")

    def health_check(self) -> dict[str, Any]:
        status = self.get_qsm_status()
        return {
            "ok": status.connected,
            "mode": status.mode,
            "connected": status.connected,
            "base_url": status.base_url,
            "detail": status.detail,
            "error_message": status.error_message,
        }

    def get_qsm_status(self) -> QsmStatus:
        if self.mode != "real":
            return self._mock_status()

        payload, error = self._request_json("/api/status")
        if error:
            return self._real_unavailable(error)

        connected = bool(payload.get("ok", True))
        devices = self.get_device_status(payload)
        vitals = self.read_vitals() if connected else self._fallback_vitals()
        vitals_status = "available" if vitals.get("source") == "real" else "fallback"
        camera_status = str(devices.get("camera", "reserved"))
        dispense_status = "dry-run" if settings.dispense_dry_run else str(devices.get("dispense", "reserved"))
        device_status = self._device_label(connected, vitals_status, camera_status)
        error_message = None if connected else "外设网关返回不可用状态。"

        return QsmStatus(
            ok=connected,
            mode="real",
            connected=connected,
            base_url=self.base_url,
            device_status=device_status,
            vitals_status=vitals_status,
            camera_status=camera_status,
            dispense_status=dispense_status,
            error_message=error_message,
            status_label=device_status,
            vitals=vitals,
            devices=devices,
            detail="外设网关已响应" if connected else "外设网关返回不可用状态",
        )

    def read_vitals(self) -> dict[str, Any]:
        if self.mode != "real":
            return {"temperature_c": 35.7, "heart_rate": None, "spo2": None, "source": "mock"}
        payload, error = self._request_json("/api/vitals/read_all")
        if error:
            return self._fallback_vitals(error)
        vitals = payload.get("vitals") or payload
        if isinstance(vitals, dict):
            return {
                "temperature_c": vitals.get("temperature") or vitals.get("temperature_c") or 35.7,
                "heart_rate": vitals.get("heart_rate"),
                "spo2": vitals.get("spo2"),
                "source": "real",
            }
        return self._fallback_vitals("体征数据格式不可识别。")

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
                "camera": "reserved",
                "vitals": "unavailable",
                "dispense": "dry-run" if settings.dispense_dry_run else "ready",
                "voice": "reserved",
            }
        devices = payload.get("devices") if isinstance(payload.get("devices"), dict) else {}
        camera = devices.get("camera") or payload.get("camera_status") or ("available" if payload.get("ok") else "reserved")
        vitals = devices.get("vitals") or payload.get("vitals_status") or ("available" if payload.get("ok") else "unavailable")
        return {
            "camera": str(camera),
            "vitals": str(vitals),
            "dispense": "dry-run" if settings.dispense_dry_run else "ready",
            "voice": str(devices.get("voice") or "reserved"),
        }

    def capture_camera(self) -> dict[str, Any]:
        if self.mode != "real":
            return {"ok": True, "mode": "mock", "status": "mock", "image": None}
        payload, error = self._request_json("/api/camera/capture")
        if error:
            return {"ok": False, "mode": "real", "status": "reserved", "image": None, "error_message": error}
        return {
            "ok": bool(payload.get("ok", True)),
            "mode": "real",
            "status": str(payload.get("status", "available")),
            "image": payload.get("image") or payload.get("image_base64"),
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

    def _request_json(self, path: str) -> tuple[dict[str, Any], str | None]:
        try:
            with urlopen(f"{self.base_url}{path}", timeout=settings.qsm_timeout_seconds) as res:
                body = res.read().decode("utf-8")
            payload = json.loads(body) if body else {}
            if isinstance(payload, dict):
                return payload, None
            return {}, "外设网关返回格式不可识别。"
        except HTTPError as exc:
            return {}, f"外设网关 HTTP {exc.code}"
        except URLError as exc:
            return {}, f"外设网关连接失败：{exc.reason}"
        except TimeoutError:
            return {}, "外设网关连接超时。"
        except (OSError, json.JSONDecodeError) as exc:
            return {}, f"外设网关暂不可用：{exc}"

    def _real_unavailable(self, error_message: str) -> QsmStatus:
        devices = self.get_device_status()
        return QsmStatus(
            ok=False,
            mode="real",
            connected=False,
            base_url=self.base_url,
            device_status="暂不可用",
            vitals_status="unavailable",
            camera_status=devices["camera"],
            dispense_status=devices["dispense"],
            error_message=error_message,
            status_label="暂不可用",
            vitals=self._fallback_vitals(error_message),
            devices=devices,
            detail="外设网关暂不可用",
        )

    def _fallback_vitals(self, error_message: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"temperature_c": 35.7, "heart_rate": None, "spo2": None, "source": "fallback"}
        if error_message:
            payload["error_message"] = error_message
        return payload

    @staticmethod
    def _device_label(connected: bool, vitals_status: str, camera_status: str) -> str:
        if not connected:
            return "暂不可用"
        if vitals_status == "available" and camera_status == "available":
            return "可用"
        return "部分可用"

    def _mock_status(self) -> QsmStatus:
        return QsmStatus(
            ok=True,
            mode="mock",
            connected=True,
            base_url=self.base_url,
            device_status="部分可用",
            vitals_status="mock",
            camera_status="mock",
            dispense_status="dry-run",
            error_message=None,
            status_label="部分可用",
            vitals=self.read_vitals(),
            devices=self.get_device_status(),
            detail="mock 模式用于本机首页闭环演示",
        )
