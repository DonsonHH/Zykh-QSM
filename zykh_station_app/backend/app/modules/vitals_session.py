from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from .. import db
from ..db import now_text
from ..repositories.demo_vitals_repository import DemoVitalsRecord, DemoVitalsRepository
from ..repositories.inquiry_repository import InquiryRepository
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

    def start(
        self,
        *,
        replace_active: bool = True,
        source_route: str = "HOME",
        inquiry_session_id: str = "",
    ) -> VitalsSessionResponse:
        context = self._resolve_context(source_route, inquiry_session_id)
        response = VitalsSessionResponse(
            **self._gateway.start_vitals_session(replace_active=replace_active)
        )
        if not response.session_id:
            raise VitalsSessionNotFound("gateway did not return a session id")
        if not response.hardware_started:
            return response.model_copy(
                update=self._context_for_session(response.session_id)
            )
        self._store_context(response.session_id, context)
        return response.model_copy(update=context)

    def get(self, session_id: str) -> VitalsSessionResponse:
        result = self._gateway.get_vitals_session(session_id)
        if not result.get("session_id"):
            raise VitalsSessionNotFound(session_id)
        response = VitalsSessionResponse(**result).model_copy(
            update=self._context_for_session(session_id)
        )
        response = self._attach_previous_reference(response)
        self._persist_completed_measurement(response)
        return response

    def cancel(self, session_id: str) -> VitalsSessionResponse:
        return VitalsSessionResponse(
            **self._gateway.cancel_vitals_session(session_id)
        ).model_copy(update=self._context_for_session(session_id))

    @staticmethod
    def _resolve_context(source_route: str, inquiry_session_id: str) -> dict[str, str]:
        route = str(source_route or "HOME").strip().upper()
        inquiry_id = str(inquiry_session_id or "").strip()
        if route == "HOME":
            if inquiry_id:
                raise ValueError("首页体征测量不能携带问询会话。")
            return {
                "source_route": "HOME",
                "inquiry_session_id": "",
                "attribution_source": "UNREGISTERED",
                "service_user_id": "",
                "service_user_name_snapshot": "",
                "persona_generation": "",
            }
        if route != "INQUIRY" or not inquiry_id:
            raise ValueError("问询体征测量缺少有效问询会话。")
        session = InquiryRepository().get_session(inquiry_id)
        if session is None:
            raise ValueError("问询体征测量缺少有效问询会话。")
        if session.stage != "vitals" or session.next_action != "measure_vitals":
            raise ValueError("问询会话当前阶段不允许启动体征测量。")
        if not session.user_id.strip():
            return {
                "source_route": "INQUIRY",
                "inquiry_session_id": inquiry_id,
                "attribution_source": "INQUIRY_SESSION",
                "service_user_id": "",
                "service_user_name_snapshot": session.user_name,
                "persona_generation": "",
            }
        session_generation = session.persona_generation.strip()
        if not session_generation:
            raise ValueError("问询会话缺少人物代次快照，不能启动体征测量。")
        db.init_db()
        with db.connect() as conn:
            person = conn.execute(
                """
                SELECT id, persona_generation FROM service_users
                WHERE id=? AND archived=0
                """,
                (session.user_id,),
            ).fetchone()
        if person is None:
            raise ValueError("问询人物资料已归档或缺少代次，不能启动体征测量。")
        current_generation = str(person["persona_generation"] or "").strip()
        if not current_generation or current_generation != session_generation:
            raise ValueError("问询人物代次已变化，不能沿用旧会话启动体征测量。")
        return {
            "source_route": "INQUIRY",
            "inquiry_session_id": inquiry_id,
            "attribution_source": "INQUIRY_SESSION",
            "service_user_id": str(person["id"]),
            "service_user_name_snapshot": session.user_name,
            "persona_generation": session_generation,
        }

    @staticmethod
    def _store_context(session_id: str, context: dict[str, str]) -> None:
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO vitals_session_contexts(
                  session_id, source_route, inquiry_session_id, attribution_source,
                  service_user_id, service_user_name_snapshot, persona_generation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  source_route=excluded.source_route,
                  inquiry_session_id=excluded.inquiry_session_id,
                  attribution_source=excluded.attribution_source,
                  service_user_id=excluded.service_user_id,
                  service_user_name_snapshot=excluded.service_user_name_snapshot,
                  persona_generation=excluded.persona_generation
                """,
                (
                    session_id,
                    context["source_route"],
                    context["inquiry_session_id"],
                    context["attribution_source"],
                    context["service_user_id"],
                    context["service_user_name_snapshot"],
                    context["persona_generation"],
                    now_text(),
                ),
            )

    @staticmethod
    def _context_for_session(session_id: str) -> dict[str, str]:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT source_route, inquiry_session_id, attribution_source,
                       service_user_id, service_user_name_snapshot, persona_generation
                FROM vitals_session_contexts WHERE session_id=?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return {
                "source_route": "HOME",
                "inquiry_session_id": "",
                "attribution_source": "UNREGISTERED",
                "service_user_id": "",
                "service_user_name_snapshot": "",
                "persona_generation": "",
            }
        return dict(row)

    @staticmethod
    def _persist_completed_measurement(response: VitalsSessionResponse) -> None:
        if response.status != "complete":
            return
        if response.historical_fallback:
            return
        if VitalsSessionModule._has_demo_provenance(response):
            VitalsSessionModule._persist_demo_measurement(response)
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
            source_route=response.source_route,
            inquiry_session_id=response.inquiry_session_id,
            attribution_source=response.attribution_source,
            service_user_id=response.service_user_id,
            service_user_name_snapshot=response.service_user_name_snapshot,
            persona_generation=response.persona_generation,
            temperature_source=response.temperature_source or "",
            heart_rate_source=response.heart_rate_source or "",
            spo2_source=response.spo2_source or "",
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
    def _has_demo_provenance(response: VitalsSessionResponse) -> bool:
        return bool(
            response.spo2_demo_fallback
            or response.heart_rate_source == "demo_fallback"
            or response.spo2_source == "demo_fallback"
        )

    @staticmethod
    def _persist_demo_measurement(response: VitalsSessionResponse) -> None:
        if response.heart_rate is None or response.spo2 is None or response.temperature is None:
            return
        measured_at = response.measured_at or response.updated_at or now_text()
        DemoVitalsRepository().append_once(
            DemoVitalsRecord(
                id=f"demo-vitals-session-{response.session_id}",
                session_id=response.session_id,
                temperature=response.temperature,
                heart_rate=response.heart_rate,
                spo2=response.spo2,
                measured_at=measured_at,
                source_route=response.source_route,
                inquiry_session_id=response.inquiry_session_id,
                service_user_id=response.service_user_id,
                persona_generation=response.persona_generation,
                temperature_source=response.temperature_source or "",
                heart_rate_source=response.heart_rate_source or "",
                spo2_source=response.spo2_source or "",
                demo_fallback_reason=(
                    response.demo_fallback_reason or response.failure_reason or ""
                ),
            )
        )

    @staticmethod
    def _attach_previous_reference(response: VitalsSessionResponse) -> VitalsSessionResponse:
        if response.status != "failed" or not response.hardware_started:
            return response
        if response.heart_rate is not None or response.spo2 is not None:
            return response

        previous = VitalsRepository().latest_complete_core(
            source_route=response.source_route,
            service_user_id=response.service_user_id,
            persona_generation=response.persona_generation,
        )
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
