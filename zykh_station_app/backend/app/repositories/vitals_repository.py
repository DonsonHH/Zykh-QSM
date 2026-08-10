from __future__ import annotations

from pydantic import BaseModel

from .. import db


class VitalsRecord(BaseModel):
    id: str
    temperature: float | None = None
    heart_rate: int | None = None
    spo2: int | None = None
    systolic_pressure: int | None = None
    diastolic_pressure: int | None = None
    respiratory_rate: int | None = None
    microcirculation: int | None = None
    fatigue: int | None = None
    rr_interval: int | None = None
    hrv_sdnn: int | None = None
    hrv_rmssd: int | None = None
    body_temperature: float | None = None
    ambient_temperature: float | None = None
    status: str
    source: str
    sensor_model: str = ""
    error_message: str = ""
    measured_at: str
    source_route: str = "HOME"
    inquiry_session_id: str = ""
    attribution_source: str = "UNREGISTERED"
    service_user_id: str = ""
    service_user_name_snapshot: str = ""
    persona_generation: str = ""
    temperature_source: str = ""
    heart_rate_source: str = ""
    spo2_source: str = ""


class VitalsRepository:
    def append(self, record: VitalsRecord) -> VitalsRecord:
        self._insert(record)
        return record

    def append_once(self, record: VitalsRecord) -> bool:
        return self._insert(record, ignore_conflict=True)

    @staticmethod
    def _insert(record: VitalsRecord, *, ignore_conflict: bool = False) -> bool:
        db.init_db()
        with db.connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT {"OR IGNORE " if ignore_conflict else ""}INTO vitals_records(
                  id, temperature, heart_rate, spo2,
                  systolic_pressure, diastolic_pressure, respiratory_rate,
                  microcirculation, fatigue, rr_interval, hrv_sdnn, hrv_rmssd,
                  body_temperature, ambient_temperature,
                  status, source, sensor_model, error_message, measured_at,
                  source_route, inquiry_session_id, attribution_source,
                  service_user_id, service_user_name_snapshot, persona_generation,
                  temperature_source, heart_rate_source, spo2_source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.temperature,
                    record.heart_rate,
                    record.spo2,
                    record.systolic_pressure,
                    record.diastolic_pressure,
                    record.respiratory_rate,
                    record.microcirculation,
                    record.fatigue,
                    record.rr_interval,
                    record.hrv_sdnn,
                    record.hrv_rmssd,
                    record.body_temperature,
                    record.ambient_temperature,
                    record.status,
                    record.source,
                    record.sensor_model,
                    record.error_message,
                    record.measured_at,
                    record.source_route,
                    record.inquiry_session_id,
                    record.attribution_source,
                    record.service_user_id,
                    record.service_user_name_snapshot,
                    record.persona_generation,
                    record.temperature_source,
                    record.heart_rate_source,
                    record.spo2_source,
                ),
            )
        return cursor.rowcount > 0

    def latest(self) -> VitalsRecord | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, temperature, heart_rate, spo2,
                       systolic_pressure, diastolic_pressure, respiratory_rate,
                       microcirculation, fatigue, rr_interval, hrv_sdnn, hrv_rmssd,
                       body_temperature, ambient_temperature,
                       status, source, sensor_model, error_message, measured_at,
                       source_route, inquiry_session_id, attribution_source,
                       service_user_id, service_user_name_snapshot, persona_generation
                FROM vitals_records
                ORDER BY measured_at DESC
                LIMIT 1
                """
            ).fetchone()
        return VitalsRecord(**dict(row)) if row else None

    def completed_inquiry_measurement(
        self,
        *,
        vitals_session_id: str,
        inquiry_session_id: str,
        service_user_id: str,
        persona_generation: str,
    ) -> VitalsRecord | None:
        """Load one server-recorded live measurement bound to the current persona."""
        measurement_id = f"vitals-session-{str(vitals_session_id or '').strip()}"
        inquiry_id = str(inquiry_session_id or "").strip()
        user_id = str(service_user_id or "").strip()
        generation = str(persona_generation or "").strip()
        if not all((measurement_id != "vitals-session-", inquiry_id, user_id, generation)):
            return None
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT r.*
                FROM vitals_records AS r
                JOIN service_users AS u ON u.id=r.service_user_id
                WHERE r.id=? AND r.status='available'
                  AND r.source_route='INQUIRY'
                  AND r.attribution_source='INQUIRY_SESSION'
                  AND r.inquiry_session_id=?
                  AND r.service_user_id=?
                  AND r.persona_generation=?
                  AND r.temperature_source='gy614_sensor'
                  AND r.heart_rate_source='uart8_sensor'
                  AND r.spo2_source='uart8_sensor'
                  AND r.temperature IS NOT NULL AND r.temperature > 0
                  AND r.heart_rate IS NOT NULL AND r.heart_rate > 0
                  AND r.spo2 IS NOT NULL AND r.spo2 > 0
                  AND u.archived=0 AND u.persona_generation=?
                LIMIT 1
                """,
                (measurement_id, inquiry_id, user_id, generation, generation),
            ).fetchone()
        return VitalsRecord(**dict(row)) if row else None

    def latest_for_context(self) -> VitalsRecord | None:
        """Return the latest usable measurement without letting failed attempts hide it."""
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, temperature, heart_rate, spo2,
                       systolic_pressure, diastolic_pressure, respiratory_rate,
                       microcirculation, fatigue, rr_interval, hrv_sdnn, hrv_rmssd,
                       body_temperature, ambient_temperature,
                       status, source, sensor_model, error_message, measured_at,
                       source_route, inquiry_session_id, attribution_source,
                       service_user_id, service_user_name_snapshot, persona_generation
                FROM vitals_records
                WHERE status IN ('available', 'partial')
                  AND (temperature IS NOT NULL OR heart_rate IS NOT NULL OR spo2 IS NOT NULL)
                ORDER BY measured_at DESC
                LIMIT 1
                """
            ).fetchone()
        return VitalsRecord(**dict(row)) if row else None

    def latest_complete_core(
        self,
        *,
        source_route: str = "HOME",
        service_user_id: str = "",
        persona_generation: str = "",
    ) -> VitalsRecord | None:
        """Return the latest complete measurement for the same ownership context."""
        route = str(source_route or "").strip().upper()
        if route == "HOME":
            ownership_clause = "source_route='HOME' AND attribution_source='UNREGISTERED'"
            ownership_params: tuple[str, ...] = ()
        elif route == "INQUIRY":
            user_id = str(service_user_id or "").strip()
            generation = str(persona_generation or "").strip()
            if not user_id or not generation:
                return None
            ownership_clause = (
                "source_route='INQUIRY' AND attribution_source='INQUIRY_SESSION' "
                "AND service_user_id=? AND persona_generation=?"
            )
            ownership_params = (user_id, generation)
        else:
            return None
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                f"""
                SELECT id, temperature, heart_rate, spo2,
                       systolic_pressure, diastolic_pressure, respiratory_rate,
                       microcirculation, fatigue, rr_interval, hrv_sdnn, hrv_rmssd,
                       body_temperature, ambient_temperature,
                       status, source, sensor_model, error_message, measured_at,
                       source_route, inquiry_session_id, attribution_source,
                       service_user_id, service_user_name_snapshot, persona_generation
                FROM vitals_records
                WHERE status IN ('available', 'partial')
                  AND {ownership_clause}
                  AND temperature IS NOT NULL AND temperature > 0
                  AND heart_rate IS NOT NULL AND heart_rate > 0
                  AND spo2 IS NOT NULL AND spo2 > 0
                  AND source NOT LIKE '%SpO2-demo%'
                  AND sensor_model NOT LIKE '%SpO2-demo%'
                ORDER BY measured_at DESC
                LIMIT 1
                """,
                ownership_params,
            ).fetchone()
        return VitalsRecord(**dict(row)) if row else None

    def count(self) -> int:
        db.init_db()
        with db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS count FROM vitals_records").fetchone()["count"])
