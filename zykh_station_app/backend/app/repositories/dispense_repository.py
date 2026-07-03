from __future__ import annotations

from .. import db
from ..schemas.dispense import DispenseRecord


class DispenseRepository:
    def list_records(self) -> list[DispenseRecord]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, medicine_id, medicine_name, slot, hardware_slot, quantity,
                       unit, reason, dry_run, message, qsm_ok, qsm_detail, created_at
                FROM dispense_records
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [
            DispenseRecord(
                id=row["id"],
                medicine_id=row["medicine_id"],
                medicine_name=row["medicine_name"],
                slot=row["slot"],
                hardware_slot=int(row["hardware_slot"]),
                quantity=int(row["quantity"]),
                unit=row["unit"],
                reason=row["reason"],
                dry_run=bool(row["dry_run"]),
                message=row["message"],
                qsm_ok=bool(row["qsm_ok"]),
                qsm_detail=row["qsm_detail"] or "",
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def append(self, record: DispenseRecord) -> DispenseRecord:
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO dispense_records(
                  id, medicine_id, medicine_name, slot, hardware_slot, quantity,
                  unit, reason, dry_run, message, qsm_ok, qsm_detail, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.medicine_id,
                    record.medicine_name,
                    record.slot,
                    record.hardware_slot,
                    record.quantity,
                    record.unit,
                    record.reason,
                    1 if record.dry_run else 0,
                    record.message,
                    1 if record.qsm_ok else 0,
                    record.qsm_detail,
                    record.created_at,
                ),
            )
        return record
