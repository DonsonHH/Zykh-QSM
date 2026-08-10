from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3
import time

from .. import db
from ..schemas.manual_medication_access import (
    ManualDispenseExecutionCommand,
    ManualMedicationAssessment,
    ManualMedicationOutcome,
)
from .medicine_repository import MedicineRepository


class ManualAccessIdempotencyConflict(ValueError):
    pass


class ManualExecutionPreconditionError(ValueError):
    pass


@dataclass(frozen=True)
class ManualMedicationPersonSnapshot:
    service_user_id: str
    name: str
    legacy_allergies: str
    persona_generation: str
    safety_profile_revision: int
    medical_conditions: tuple[dict[str, object], ...]
    current_medications: tuple[dict[str, object], ...]
    allergy_facts: tuple[dict[str, object], ...]
    archived: bool

    def safety_fingerprint(self) -> str:
        payload = {
            "service_user_id": self.service_user_id,
            "legacy_allergies": self.legacy_allergies,
            "persona_generation": self.persona_generation,
            "safety_profile_revision": self.safety_profile_revision,
            "medical_conditions": self.medical_conditions,
            "current_medications": self.current_medications,
            "allergy_facts": self.allergy_facts,
            "archived": self.archived,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SafetyCheckSnapshot:
    request_id: str
    service_user_id: str
    service_user_name: str
    persona_generation: str
    safety_profile_revision: int
    person_safety_fingerprint: str
    verification_method: str
    verification_assertion_id: str
    medicine_id: str
    medicine_name: str
    slot: str
    hardware_slot: int
    stock: int
    review_fingerprint: str
    ruleset_version: str


@dataclass(frozen=True)
class StoredSafetyCheck:
    check_id: str
    service_user_id: str
    service_user_name: str
    persona_generation: str
    safety_profile_revision: int
    person_safety_fingerprint: str
    verification_method: str
    verification_assertion_id: str
    medicine_id: str
    medicine_name: str
    slot: str
    hardware_slot: int
    stock: int
    review_fingerprint: str
    check_status: str
    expires_at: str
    consumed_at: str
    dispense_status: str


class ManualMedicationAccessRepository:
    """SQLite adapter for immutable safety checks and their append-only outbox event."""

    _CONFIRM_REPLAY_WAIT_SECONDS = 10.0
    _CONFIRM_REPLAY_POLL_SECONDS = 0.02

    def get_person(self, service_user_id: str) -> ManualMedicationPersonSnapshot | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, allergies, persona_generation, safety_profile_revision,
                       medical_conditions_json, current_medications_json,
                       allergy_facts_json, archived
                FROM service_users WHERE id=?
                """,
                (service_user_id,),
            ).fetchone()
        if row is None:
            return None
        return self._person_from_row(row)

    def reserve_checked_execution(
        self,
        command: ManualDispenseExecutionCommand,
    ) -> None:
        """Atomically revalidate every manual grant input before cabinet access.

        The fixed cabinet stock value is an availability flag, not a decrementing
        package count. One-time execution ownership is persisted by begin_confirm;
        this final recheck must not turn an available medicine into zero.
        """
        if int(command.quantity) < 1:
            raise ManualExecutionPreconditionError("取药数量无效，本次柜门未打开。")
        db.init_db()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            checked_at = db.now_text()
            assertion = conn.execute(
                """
                SELECT assertion_id FROM identity_assertions
                WHERE assertion_id=? AND service_user_id=?
                  AND verification_method=? AND expires_at>?
                """,
                (
                    command.verification_assertion_id,
                    command.service_user_id,
                    command.verification_method,
                    checked_at,
                ),
            ).fetchone()
            if assertion is None:
                raise ManualExecutionPreconditionError(
                    "身份确认已过期，请重新确认身份并核查。"
                )
            person_row = conn.execute(
                """
                SELECT id, name, allergies, persona_generation,
                       safety_profile_revision, medical_conditions_json,
                       current_medications_json, allergy_facts_json, archived
                FROM service_users WHERE id=?
                """,
                (command.service_user_id,),
            ).fetchone()
            if person_row is None:
                raise ManualExecutionPreconditionError(
                    "人物资料已经更新，请重新确认身份并核查。"
                )
            person = self._person_from_row(person_row)
            if (
                person.archived
                or person.persona_generation != command.expected_persona_generation
                or person.safety_profile_revision
                != command.expected_safety_profile_revision
                or person.safety_fingerprint()
                != command.expected_person_safety_fingerprint
            ):
                raise ManualExecutionPreconditionError(
                    "人物资料已经更新，请重新确认身份并核查。"
                )
            medicine_row = conn.execute(
                "SELECT * FROM medicines WHERE id=?",
                (command.medicine_id,),
            ).fetchone()
            if medicine_row is None:
                raise ManualExecutionPreconditionError(
                    "药品库存记录已经变化，请重新核查。"
                )
            medicine = MedicineRepository._row_to_medicine(medicine_row)
            if (
                medicine.slot != command.slot
                or int(medicine.hardware_slot or 0) != command.expected_hardware_slot
            ):
                raise ManualExecutionPreconditionError(
                    "药品仓位映射已经变化，请重新核查。"
                )
            if (
                medicine.stock != command.expected_stock
                or medicine.stock < command.quantity
            ):
                raise ManualExecutionPreconditionError(
                    "药品库存记录已经变化，请重新核查。"
                )
            if (
                medicine.expire_date != command.expected_expire_date
                or MedicineRepository.review_fingerprint(medicine)
                != command.expected_review_fingerprint
            ):
                raise ManualExecutionPreconditionError(
                    "药品身份或安全资料已经变化，请重新核查。"
                )

    @classmethod
    def _person_from_row(cls, row: object) -> ManualMedicationPersonSnapshot:
        values = dict(row)
        return ManualMedicationPersonSnapshot(
            service_user_id=str(values["id"]),
            name=str(values["name"]),
            legacy_allergies=str(values["allergies"] or ""),
            persona_generation=str(values["persona_generation"] or ""),
            safety_profile_revision=max(1, int(values["safety_profile_revision"] or 1)),
            medical_conditions=tuple(cls._json_object_list(values["medical_conditions_json"])),
            current_medications=tuple(cls._json_object_list(values["current_medications_json"])),
            allergy_facts=tuple(cls._json_object_list(values["allergy_facts_json"])),
            archived=bool(values["archived"]),
        )

    def get_replay(
        self,
        *,
        request_id: str,
        request_payload_digest: str,
    ) -> ManualMedicationAssessment | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT check_id, request_payload_digest, check_status,
                       reason_codes_json, reason_summary, expires_at, dispense_status
                FROM medicine_safety_checks WHERE request_id=?
                """,
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        if str(row["request_payload_digest"]) != request_payload_digest:
            raise ManualAccessIdempotencyConflict("同一 request_id 不能用于不同的安全核查请求。")
        return self._assessment_from_row(row)

    def save_assessment(
        self,
        *,
        snapshot: SafetyCheckSnapshot,
        request_payload_digest: str,
        assessment: ManualMedicationAssessment,
        created_at: str,
    ) -> ManualMedicationAssessment:
        db.init_db()
        reason_codes_json = json.dumps(assessment.reason_codes, ensure_ascii=False)
        event_id = f"medication-safety:{assessment.check_id}"
        event_payload = {
            "schema_version": 1,
            "event_id": event_id,
            "check_id": assessment.check_id,
            "route": "MANUAL_INVENTORY",
            "service_user_id": snapshot.service_user_id,
            "service_user_name": snapshot.service_user_name,
            "persona_generation": snapshot.persona_generation,
            "profile_revision": snapshot.safety_profile_revision,
            "medicine_id": snapshot.medicine_id,
            "medicine_name": snapshot.medicine_name,
            "slot": snapshot.slot,
            "medicine": {
                "id": snapshot.medicine_id,
                "name": snapshot.medicine_name,
                "slot": snapshot.hardware_slot,
            },
            "check_status": assessment.check_status,
            "dispense_status": assessment.dispense_status,
            "reason_codes": assessment.reason_codes,
            "reason_summary": assessment.message,
            "caregiver_summary": assessment.message,
            "ruleset_version": snapshot.ruleset_version,
            "medicine_review_fingerprint": snapshot.review_fingerprint,
            "qsm_operation_id": "",
            "occurred_at": created_at,
            "updated_at": created_at,
        }
        payload_json = self._canonical_json(event_payload)
        payload_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT check_id, request_payload_digest, check_status,
                       reason_codes_json, reason_summary, expires_at, dispense_status
                FROM medicine_safety_checks WHERE request_id=?
                """,
                (snapshot.request_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["request_payload_digest"]) != request_payload_digest:
                    raise ManualAccessIdempotencyConflict(
                        "同一 request_id 不能用于不同的安全核查请求。"
                    )
                return self._assessment_from_row(existing)
            conn.execute(
                """
                INSERT INTO medicine_safety_checks(
                  check_id, request_id, request_payload_digest, route,
                  service_user_id, service_user_name_snapshot, persona_generation,
                  safety_profile_revision, person_safety_fingerprint, verification_method,
                  verification_assertion_id, medicine_id, medicine_name_snapshot,
                  slot, hardware_slot_snapshot, stock_snapshot,
                  review_fingerprint, check_status, reason_codes_json,
                  reason_summary, ruleset_version, expires_at, dispense_status,
                  created_at, updated_at
                ) VALUES (?, ?, ?, 'MANUAL_INVENTORY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.check_id,
                    snapshot.request_id,
                    request_payload_digest,
                    snapshot.service_user_id,
                    snapshot.service_user_name,
                    snapshot.persona_generation,
                    snapshot.safety_profile_revision,
                    snapshot.person_safety_fingerprint,
                    snapshot.verification_method,
                    snapshot.verification_assertion_id,
                    snapshot.medicine_id,
                    snapshot.medicine_name,
                    snapshot.slot,
                    snapshot.hardware_slot,
                    snapshot.stock,
                    snapshot.review_fingerprint,
                    assessment.check_status,
                    reason_codes_json,
                    assessment.message,
                    snapshot.ruleset_version,
                    assessment.expires_at,
                    assessment.dispense_status,
                    created_at,
                    created_at,
                ),
            )
            if assessment.check_status != "PASSED":
                conn.execute(
                    """
                    INSERT INTO medication_safety_outbox(
                      event_id, aggregate_id, event_type, payload_json,
                      payload_digest, status, attempts, next_attempt_at, created_at
                    ) VALUES (?, ?, 'MEDICATION_SAFETY_EVENT_RECORDED', ?, ?, 'pending', 0, ?, ?)
                    """,
                    (
                        event_id,
                        assessment.check_id,
                        payload_json,
                        payload_digest,
                        created_at,
                        created_at,
                    ),
                )
        return assessment

    def get_check(self, check_id: str) -> StoredSafetyCheck | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT check_id, service_user_id, service_user_name_snapshot,
                       persona_generation, safety_profile_revision,
                       person_safety_fingerprint,
                       verification_method, verification_assertion_id,
                       medicine_id, medicine_name_snapshot, slot,
                       hardware_slot_snapshot, stock_snapshot,
                       review_fingerprint, check_status, expires_at,
                       consumed_at, dispense_status
                FROM medicine_safety_checks WHERE check_id=?
                """,
                (check_id,),
            ).fetchone()
        return self._stored_check_from_row(row) if row is not None else None

    def get_confirm_replay(
        self,
        *,
        request_id: str,
        request_payload_digest: str,
    ) -> ManualMedicationOutcome | None:
        """Return one request's terminal result, waiting while its owner is active.

        An owner that disappears leaves the persisted RESULT_UNKNOWN boundary as
        the safe replay after the bounded wait; callers must never execute QSM
        again for that request ID.
        """
        db.init_db()
        deadline = time.monotonic() + self._CONFIRM_REPLAY_WAIT_SECONDS
        while True:
            with db.connect() as conn:
                row = conn.execute(
                    """
                    SELECT check_id, confirm_payload_digest, check_status, dispense_status,
                           confirm_message, dispense_record_id, confirm_completed_at
                    FROM medicine_safety_checks WHERE confirm_request_id=?
                    """,
                    (request_id,),
                ).fetchone()
            if row is None:
                return None
            if str(row["confirm_payload_digest"]) != request_payload_digest:
                raise ManualAccessIdempotencyConflict("同一 request_id 不能用于不同的取药确认请求。")
            outcome = self._confirm_outcome_from_row(row)
            if str(row["confirm_completed_at"] or ""):
                if (
                    str(row["check_status"]) in {"BLOCKED", "CHECK_FAILED"}
                    and str(row["dispense_status"]) == "NOT_STARTED"
                ):
                    raise ManualExecutionPreconditionError(outcome.message)
                return outcome
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._terminalize_abandoned_confirm(
                    request_id=request_id,
                    request_payload_digest=request_payload_digest,
                )
            time.sleep(min(self._CONFIRM_REPLAY_POLL_SECONDS, remaining))

    def _terminalize_abandoned_confirm(
        self,
        *,
        request_id: str,
        request_payload_digest: str,
    ) -> ManualMedicationOutcome:
        """Persist the fail-safe result left by a confirm owner that disappeared."""
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._select_confirm_event_row(
                conn,
                "confirm_request_id=?",
                (request_id,),
            )
            if row is None:
                raise RuntimeError("取药确认幂等状态不完整，请勿自动重试。")
            if str(row["confirm_payload_digest"]) != request_payload_digest:
                raise ManualAccessIdempotencyConflict(
                    "同一 request_id 不能用于不同的取药确认请求。"
                )
            if str(row["confirm_completed_at"] or ""):
                return self._confirm_outcome_from_row(row)
            completed_at = db.now_text()
            cursor = conn.execute(
                """
                UPDATE medicine_safety_checks
                SET dispense_status='RESULT_UNKNOWN',
                    confirm_message=CASE WHEN confirm_message='' THEN ? ELSE confirm_message END,
                    confirm_completed_at=?, updated_at=?
                WHERE check_id=? AND confirm_completed_at=''
                """,
                (
                    "柜门操作已进入执行边界，当前结果待确认，请勿重复取药。",
                    completed_at,
                    completed_at,
                    str(row["check_id"]),
                ),
            )
            if cursor.rowcount != 1:
                row = self._select_confirm_event_row(
                    conn,
                    "confirm_request_id=?",
                    (request_id,),
                )
                if row is None or not str(row["confirm_completed_at"] or ""):
                    raise RuntimeError("取药确认结果未能原子终态化。")
                return self._confirm_outcome_from_row(row)
            terminal = self._select_confirm_event_row(
                conn,
                "confirm_request_id=?",
                (request_id,),
            )
            if terminal is None:
                raise RuntimeError("取药确认终态丢失。")
            self._insert_terminal_event(conn, terminal)
            return self._confirm_outcome_from_row(terminal)

    def begin_confirm(
        self,
        *,
        request_id: str,
        request_payload_digest: str,
        check_id: str,
        qsm_operation_id: str,
        consumed_at: str,
    ) -> bool:
        """Atomically claim QSM execution; false means an identical claim exists."""
        db.init_db()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            replay = conn.execute(
                "SELECT check_id, confirm_payload_digest FROM medicine_safety_checks WHERE confirm_request_id=?",
                (request_id,),
            ).fetchone()
            if replay is not None:
                if str(replay["confirm_payload_digest"]) != request_payload_digest:
                    raise ManualAccessIdempotencyConflict(
                        "同一 request_id 不能用于不同的取药确认请求。"
                    )
                return False
            row = conn.execute(
                """
                SELECT check_id, service_user_id, service_user_name_snapshot,
                       persona_generation, safety_profile_revision,
                       person_safety_fingerprint,
                       verification_method, verification_assertion_id,
                       medicine_id, medicine_name_snapshot, slot,
                       hardware_slot_snapshot, stock_snapshot,
                       review_fingerprint, check_status, expires_at,
                       consumed_at, dispense_status
                FROM medicine_safety_checks WHERE check_id=?
                """,
                (check_id,),
            ).fetchone()
            if row is None:
                raise ValueError("安全核查记录不存在。")
            stored = self._stored_check_from_row(row)
            if stored.check_status != "PASSED":
                raise ValueError("只有核查通过的记录才能继续取药。")
            if stored.consumed_at:
                raise ValueError("该安全核查已被使用，请重新确认身份并核查。")
            if not stored.expires_at or stored.expires_at <= consumed_at:
                raise ValueError("该安全核查已过期，请重新确认身份并核查。")
            unknown_message = "柜门操作已进入执行边界，当前结果待确认，请勿重复取药。"
            cursor = conn.execute(
                """
                UPDATE medicine_safety_checks
                SET consumed_at=?, qsm_operation_id=?, confirm_request_id=?,
                    confirm_payload_digest=?, dispense_status='RESULT_UNKNOWN',
                    confirm_message=?, confirm_completed_at='', updated_at=?
                WHERE check_id=? AND consumed_at=''
                """,
                (
                    consumed_at,
                    qsm_operation_id,
                    request_id,
                    request_payload_digest,
                    unknown_message,
                    consumed_at,
                    check_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("该安全核查已被使用，请重新确认身份并核查。")
        return True

    def complete_confirm(
        self,
        *,
        check_id: str,
        dispense_status: str,
        message: str,
        dispense_record_id: str,
        completed_at: str,
    ) -> ManualMedicationOutcome:
        if dispense_status not in {"DISPENSED", "HARDWARE_FAILED", "RESULT_UNKNOWN"}:
            raise ValueError("不支持的物理取药结果。")
        db.init_db()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._select_confirm_event_row(
                conn,
                "check_id=?",
                (check_id,),
            )
            if row is None:
                raise ValueError("安全核查记录不存在。")
            if str(row["confirm_completed_at"] or ""):
                return self._confirm_outcome_from_row(row)
            cursor = conn.execute(
                """
                UPDATE medicine_safety_checks
                SET dispense_status=?, dispense_record_id=?, confirm_message=?,
                    confirm_completed_at=?, updated_at=?
                WHERE check_id=? AND confirm_completed_at=''
                """,
                (
                    dispense_status,
                    dispense_record_id,
                    message,
                    completed_at,
                    completed_at,
                    check_id,
                ),
            )
            if cursor.rowcount != 1:
                terminal = self._select_confirm_event_row(
                    conn,
                    "check_id=?",
                    (check_id,),
                )
                if terminal is None or not str(terminal["confirm_completed_at"] or ""):
                    raise RuntimeError("取药确认结果未能原子保存。")
                return self._confirm_outcome_from_row(terminal)
            terminal = self._select_confirm_event_row(
                conn,
                "check_id=?",
                (check_id,),
            )
            if terminal is None:
                raise RuntimeError("取药确认终态丢失。")
            self._insert_terminal_event(conn, terminal)
            return self._confirm_outcome_from_row(terminal)

    def invalidate_confirm_before_qsm(
        self,
        *,
        check_id: str,
        request_id: str,
        request_payload_digest: str,
        check_status: str,
        reason_codes: list[str],
        message: str,
        completed_at: str,
    ) -> ManualMedicationOutcome:
        """Terminalize a stale pass without claiming a physical cabinet result."""
        if check_status not in {"BLOCKED", "CHECK_FAILED"}:
            raise ValueError("失效的安全核查必须记录为阻止或核查失败。")
        db.init_db()
        reason_codes_json = json.dumps(reason_codes, ensure_ascii=False)
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT check_id, confirm_request_id, confirm_payload_digest,
                       dispense_status, confirm_message, dispense_record_id,
                       confirm_completed_at
                FROM medicine_safety_checks WHERE check_id=?
                """,
                (check_id,),
            ).fetchone()
            if existing is None:
                raise ValueError("安全核查记录不存在。")
            existing_request_id = str(existing["confirm_request_id"] or "")
            if existing_request_id and existing_request_id != request_id:
                raise ValueError("该安全核查已被使用，请重新确认身份并核查。")
            if existing_request_id and str(existing["confirm_payload_digest"]) != request_payload_digest:
                raise ManualAccessIdempotencyConflict(
                    "同一 request_id 不能用于不同的取药确认请求。"
                )
            if str(existing["confirm_completed_at"] or ""):
                return self._confirm_outcome_from_row(existing)
            cursor = conn.execute(
                """
                UPDATE medicine_safety_checks
                SET check_status=?, reason_codes_json=?, reason_summary=?,
                    expires_at='', consumed_at=CASE WHEN consumed_at='' THEN ? ELSE consumed_at END,
                    dispense_status='NOT_STARTED', dispense_record_id='',
                    qsm_operation_id='', confirm_request_id=?,
                    confirm_payload_digest=?, confirm_message=?,
                    confirm_completed_at=?, updated_at=?
                WHERE check_id=? AND confirm_completed_at=''
                """,
                (
                    check_status,
                    reason_codes_json,
                    message,
                    completed_at,
                    request_id,
                    request_payload_digest,
                    message,
                    completed_at,
                    completed_at,
                    check_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("安全核查失效状态未能原子保存。")
            terminal = self._select_confirm_event_row(
                conn,
                "check_id=?",
                (check_id,),
            )
            if terminal is None:
                raise RuntimeError("安全核查失效终态丢失。")
            self._insert_terminal_event(conn, terminal)
            return self._confirm_outcome_from_row(terminal)

    @staticmethod
    def _select_confirm_event_row(
        conn: sqlite3.Connection,
        predicate: str,
        params: tuple[object, ...],
    ) -> sqlite3.Row | None:
        return conn.execute(
            f"""
            SELECT check_id, confirm_request_id, confirm_payload_digest,
                   dispense_status, confirm_message, dispense_record_id,
                   confirm_completed_at, service_user_id,
                   service_user_name_snapshot, persona_generation,
                   safety_profile_revision, medicine_id,
                   medicine_name_snapshot, slot, hardware_slot_snapshot,
                   review_fingerprint, check_status, reason_codes_json,
                   reason_summary, ruleset_version, qsm_operation_id
            FROM medicine_safety_checks WHERE {predicate}
            """,
            params,
        ).fetchone()

    def _insert_terminal_event(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        check_id = str(row["check_id"])
        completed_at = str(row["confirm_completed_at"])
        event_id = f"medication-safety:{check_id}"
        event_payload = {
            "schema_version": 1,
            "event_id": event_id,
            "check_id": check_id,
            "route": "MANUAL_INVENTORY",
            "service_user_id": str(row["service_user_id"]),
            "service_user_name": str(row["service_user_name_snapshot"]),
            "persona_generation": str(row["persona_generation"] or ""),
            "profile_revision": int(row["safety_profile_revision"] or 0),
            "medicine_id": str(row["medicine_id"]),
            "medicine_name": str(row["medicine_name_snapshot"]),
            "slot": str(row["slot"]),
            "medicine": {
                "id": str(row["medicine_id"]),
                "name": str(row["medicine_name_snapshot"]),
                "slot": int(row["hardware_slot_snapshot"] or 0),
            },
            "check_status": str(row["check_status"]),
            "dispense_status": str(row["dispense_status"]),
            "reason_codes": json.loads(str(row["reason_codes_json"] or "[]")),
            "reason_summary": str(row["reason_summary"] or ""),
            "caregiver_summary": str(row["confirm_message"] or ""),
            "ruleset_version": str(row["ruleset_version"]),
            "medicine_review_fingerprint": str(row["review_fingerprint"] or ""),
            "qsm_operation_id": str(row["qsm_operation_id"] or ""),
            "occurred_at": completed_at,
            "updated_at": completed_at,
        }
        payload_json = self._canonical_json(event_payload)
        payload_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        existing = conn.execute(
            "SELECT payload_digest FROM medication_safety_outbox WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_digest"]) != payload_digest:
                raise ManualAccessIdempotencyConflict(
                    "同一安全事件不能保存不同的终态结果。"
                )
            return
        conn.execute(
            """
            INSERT INTO medication_safety_outbox(
              event_id, aggregate_id, event_type, payload_json,
              payload_digest, status, attempts, next_attempt_at, created_at
            ) VALUES (?, ?, 'MEDICATION_SAFETY_EVENT_RECORDED', ?, ?, 'pending', 0, ?, ?)
            """,
            (event_id, check_id, payload_json, payload_digest, completed_at, completed_at),
        )

    def count_checks(self, *, request_id: str = "") -> int:
        db.init_db()
        query = "SELECT COUNT(*) AS count FROM medicine_safety_checks"
        params: tuple[object, ...] = ()
        if request_id:
            query += " WHERE request_id=?"
            params = (request_id,)
        with db.connect() as conn:
            return int(conn.execute(query, params).fetchone()["count"])

    def count_outbox_events(self, *, check_id: str = "") -> int:
        db.init_db()
        query = "SELECT COUNT(*) AS count FROM medication_safety_outbox"
        params: tuple[object, ...] = ()
        if check_id:
            query += " WHERE aggregate_id=?"
            params = (check_id,)
        with db.connect() as conn:
            return int(conn.execute(query, params).fetchone()["count"])

    @staticmethod
    def _assessment_from_row(row: object) -> ManualMedicationAssessment:
        values = dict(row)
        try:
            reason_codes = json.loads(str(values.get("reason_codes_json") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            reason_codes = []
        return ManualMedicationAssessment(
            check_id=str(values["check_id"]),
            check_status=str(values["check_status"]),
            reason_codes=[str(value) for value in reason_codes if str(value).strip()],
            message=str(values["reason_summary"]),
            expires_at=str(values.get("expires_at") or ""),
            dispense_status=str(values.get("dispense_status") or "NOT_STARTED"),
        )

    @staticmethod
    def _confirm_outcome_from_row(row: object) -> ManualMedicationOutcome:
        values = dict(row)
        status = str(values.get("dispense_status") or "RESULT_UNKNOWN")
        return ManualMedicationOutcome(
            ok=status == "DISPENSED",
            safety_check_id=str(values["check_id"]),
            dispense_status=status,
            message=str(
                values.get("confirm_message")
                or "柜门结果待现场确认，请勿自动重试。"
            ),
            dispense_record_id=str(values.get("dispense_record_id") or ""),
        )

    @staticmethod
    def _stored_check_from_row(row: object) -> StoredSafetyCheck:
        values = dict(row)
        return StoredSafetyCheck(
            check_id=str(values["check_id"]),
            service_user_id=str(values["service_user_id"]),
            service_user_name=str(values["service_user_name_snapshot"]),
            persona_generation=str(values["persona_generation"] or ""),
            safety_profile_revision=int(values["safety_profile_revision"] or 0),
            person_safety_fingerprint=str(values.get("person_safety_fingerprint") or ""),
            verification_method=str(values["verification_method"]),
            verification_assertion_id=str(values["verification_assertion_id"]),
            medicine_id=str(values["medicine_id"]),
            medicine_name=str(values["medicine_name_snapshot"]),
            slot=str(values["slot"]),
            hardware_slot=int(values.get("hardware_slot_snapshot") or 0),
            stock=int(values.get("stock_snapshot") if values.get("stock_snapshot") is not None else -1),
            review_fingerprint=str(values["review_fingerprint"]),
            check_status=str(values["check_status"]),
            expires_at=str(values["expires_at"] or ""),
            consumed_at=str(values["consumed_at"] or ""),
            dispense_status=str(values["dispense_status"] or "NOT_STARTED"),
        )

    @staticmethod
    def _json_object_list(value: object) -> list[dict[str, object]]:
        try:
            parsed = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
