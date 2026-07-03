from __future__ import annotations

import json
import socket
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import real_dispense_enabled, settings
from ..schemas.qsm import QsmStatus
from .local_camera import LocalCameraService


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

        payload, error = self._request_json(settings.qsm_status_path)
        if error:
            return self._real_unavailable(error)

        connected = bool(payload.get("ok", True))
        devices = self.get_device_status(payload)
        vitals = self._unavailable_vitals()
        vitals_status = devices.get("vitals", "available" if connected else "unavailable")
        camera_status = str(devices.get("camera", "reserved"))
        dispense_status = "ready" if real_dispense_enabled() else "dry-run"
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
        last_error = ""
        for path, partial in (
            (settings.qsm_vitals_all_path, False),
            (settings.qsm_vitals_path, False),
            (settings.qsm_temp_path, True),
        ):
            for method in ("POST", "GET"):
                payload, error = self._request_json(path, method=method, body_format="auto")
                if not error:
                    return self._parse_vitals(payload, partial=partial)
                last_error = error
        return self._unavailable_vitals(last_error)

    def read_temperature(self) -> dict[str, Any]:
        if self.mode != "real":
            return {"temperature_c": 35.7, "source": "mock"}
        payload, error = self._request_json(settings.qsm_temp_path, method="POST")
        if error:
            return self._unavailable_vitals(error)
        return self._parse_vitals(payload, partial=True)

    def _parse_vitals(self, payload: dict[str, Any], partial: bool = False) -> dict[str, Any]:
        vitals = payload.get("vitals") or payload
        temperature_payload = payload.get("temperature") if isinstance(payload.get("temperature"), dict) else {}
        if isinstance(vitals, dict):
            temperature = self._first_present(
                vitals,
                ("temperature", "temperature_c", "temp", "body_temp_c"),
                fallback=self._first_present(temperature_payload, ("body_temp_c",)),
            )
            return {
                "temperature_c": temperature,
                "heart_rate": self._first_present(vitals, ("heart_rate", "hr")),
                "spo2": self._first_present(vitals, ("spo2", "blood_oxygen")),
                "source": "real",
                "partial": partial,
                "raw": payload,
            }
        return self._unavailable_vitals("体征数据格式不可识别。")

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
                "dispense": "ready" if real_dispense_enabled() else "dry-run",
                "voice": "reserved",
            }
        devices = payload.get("devices") if isinstance(payload.get("devices"), dict) else {}
        camera = devices.get("camera") or payload.get("camera_status") or ("available" if payload.get("ok") else "reserved")
        vitals = devices.get("vitals") or payload.get("vitals_status") or ("available" if payload.get("ok") else "unavailable")
        return {
            "camera": str(camera),
            "vitals": str(vitals),
            "dispense": "ready" if real_dispense_enabled() else "dry-run",
            "voice": str(devices.get("voice") or "reserved"),
        }

    def capture_camera(self) -> dict[str, Any]:
        return LocalCameraService().capture()

    def dispense(self, slot: str, quantity: int, dry_run: bool = True) -> dict[str, Any]:
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "slot": slot,
                "quantity": quantity,
                "detail": "dry-run only",
            }
        if self.mode != "real":
            return {"ok": False, "dry_run": False, "slot": slot, "quantity": quantity, "detail": "QSM real 模式未启用。"}
        payload, error = self._request_json(
            settings.qsm_dispense_path,
            method="POST",
            payload={"slot": slot, "quantity": quantity},
            body_format="auto",
        )
        if error:
            return {"ok": False, "dry_run": False, "slot": slot, "quantity": quantity, "detail": error}
        ok = bool(payload.get("ok", payload.get("result") == "success"))
        return {
            "ok": ok,
            "dry_run": False,
            "slot": slot,
            "quantity": quantity,
            "detail": payload.get("detail") or payload.get("error") or payload.get("result") or "外设网关已返回。",
            "raw": payload,
        }

    def audio_asr(self, duration: int = 4) -> dict[str, Any]:
        return self._qsm_action(settings.qsm_audio_asr_path, {"duration": duration}, "语音识别")

    def audio_speak(self, text: str) -> dict[str, Any]:
        return self._qsm_action(settings.qsm_audio_speak_path, {"text": text}, "语音播报")

    def audio_beep(self) -> dict[str, Any]:
        return self._qsm_action(settings.qsm_audio_beep_path, {}, "提示音")

    def _qsm_action(self, path: str, payload: dict[str, Any], label: str) -> dict[str, Any]:
        if self.mode != "real":
            return {"ok": False, "mode": self.mode, "error_message": f"{label}需要 QSM real 模式。"}
        data, error = self._request_json(path, method="POST", payload=payload, body_format="auto")
        if error:
            return {"ok": False, "mode": "real", "error_message": error}
        data.setdefault("ok", True)
        data["mode"] = "real"
        return data

    def _request_json(
        self,
        path: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        body_format: str = "form",
    ) -> tuple[dict[str, Any], str | None]:
        formats = ["none"] if method == "GET" else ([body_format] if body_format in {"form", "json"} else ["form", "json"])
        errors: list[str] = []
        for item in formats:
            result, error = self._single_request_json(path, method=method, payload=payload, body_format=item)
            if not error:
                return result, None
            errors.append(error)
        return {}, errors[-1] if errors else "外设网关请求失败。"

    def _single_request_json(
        self,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        body_format: str,
    ) -> tuple[dict[str, Any], str | None]:
        try:
            data = None
            headers: dict[str, str] = {}
            if method != "GET":
                if body_format == "json":
                    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
                    headers["Content-Type"] = "application/json"
                else:
                    body = urlencode(payload or {}).encode("utf-8")
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                data = body
            request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
            with urlopen(request, timeout=settings.qsm_timeout_seconds) as res:
                body = res.read().decode("utf-8")
            if not body:
                return {}, "外设网关返回空响应。"
            payload = json.loads(body) if body else {}
            if isinstance(payload, dict):
                return payload, None
            return {}, "外设网关返回格式不可识别。"
        except HTTPError as exc:
            return {}, f"外设网关 HTTP {exc.code}"
        except URLError as exc:
            return {}, f"外设网关连接失败：{exc.reason}"
        except (TimeoutError, socket.timeout):
            return {}, "外设网关连接超时。"
        except (OSError, json.JSONDecodeError) as exc:
            return {}, f"外设网关暂不可用：{exc}"

    @staticmethod
    def _first_present(payload: dict[str, Any], keys: tuple[str, ...], fallback: Any = None) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return fallback

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
            vitals=self._unavailable_vitals(error_message),
            devices=devices,
            detail="外设网关暂不可用",
        )

    def _unavailable_vitals(self, error_message: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"temperature_c": None, "heart_rate": None, "spo2": None, "source": "unavailable"}
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
            detail="mock 模式用于本机闭环检查",
        )
