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

        payload, error = self._request_json(settings.qsm_status_path, timeout=settings.qsm_network_timeout_seconds)
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
        if not settings.qsm_vitals_prefer_full:
            temperature = self.read_temperature()
            if temperature.get("source") == "real":
                return temperature
            return self._read_full_vitals(fallback_error=str(temperature.get("error_message", "")))

        return self._read_full_vitals()

    def read_full_vitals(self) -> dict[str, Any]:
        if self.mode != "real":
            return {
                "temperature_c": 35.7,
                "heart_rate": 78,
                "spo2": 97,
                "source": "mock",
                "finger_detected": True,
                "quality": "mock",
                "message": "mock full vitals",
            }
        return self._read_full_vitals()

    def _read_full_vitals(self, fallback_error: str = "") -> dict[str, Any]:
        last_error = ""
        for path, partial in (
            (settings.qsm_vitals_all_path, False),
            (settings.qsm_vitals_path, False),
            (settings.qsm_temp_path, True),
        ):
            for method in ("POST", "GET"):
                payload, error = self._request_json(
                    path,
                    method=method,
                    body_format="auto",
                    timeout=settings.qsm_vitals_timeout_seconds,
                )
                if not error:
                    return self._parse_vitals(payload, partial=partial)
                last_error = error
        return self._unavailable_vitals(last_error or fallback_error)

    def read_temperature(self) -> dict[str, Any]:
        if self.mode != "real":
            return {"temperature_c": 35.7, "source": "mock"}
        payload, error = self._request_json(settings.qsm_temp_path, method="POST")
        if error:
            return self._unavailable_vitals(error)
        return self._parse_vitals(payload, partial=True)

    def _parse_vitals(self, payload: dict[str, Any], partial: bool = False) -> dict[str, Any]:
        vitals = payload.get("vitals") or payload
        sensors = payload.get("sensors") if isinstance(payload.get("sensors"), dict) else {}
        max30102 = sensors.get("max30102", {}).get("data") if isinstance(sensors.get("max30102"), dict) else {}
        gy614 = sensors.get("gy614", {}).get("data") if isinstance(sensors.get("gy614"), dict) else {}
        max30102 = max30102 if isinstance(max30102, dict) else {}
        gy614 = gy614 if isinstance(gy614, dict) else {}
        temperature_payload = payload.get("temperature") if isinstance(payload.get("temperature"), dict) else {}
        if isinstance(vitals, dict):
            temperature = self._first_present(gy614, ("body_temp_c", "target_temp_c"))
            if temperature is None:
                temperature = self._first_present(temperature_payload, ("body_temp_c", "target_temp_c"))
            if temperature is None:
                temperature = self._first_present(vitals, ("temperature_c", "temp", "body_temp_c", "temperature"))
            if isinstance(temperature, dict):
                temperature = self._first_present(temperature, ("body_temp_c", "target_temp_c"))
            finger_detected = self._first_present(max30102, ("finger_detected",))
            if finger_detected is None:
                finger_detected = self._first_present(vitals, ("finger_detected",))
            quality = self._first_present(max30102, ("quality",), fallback=self._first_present(vitals, ("quality",)))
            message = self._first_present(max30102, ("message",), fallback=self._first_present(vitals, ("message",)))
            heart_rate = self._first_present(max30102, ("heart_rate_bpm",))
            if heart_rate is None:
                heart_rate = self._first_present(vitals, ("heart_rate", "hr"))
            spo2 = self._first_present(max30102, ("spo2_percent",))
            if spo2 is None:
                spo2 = self._first_present(vitals, ("spo2", "blood_oxygen"))
            if finger_detected is False:
                if self._is_zeroish(heart_rate):
                    heart_rate = None
                if self._is_zeroish(spo2):
                    spo2 = None
            return {
                "temperature_c": temperature,
                "heart_rate": heart_rate,
                "spo2": spo2,
                "source": "real",
                "finger_detected": finger_detected,
                "quality": quality,
                "message": message,
                "sample_count": self._first_present(max30102, ("sample_count",), fallback=self._first_present(vitals, ("sample_count",))),
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
        payload: dict[str, Any] = {"slot": slot, "quantity": quantity}
        try:
            numeric_slot = int(slot)
            if 1 <= numeric_slot <= 23:
                payload["control_code"] = numeric_slot - 1
        except ValueError:
            pass
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
            payload=payload,
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
            "detail": payload.get("message") or payload.get("detail") or payload.get("error") or payload.get("result") or "外设网关已返回。",
            "raw": payload,
        }

    def audio_asr(self, duration: int = 4) -> dict[str, Any]:
        return self._qsm_action(settings.qsm_audio_asr_path, {"duration": duration}, "语音识别")

    def audio_speak(self, text: str, volume: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text}
        if volume is not None:
            payload["volume"] = max(0, min(int(volume), 255))
        return self._qsm_action(settings.qsm_audio_speak_path, payload, "语音播报")

    def audio_beep(self, volume: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if volume is not None:
            payload["volume"] = max(0, min(int(volume), 255))
        return self._qsm_action(settings.qsm_audio_beep_path, payload, "提示音")

    def audio_play_base64(self, audio_base64: str, fmt: str = "wav", volume: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"audio_base64": audio_base64, "format": fmt}
        if volume is not None:
            payload["volume"] = max(0, min(int(volume), 255))
        return self._qsm_action(
            settings.qsm_audio_play_path,
            payload,
            "音频播放",
        )

    def get_network_status(self) -> dict[str, Any]:
        if self.mode != "real":
            return {
                "ok": False,
                "mode": self.mode,
                "sim_present": False,
                "connected": False,
                "signal": "none",
                "status": "unavailable",
                "error_message": "QSM real 模式未启用，无法读取真实 SIM 状态。",
            }
        payload, error = self._request_json(
            settings.qsm_network_status_path,
            method="GET",
            timeout=settings.qsm_network_timeout_seconds,
        )
        if error:
            status = self.get_qsm_status()
            network = status.devices.get("network") if isinstance(status.devices, dict) else None
            if isinstance(network, dict):
                return network
            return {"ok": False, "error_message": error, "sim_present": False, "connected": False, "signal": "none"}
        return payload

    def start_4g_network(self) -> dict[str, Any]:
        return self._qsm_action(
            settings.qsm_network_start_4g_path,
            {},
            "SIM 网络启动",
            timeout=settings.qsm_network_timeout_seconds + 70,
        )

    def _qsm_action(
        self,
        path: str,
        payload: dict[str, Any],
        label: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if self.mode != "real":
            return {"ok": False, "mode": self.mode, "error_message": f"{label}需要 QSM real 模式。"}
        data, error = self._request_json(path, method="POST", payload=payload, body_format="auto", timeout=timeout)
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
        timeout: float | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        formats = ["none"] if method == "GET" else ([body_format] if body_format in {"form", "json"} else ["form", "json"])
        errors: list[str] = []
        for item in formats:
            result, error = self._single_request_json(path, method=method, payload=payload, body_format=item, timeout=timeout)
            if not error:
                return result, None
            errors.append(error)
            if "超时" in error:
                return {}, error
        return {}, errors[-1] if errors else "外设网关请求失败。"

    def _single_request_json(
        self,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        body_format: str,
        timeout: float | None = None,
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
            with urlopen(request, timeout=timeout or settings.qsm_timeout_seconds) as res:
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

    @staticmethod
    def _is_zeroish(value: Any) -> bool:
        try:
            return float(value) == 0
        except (TypeError, ValueError):
            return False

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
