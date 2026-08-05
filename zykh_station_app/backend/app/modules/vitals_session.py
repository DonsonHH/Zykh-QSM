from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from ..db import now_text
from ..repositories.device_action_repository import DeviceActionRecord, DeviceActionRepository
from ..repositories.sync_repository import SyncRepository
from ..repositories.vitals_repository import VitalsRecord, VitalsRepository
from ..schemas.qsm import VitalsSessionResponse
from ..services.qsm_client import QsmClient


class VitalsSessionGateway(Protocol):
    """Internal seam implemented by the production QSM and test adapters."""

    def prepare_vitals(self) -> dict[str, object]: ...

    def start_vitals_session(self, *, replace_active: bool = True) -> dict[str, object]: ...

    def get_vitals_session(self, session_id: str) -> dict[str, object]: ...

    def cancel_vitals_session(self, session_id: str) -> dict[str, object]: ...


class VitalsSessionNotFound(LookupError):
    pass


class VitalsSessionModule:
    """Own host-side vitals session truth, history, and persistence policy."""

    def __init__(self, gateway: VitalsSessionGateway | None = None) -> None:
        self._gateway = gateway or QsmClient()

    def prepare(self) -> dict[str, object]:
        return self._gateway.prepare_vitals()

    def start(self, *, replace_active: bool = True) -> VitalsSessionResponse:
        return VitalsSessionResponse(
            **self._gateway.start_vitals_session(replace_active=replace_active)
        )

    def get(self, session_id: str) -> VitalsSessionResponse:
        result = self._gateway.get_vitals_session(session_id)
        if not result.get("session_id"):
            raise VitalsSessionNotFound(session_id)
        response = self._attach_previous_reference(VitalsSessionResponse(**result))
        self._persist_completed_measurement(response)
        return response

    def cancel(self, session_id: str) -> VitalsSessionResponse:
        return VitalsSessionResponse(**self._gateway.cancel_vitals_session(session_id))

    @staticmethod
    def _persist_completed_measurement(response: VitalsSessionResponse) -> None:
        if response.status != "complete":
            return
        if response.historical_fallback:
            return
        if response.spo2_demo_fallback or response.spo2_source == "demo_fallback":
            return
        if response.heart_rate is None or response.spo2 is None or response.temperature is None:
            return

        measured_at = response.measured_at or response.updated_at or now_text()
        record = VitalsRecord(
            id=f"vitals-session-{response.session_id}",
            temperature=response.temperature,
            heart_rate=response.heart_rate,
            spo2=response.spo2,
            systolic_pressure=response.systolic_pressure,
            diastolic_pressure=response.diastolic_pressure,
            respiratory_rate=response.respiratory_rate,
            microcirculation=response.microcirculation,
            fatigue=response.fatigue,
            rr_interval=response.rr_interval,
            hrv_sdnn=response.hrv_sdnn,
            hrv_rmssd=response.hrv_rmssd,
            body_temperature=response.body_temperature,
            ambient_temperature=response.ambient_temperature,
            status="available",
            source=response.source or response.mode,
            sensor_model=response.source or "",
            error_message="",
            measured_at=measured_at,
        )
        if not VitalsRepository().append_once(record):
            return
        SyncRepository().mark_pending()
        temperature_label = (
            "指温参考"
            if response.temperature_source == "uart8_fingertip_reference"
            else "额温"
        )
        DeviceActionRepository().append(
            DeviceActionRecord(
                id=f"device-{uuid4().hex[:12]}",
                created_at=measured_at,
                type="体征读取",
                title=f"心率 {response.heart_rate}次/分，血氧 {response.spo2}%",
                description=(
                    f"{temperature_label} {response.temperature:.1f}℃，体征测量已完成。"
                ),
                status="已记录",
            )
        )

    @staticmethod
    def _attach_previous_reference(response: VitalsSessionResponse) -> VitalsSessionResponse:
        if response.status != "failed" or not response.hardware_started:
            return response
        if response.heart_rate is not None or response.spo2 is not None:
            return response

        previous = VitalsRepository().latest_complete_core()
        if previous is None:
            return response

        return response.model_copy(
            update={
                "message": "本次手指信号未稳定；已附上一次完整测量供参考。",
                "historical_fallback": True,
                "historical_temperature": previous.temperature,
                "historical_heart_rate": previous.heart_rate,
                "historical_spo2": previous.spo2,
                "historical_source": previous.source,
                "historical_measured_at": previous.measured_at,
            }
        )
