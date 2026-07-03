from __future__ import annotations

from pydantic import BaseModel

from .. import db


class VitalsRecord(BaseModel):
    id: str
    temperature: float | None = None
    heart_rate: int | None = None
    spo2: int | None = None
    status: str
    source: str
    error_message: str = ""
    measured_at: str


class VitalsRepository:
    def append(self, record: VitalsRecord) -> VitalsRecord:
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO vitals_records(
                  id, temperature, heart_rate, spo2, status, source, error_message, measured_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.temperature,
                    record.heart_rate,
                    record.spo2,
                    record.status,
                    record.source,
                    record.error_message,
                    record.measured_at,
                ),
            )
        return record

    def latest(self) -> VitalsRecord | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, temperature, heart_rate, spo2, status, source, error_message, measured_at
                FROM vitals_records
                ORDER BY measured_at DESC
                LIMIT 1
                """
            ).fetchone()
        return VitalsRecord(**dict(row)) if row else None

    def count(self) -> int:
        db.init_db()
        with db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS count FROM vitals_records").fetchone()["count"])
