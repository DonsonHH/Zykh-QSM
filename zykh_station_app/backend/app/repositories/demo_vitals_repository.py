from __future__ import annotations

from pydantic import BaseModel

from .. import db


class DemoVitalsRecord(BaseModel):
    id: str
    session_id: str
    temperature: float
    heart_rate: int
    spo2: int
    measured_at: str
    source_route: str = "HOME"
    inquiry_session_id: str = ""
    service_user_id: str = ""
    persona_generation: str = ""
    temperature_source: str = ""
    heart_rate_source: str = ""
    spo2_source: str = ""
    demo_fallback_reason: str = ""


class DemoVitalsRepository:
    """Persist presentation-only vitals outside clinical history and sync."""

    def append_once(self, record: DemoVitalsRecord) -> bool:
        db.init_db()
        with db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO demo_vitals_records(
                  id, session_id, temperature, heart_rate, spo2, measured_at,
                  source_route, inquiry_session_id, service_user_id, persona_generation,
                  temperature_source, heart_rate_source, spo2_source, demo_fallback_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.session_id,
                    record.temperature,
                    record.heart_rate,
                    record.spo2,
                    record.measured_at,
                    record.source_route,
                    record.inquiry_session_id,
                    record.service_user_id,
                    record.persona_generation,
                    record.temperature_source,
                    record.heart_rate_source,
                    record.spo2_source,
                    record.demo_fallback_reason,
                ),
            )
        return cursor.rowcount > 0

    def get_by_session(self, session_id: str) -> DemoVitalsRecord | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM demo_vitals_records WHERE session_id=? LIMIT 1",
                (str(session_id or "").strip(),),
            ).fetchone()
        return DemoVitalsRecord(**dict(row)) if row else None

    def count(self) -> int:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM demo_vitals_records").fetchone()
        return int(row["count"])
