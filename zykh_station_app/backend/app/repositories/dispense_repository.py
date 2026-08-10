from __future__ import annotations

from .. import db
from ..schemas.dispense import DispenseRecord
from .medicine_repository import MedicineRepository


class DispenseRepository:
    def successful_counts_by_medicine(self) -> dict[str, int]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT medicine_id, COUNT(*) AS dispense_count
                FROM dispense_records
                WHERE dry_run=0 AND qsm_ok=1
                GROUP BY medicine_id
                """
            ).fetchall()
        return {str(row["medicine_id"]): int(row["dispense_count"]) for row in rows}

    def list_records(self) -> list[DispenseRecord]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, medicine_id, medicine_name, slot, hardware_slot, quantity,
                       unit, reason, dry_run, message, qsm_ok, qsm_detail,
                       target_user_id, target_user_name, verification_method,
                       verification_score, target_user_type, today_plan_id,
                       persona_generation, created_at
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
                target_user_id=row["target_user_id"] or "",
                persona_generation=row["persona_generation"] or "",
                target_user_name=row["target_user_name"] or "家庭成员",
                verification_method=row["verification_method"] or "manual",
                verification_score=float(row["verification_score"]) if row["verification_score"] is not None else None,
                target_user_type=row["target_user_type"] or "registered",
                today_plan_id=row["today_plan_id"] or "",
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def append(self, record: DispenseRecord) -> DispenseRecord:
        db.init_db()
        with db.connect() as conn:
            self._insert(conn, record)
        return record

    def append_with_inventory_observation(
        self,
        record: DispenseRecord,
        *,
        expected_stock: int,
        expected_inventory_revision: int,
    ) -> tuple[DispenseRecord, bool]:
        """Persist a real success and bind its pending inventory observation atomically."""
        db.init_db()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._insert(conn, record)
            pending = MedicineRepository._mark_inventory_observation_pending_in_connection(
                conn,
                record.medicine_id,
                record.id,
                expected_stock=expected_stock,
                expected_inventory_revision=expected_inventory_revision,
            )
        return record, pending

    @staticmethod
    def _insert(conn, record: DispenseRecord) -> None:
        conn.execute(
            """
            INSERT INTO dispense_records(
              id, medicine_id, medicine_name, slot, hardware_slot, quantity,
              unit, reason, dry_run, message, qsm_ok, qsm_detail,
              target_user_id, target_user_name, verification_method,
              verification_score, target_user_type, today_plan_id,
              persona_generation, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                record.target_user_id,
                record.target_user_name,
                record.verification_method,
                record.verification_score,
                record.target_user_type,
                record.today_plan_id,
                record.persona_generation,
                record.created_at,
            ),
        )
