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


CABINET_CONTROL_CODE_BY_SLOT: dict[int, int] = {
    1: 3,
    2: 2,
    3: 1,
    4: 0,
    5: 7,
    6: 6,
    7: 5,
    8: 4,
    9: 9,
    10: 8,
    11: 11,
    12: 10,
    13: 13,
    14: 12,
    15: 16,
    16: 15,
    17: 14,
    18: 19,
    19: 18,
    20: 17,
    21: 22,
    22: 21,
    23: 20,
}


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

        payload, error = self._request_json(settings.qsm_status_path, timeout=settings.qsm_timeout_seconds)
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
        integrated = {}
        integrated_ok = True
        integrated_error = ""
        for sensor_name in ("uart_vitals", "integrated_vitals", "max30102"):
            sensor_entry = sensors.get(sensor_name)
            if not isinstance(sensor_entry, dict):
                continue
            integrated_ok = bool(sensor_entry.get("ok", True))
            if isinstance(sensor_entry.get("data"), dict):
                integrated = sensor_entry["data"]
            if not integrated_ok:
                integrated_error = str(
                    integrated.get("error")
                    or sensor_entry.get("error")
                    or sensor_entry.get("detail")
                    or "综合体征模块读取失败。"
                )
            break
        gy614_entry = sensors.get("gy614") if isinstance(sensors.get("gy614"), dict) else {}
        gy614_ok = bool(gy614_entry.get("ok", True))
        gy614 = gy614_entry.get("data") if isinstance(gy614_entry.get("data"), dict) else {}
        gy614_error = ""
        if not gy614_ok:
            gy614_error = str(gy614_entry.get("error") or gy614_entry.get("detail") or "额温模块读取失败。")
        integrated = integrated if isinstance(integrated, dict) else {}
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
            if self._is_zeroish(temperature):
                temperature = None
            finger_detected = self._first_present(integrated, ("finger_detected",))
            if finger_detected is None:
                finger_detected = self._first_present(vitals, ("finger_detected",))
            quality = self._first_present(integrated, ("quality",), fallback=self._first_present(vitals, ("quality",)))
            message = self._first_present(integrated, ("message",), fallback=self._first_present(vitals, ("message",)))
            heart_rate = self._first_present(integrated, ("heart_rate_bpm", "heart_rate", "hr"))
            if heart_rate is None:
                heart_rate = self._first_present(vitals, ("heart_rate", "hr"))
            spo2 = self._first_present(integrated, ("spo2_percent", "spo2", "blood_oxygen"))
            if spo2 is None:
                spo2 = self._first_present(vitals, ("spo2", "blood_oxygen"))
            systolic_pressure = self._first_present(
                integrated,
                ("systolic_pressure", "systolic", "systolic_bp"),
                fallback=self._first_present(vitals, ("systolic_pressure", "systolic", "systolic_bp")),
            )
            diastolic_pressure = self._first_present(
                integrated,
                ("diastolic_pressure", "diastolic", "diastolic_bp"),
                fallback=self._first_present(vitals, ("diastolic_pressure", "diastolic", "diastolic_bp")),
            )
            respiratory_rate = self._first_present(
                integrated,
                ("respiratory_rate", "respiration_rate"),
                fallback=self._first_present(vitals, ("respiratory_rate", "respiration_rate")),
            )
            microcirculation = self._first_present(integrated, ("microcirculation",))
            fatigue = self._first_present(integrated, ("fatigue",))
            rr_interval = self._first_present(integrated, ("rr_interval",))
            hrv_sdnn = self._first_present(integrated, ("hrv_sdnn", "sdnn"))
            hrv_rmssd = self._first_present(integrated, ("hrv_rmssd", "rmssd"))
            sensor_body_temperature = self._first_present(
                integrated,
                ("body_temperature_c", "sensor_body_temperature"),
            )
            ambient_temperature = self._first_present(
                integrated,
                ("ambient_temperature_c", "ambient_temperature"),
            )
            reference_ready = self._first_present(integrated, ("reference_ready",), fallback=False)
            if self._is_zeroish(heart_rate):
                heart_rate = None
            if self._is_zeroish(spo2):
                spo2 = None
            if self._is_zeroish(systolic_pressure):
                systolic_pressure = None
            if self._is_zeroish(diastolic_pressure):
                diastolic_pressure = None
            if self._is_zeroish(respiratory_rate):
                respiratory_rate = None
            if self._is_zeroish(microcirculation):
                microcirculation = None
            if self._is_zeroish(fatigue):
                fatigue = None
            if self._is_zeroish(rr_interval):
                rr_interval = None
            if self._is_zeroish(hrv_sdnn):
                hrv_sdnn = None
            if self._is_zeroish(hrv_rmssd):
                hrv_rmssd = None
            if not integrated_ok:
                quality = "error"
                message = integrated_error
                partial = True
            if not gy614_ok:
                partial = True
            if finger_detected is False:
                quality = quality or "no_finger"
            errors = [item for item in (integrated_error, gy614_error, str(payload.get("error") or "")) if item]
            has_usable_value = any(
                value is not None
                for value in (temperature, heart_rate, spo2, systolic_pressure, diastolic_pressure, respiratory_rate)
            )
            if payload.get("ok") is False and not has_usable_value:
                return self._unavailable_vitals("；".join(dict.fromkeys(errors)) or "体征模块读取失败。")
            return {
                "temperature_c": temperature,
                "heart_rate": heart_rate,
                "spo2": spo2,
                "systolic_pressure": systolic_pressure,
                "diastolic_pressure": diastolic_pressure,
                "respiratory_rate": respiratory_rate,
                "microcirculation": microcirculation,
                "fatigue": fatigue,
                "rr_interval": rr_interval,
                "hrv_sdnn": hrv_sdnn,
                "hrv_rmssd": hrv_rmssd,
                "sensor_body_temperature": sensor_body_temperature,
                "ambient_temperature": ambient_temperature,
                "reference_ready": bool(reference_ready),
                "source": "real",
                "finger_detected": finger_detected,
                "quality": quality,
                "message": message,
                "sample_count": self._first_present(integrated, ("sample_count",), fallback=self._first_present(vitals, ("sample_count",))),
                "partial": partial,
                "error_message": "；".join(dict.fromkeys(errors)) or None,
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
                # UI/backend use 1-23; the physical cabinet wiring has mirrored rows.
                payload["control_code"] = CABINET_CONTROL_CODE_BY_SLOT[numeric_slot]
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

    def audio_speak(self, text: str, volume: int | None = None, speed: float | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text}
        if volume is not None:
            payload["volume"] = max(0, min(int(volume), 255))
        if speed is not None:
            payload["speed"] = max(0.75, min(float(speed), 1.45))
        return self._qsm_action(settings.qsm_audio_speak_path, payload, "语音播报", timeout=settings.qsm_audio_timeout_seconds)

    def audio_beep(self, volume: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if volume is not None:
            payload["volume"] = max(0, min(int(volume), 255))
        return self._qsm_action(settings.qsm_audio_beep_path, payload, "提示音", timeout=12)

    def audio_play_base64(self, audio_base64: str, fmt: str = "wav", volume: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"audio_base64": audio_base64, "format": fmt}
        if volume is not None:
            payload["volume"] = max(0, min(int(volume), 255))
        return self._qsm_action(
            settings.qsm_audio_play_path,
            payload,
            "音频播放",
            timeout=settings.qsm_audio_timeout_seconds,
        )

    def audio_stream_start(
        self,
        *,
        port: int | None = None,
        volume: int | None = None,
        rate: int = 16000,
        channels: int = 1,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "port": int(port or settings.qsm_audio_stream_port),
            "rate": int(rate),
            "channels": int(channels),
        }
        if volume is not None:
            payload["volume"] = max(0, min(int(volume), 255))
        return self._qsm_action(settings.qsm_audio_stream_start_path, payload, "音频实时流启动")

    def audio_stream_stop(self) -> dict[str, Any]:
        return self._qsm_action(settings.qsm_audio_stream_stop_path, {}, "音频实时流停止")

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
