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
                  status, source, sensor_model, error_message, measured_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                       status, source, sensor_model, error_message, measured_at
                FROM vitals_records
                ORDER BY measured_at DESC
                LIMIT 1
                """
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
                       status, source, sensor_model, error_message, measured_at
                FROM vitals_records
                WHERE status IN ('available', 'partial')
                  AND (temperature IS NOT NULL OR heart_rate IS NOT NULL OR spo2 IS NOT NULL)
                ORDER BY measured_at DESC
                LIMIT 1
                """
            ).fetchone()
        return VitalsRecord(**dict(row)) if row else None

    def latest_complete_core(self) -> VitalsRecord | None:
        """Return the latest record containing all three core measurements."""
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, temperature, heart_rate, spo2,
                       systolic_pressure, diastolic_pressure, respiratory_rate,
                       microcirculation, fatigue, rr_interval, hrv_sdnn, hrv_rmssd,
                       body_temperature, ambient_temperature,
                       status, source, sensor_model, error_message, measured_at
                FROM vitals_records
                WHERE status IN ('available', 'partial')
                  AND temperature IS NOT NULL AND temperature > 0
                  AND heart_rate IS NOT NULL AND heart_rate > 0
                  AND spo2 IS NOT NULL AND spo2 > 0
                ORDER BY measured_at DESC
                LIMIT 1
                """
            ).fetchone()
        return VitalsRecord(**dict(row)) if row else None

    def count(self) -> int:
        db.init_db()
        with db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS count FROM vitals_records").fetchone()["count"])
