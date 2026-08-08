from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from datetime import datetime
from copy import deepcopy
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import real_dispense_enabled, settings
from ..schemas.qsm import QsmStatus


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


class _VitalsMeasurementCoordinator:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._in_flight = False
        self._generation = 0
        self._last_result: dict[str, Any] | None = None

    def run(
        self,
        reader: Callable[[], dict[str, Any]],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        with self._condition:
            if self._in_flight:
                generation = self._generation
                completed = self._condition.wait_for(
                    lambda: not self._in_flight and self._generation > generation,
                    timeout=timeout,
                )
                if completed and self._last_result is not None:
                    return deepcopy(self._last_result)
                return {
                    "temperature_c": None,
                    "heart_rate": None,
                    "spo2": None,
                    "source": "unavailable",
                    "error_message": "上一轮体征测量仍在进行，请稍后重试。",
                }
            self._in_flight = True

        result: dict[str, Any] | None = None
        try:
            result = reader()
            return result
        finally:
            self._finish(result)

    def start(self, reader: Callable[[], dict[str, Any]]) -> bool:
        with self._condition:
            if self._in_flight:
                return False
            self._in_flight = True

        def measure() -> None:
            result: dict[str, Any] | None = None
            try:
                result = reader()
            except Exception as exc:  # pragma: no cover - defensive hardware boundary
                result = {
                    "temperature_c": None,
                    "heart_rate": None,
                    "spo2": None,
                    "source": "unavailable",
                    "error_message": f"体征预热失败：{exc}",
                }
            finally:
                self._finish(result)

        threading.Thread(target=measure, name="qsm-vitals-prepare", daemon=True).start()
        return True

    def _finish(self, result: dict[str, Any] | None) -> None:
        with self._condition:
            self._last_result = deepcopy(result) if result is not None else None
            self._in_flight = False
            self._generation += 1
            self._condition.notify_all()


_VITALS_MEASUREMENT = _VitalsMeasurementCoordinator()
_MOCK_VITALS_SESSIONS: dict[str, dict[str, Any]] = {}


class QsmClient:
    def __init__(
        self,
        mode: str | None = None,
        base_url: str | None = None,
        vitals_base_url: str | None = None,
    ) -> None:
        self.mode = (mode or settings.qsm_mode or "mock").lower()
        self.base_url = (base_url or settings.qsm_api_base).rstrip("/")
        self.vitals_base_url = (vitals_base_url or settings.qsm_vitals_api_base).rstrip("/")

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
            return self._coordinated_full_vitals(fallback_error=str(temperature.get("error_message", "")))

        return self.read_full_vitals()

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
        return self._coordinated_full_vitals()

    def prepare_vitals(self) -> dict[str, Any]:
        if self.mode != "real":
            return {"ok": True, "mode": self.mode, "status": "ready", "started": False}
        payload, error = self._request_json(
            settings.qsm_vitals_prepare_path,
            method="POST",
            payload={},
            body_format="json",
            timeout=4,
            base_url=self.vitals_base_url,
        )
        if error:
            return {
                "ok": False,
                "mode": "real",
                "status": "unavailable",
                "started": False,
                "error_message": error,
            }
        payload.setdefault("ok", True)
        payload.setdefault("mode", "real")
        payload["started"] = bool(payload.get("hardware_started"))
        return payload

    def start_vitals_session(self, *, replace_active: bool = True) -> dict[str, Any]:
        if self.mode != "real":
            session_id = f"mock-vitals-{int(time.time() * 1000)}"
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            result = {
                "ok": True,
                "mode": "mock",
                "session_id": session_id,
                "status": "complete",
                "hardware_started": True,
                "elapsed_seconds": 0.0,
                "temperature": 36.5,
                "heart_rate": 76,
                "spo2": 98,
                "finger_detected": True,
                "sample_count": 3,
                "source": "mock",
                "started_at": now,
                "updated_at": now,
                "measured_at": now,
            }
            _MOCK_VITALS_SESSIONS[session_id] = result
            return deepcopy(result)

        payload, error = self._request_json(
            settings.qsm_vitals_session_start_path,
            method="POST",
            payload={"replace_active": replace_active},
            body_format="json",
            timeout=4,
            base_url=self.vitals_base_url,
        )
        if error:
            return self._vitals_session_error(
                "",
                "failed",
                error,
                communication_status="gateway_unreachable",
                failure_reason="transport_error",
            )
        if not payload.get("hardware_started"):
            return self._vitals_session_error(
                str(payload.get("session_id") or ""),
                "failed",
                str(payload.get("error_message") or "体征设备未确认启动。"),
                communication_status=str(
                    payload.get("communication_status") or "gateway_available"
                ),
                failure_reason=str(payload.get("failure_reason") or "hardware_start_failed"),
            )
        payload.setdefault("ok", True)
        payload.setdefault("mode", "real")
        return payload

    def get_vitals_session(self, session_id: str) -> dict[str, Any]:
        if self.mode != "real":
            return deepcopy(
                _MOCK_VITALS_SESSIONS.get(session_id)
                or self._vitals_session_error(session_id, "failed", "未找到体征测量会话。")
            )
        query = urlencode({"session_id": session_id})
        payload, error = self._request_json(
            f"{settings.qsm_vitals_session_status_path}?{query}",
            method="GET",
            timeout=3,
            base_url=self.vitals_base_url,
        )
        if error:
            return self._vitals_session_error(
                session_id,
                "failed",
                error,
                communication_status="gateway_unreachable",
                failure_reason="transport_error",
            )
        payload = self._apply_demo_spo2_fallback(payload)
        payload.setdefault("ok", payload.get("status") not in {"failed", "cancelled"})
        payload.setdefault("mode", "real")
        return payload

    @staticmethod
    def _apply_demo_spo2_fallback(payload: dict[str, Any]) -> dict[str, Any]:
        if not bool(getattr(settings, "vitals_demo_spo2_fallback", False)):
            return payload
        if str(payload.get("status") or "") != "failed":
            return payload
        if payload.get("finger_detected") is False:
            return payload
        try:
            heart_rate = float(payload.get("heart_rate") or 0)
            temperature = float(payload.get("temperature") or 0)
            spo2 = float(payload.get("spo2") or 0)
            heart_rate_frames = int(payload.get("heart_rate_frame_count") or 0)
        except (TypeError, ValueError):
            return payload
        if heart_rate <= 0 or temperature <= 0 or spo2 > 0 or heart_rate_frames < 1:
            return payload

        completed = dict(payload)
        completed.update(
            {
                "ok": True,
                "status": "complete",
                "spo2": 95 + secrets.randbelow(5),
                "spo2_source": "demo_fallback",
                "spo2_demo_fallback": True,
                "error_message": None,
                "message": "心率与额温已读取；血氧演示值已补齐。",
            }
        )
        completed.setdefault("temperature_source", "gy614_sensor")
        completed.setdefault("heart_rate_source", "uart8_sensor")
        return completed

    def cancel_vitals_session(self, session_id: str) -> dict[str, Any]:
        if self.mode != "real":
            result = _MOCK_VITALS_SESSIONS.get(session_id)
            if result is None:
                return self._vitals_session_error(session_id, "failed", "未找到体征测量会话。")
            result.update({"ok": True, "status": "cancelled"})
            return deepcopy(result)
        payload, error = self._request_json(
            settings.qsm_vitals_session_cancel_path,
            method="POST",
            payload={"session_id": session_id},
            body_format="json",
            timeout=4,
            base_url=self.vitals_base_url,
        )
        if error:
            return self._vitals_session_error(
                session_id,
                "failed",
                error,
                communication_status="gateway_unreachable",
                failure_reason="transport_error",
            )
        payload.setdefault("ok", True)
        payload.setdefault("mode", "real")
        return payload

    def _vitals_session_error(
        self,
        session_id: str,
        status: str,
        message: str,
        *,
        communication_status: str | None = None,
        failure_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "mode": self.mode,
            "session_id": session_id,
            "status": status,
            "hardware_started": False,
            "communication_status": communication_status,
            "failure_reason": failure_reason,
            "error_message": message,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    def _coordinated_full_vitals(self, fallback_error: str = "") -> dict[str, Any]:
        timeout = (
            settings.qsm_vitals_timeout_seconds * settings.qsm_vitals_retry_attempts
            + settings.qsm_vitals_retry_delay_seconds
            + 5
        )
        if fallback_error:
            return _VITALS_MEASUREMENT.run(
                lambda: self._read_full_vitals(fallback_error=fallback_error),
                timeout=timeout,
            )
        return _VITALS_MEASUREMENT.run(self._read_full_vitals, timeout=timeout)

    def _read_full_vitals(self, fallback_error: str = "") -> dict[str, Any]:
        last_error = ""
        for path, partial in (
            (settings.qsm_vitals_all_path, False),
            (settings.qsm_vitals_path, False),
            (settings.qsm_temp_path, True),
        ):
            for method in ("POST", "GET"):
                attempts = (
                    settings.qsm_vitals_retry_attempts
                    if path == settings.qsm_vitals_all_path and method == "POST"
                    else 1
                )
                for attempt in range(attempts):
                    payload, error = self._request_json(
                        path,
                        method=method,
                        body_format="auto",
                        timeout=settings.qsm_vitals_timeout_seconds,
                    )
                    if error:
                        last_error = error
                        break
                    parsed = self._parse_vitals(payload, partial=partial)
                    if self._core_vitals_complete(parsed) or attempt == attempts - 1:
                        return parsed
                    time.sleep(settings.qsm_vitals_retry_delay_seconds)
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
            temperature_source = self._first_present(gy614, ("temperature_source",))
            if temperature_source is None:
                temperature_source = self._first_present(temperature_payload, ("temperature_source",))
            if temperature_source is None:
                temperature_source = self._first_present(
                    vitals,
                    ("temperature_source",),
                    fallback=self._first_present(payload, ("temperature_source",)),
                )
            heart_rate_source = self._first_present(
                integrated,
                ("heart_rate_source",),
                fallback=self._first_present(
                    vitals,
                    ("heart_rate_source",),
                    fallback=self._first_present(payload, ("heart_rate_source",)),
                ),
            )
            spo2_source = self._first_present(
                integrated,
                ("spo2_source",),
                fallback=self._first_present(
                    vitals,
                    ("spo2_source",),
                    fallback=self._first_present(payload, ("spo2_source",)),
                ),
            )
            spo2_demo_fallback = self._first_present(
                integrated,
                ("spo2_demo_fallback",),
                fallback=self._first_present(
                    vitals,
                    ("spo2_demo_fallback",),
                    fallback=self._first_present(payload, ("spo2_demo_fallback",), fallback=False),
                ),
            )
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
            aggregate_source = "real"
            recognized_sources = {
                "real",
                "demo",
                "mock",
                "demo_fallback",
                "history_fallback",
                "historical_fallback",
                "unavailable",
                "fallback",
            }
            for candidate in (payload.get("source"), vitals.get("source"), payload.get("mode")):
                if str(candidate or "").strip().lower() in recognized_sources:
                    aggregate_source = str(candidate)
                    break
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
                "temperature_source": temperature_source,
                "heart_rate_source": heart_rate_source,
                "spo2_source": spo2_source,
                "spo2_demo_fallback": bool(spo2_demo_fallback),
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
                "source": aggregate_source,
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
        from .qsm_camera_service import QsmCameraService

        return QsmCameraService(self.base_url).capture()

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

    def audio_status(self) -> dict[str, Any]:
        if self.mode != "real":
            return {"ok": False, "mode": self.mode, "error_message": "音频状态需要 QSM real 模式。"}
        payload, error = self._request_json(
            settings.qsm_audio_status_path,
            method="GET",
            timeout=settings.qsm_timeout_seconds,
        )
        if error:
            return {"ok": False, "mode": "real", "qsm_mode": "real", "error_message": error}
        payload.setdefault("ok", True)
        payload.setdefault("qsm_mode", "real")
        return payload

    def audio_speak(
        self,
        text: str,
        volume: int | None = None,
        speed: float | None = None,
        tts_mode: str = "auto",
    ) -> dict[str, Any]:
        normalized_mode = (tts_mode or "auto").strip().lower()
        payload: dict[str, Any] = {"text": text}
        if volume is not None:
            payload["volume"] = max(0, min(int(volume), 255))
        if speed is not None:
            payload["speed"] = max(0.75, min(float(speed), 1.45))
        payload["tts_mode"] = (
            normalized_mode
            if normalized_mode in {"auto", "cloud", "offline"}
            else "auto"
        )
        return self._qsm_action(
            settings.qsm_audio_speak_path,
            payload,
            "语音播报",
            timeout=settings.qsm_audio_timeout_seconds,
        )

    def audio_beep(self, volume: int | None = None) -> dict[str, Any]:
        if volume is not None and int(volume) <= 0:
            return {
                "ok": True,
                "muted": True,
                "qsm_mode": self.mode,
                "detail": "当前为静音，未向外设发送提示音。",
            }
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
        data.setdefault("mode", "real")
        data["qsm_mode"] = "real"
        return data

    def _request_json(
        self,
        path: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        body_format: str = "form",
        timeout: float | None = None,
        base_url: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        formats = ["none"] if method == "GET" else ([body_format] if body_format in {"form", "json"} else ["form", "json"])
        errors: list[str] = []
        for item in formats:
            result, error = self._single_request_json(
                path,
                method=method,
                payload=payload,
                body_format=item,
                timeout=timeout,
                base_url=base_url,
            )
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
        base_url: str | None = None,
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
            request = Request(f"{(base_url or self.base_url).rstrip('/')}{path}", data=data, headers=headers, method=method)
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

    @staticmethod
    def _core_vitals_complete(vitals: dict[str, Any]) -> bool:
        return all(vitals.get(field) is not None for field in ("temperature_c", "heart_rate", "spo2"))

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
