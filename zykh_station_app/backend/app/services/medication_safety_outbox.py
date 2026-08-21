from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import re

from .. import db
from .medicine_cloud_projection import (
    MedicineCloudProjection,
    MedicineCloudProjectionError,
    cloud_projection_for_local_medicine_id,
    resolve_cloud_medicine,
)


_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_EVENT_SLOT_ALIASES = ("slot", "legacySlot", "hardwareSlot", "hardware_slot")


def _projection_for_event_identity(value: object) -> MedicineCloudProjection | None:
    medicine_id = str(value or "").strip()
    if not medicine_id:
        return None
    try:
        return cloud_projection_for_local_medicine_id(medicine_id)
    except MedicineCloudProjectionError:
        try:
            return resolve_cloud_medicine(medicine_id=medicine_id)
        except MedicineCloudProjectionError:
            return None


def _event_slot_number(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("安全事件包含无法识别的药品仓位别名。")
    match = re.fullmatch(r"[sS]?(\d+)", str(value or "").strip())
    if match is None:
        raise ValueError("安全事件包含无法识别的药品仓位别名。")
    slot = int(match.group(1))
    if slot <= 0:
        raise ValueError("安全事件包含无法识别的药品仓位别名。")
    return slot


def _cloud_event_projection(payload: dict[str, object]) -> dict[str, object]:
    projected = deepcopy(payload)
    medicine = projected.get("medicine")
    nested = medicine if isinstance(medicine, dict) else {}
    identity_values = [
        projected.get(name)
        for name in ("medicine_id", "medicineId")
        if projected.get(name)
    ]
    identity_values.extend(
        nested.get(name)
        for name in ("id", "medicine_id", "medicineId")
        if nested.get(name)
    )
    resolved = [_projection_for_event_identity(value) for value in identity_values]
    known = {item for item in resolved if item is not None}
    if known and any(item is None for item in resolved):
        raise ValueError("安全事件包含无法识别的药品身份别名。")
    if len(known) > 1:
        raise ValueError("安全事件包含相互冲突的药品身份别名。")
    if not known:
        raise ValueError("安全事件无法识别固定药品身份。")

    projection = next(iter(known))
    allowed_slots = {
        projection.local_legacy_slot,
        projection.cloud_legacy_slot,
    }
    for container in (projected, nested):
        for name in _EVENT_SLOT_ALIASES:
            if (
                name in container
                and _event_slot_number(container[name]) not in allowed_slots
            ):
                raise ValueError("安全事件药品身份与仓位别名相互冲突。")
    for name in ("medicine_id", "medicineId"):
        if name in projected:
            projected[name] = projection.cloud_medicine_id
    if isinstance(medicine, dict):
        for name in ("id", "medicine_id", "medicineId"):
            if name in medicine:
                medicine[name] = projection.cloud_medicine_id
        for name in _EVENT_SLOT_ALIASES:
            if name in medicine:
                medicine[name] = projection.cloud_legacy_slot
    for name in _EVENT_SLOT_ALIASES:
        if name in projected:
            projected[name] = projection.cloud_legacy_slot
    return projected


@dataclass(frozen=True)
class PendingMedicationSafetyEvent:
    event_id: str
    payload: dict[str, object]
    payload_digest: str
    attempts: int
    wire_payload: dict[str, object] | None = None
    wire_payload_digest: str = ""


class MedicationSafetyOutbox:
    """Incremental append-only delivery; it is intentionally outside snapshots."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or datetime.now

    def flush(
        self,
        sender: Callable[[str, dict[str, object]], object],
        *,
        capabilities: dict[str, object],
        limit: int = 20,
    ) -> int:
        if str(capabilities.get("medicationSafetyEvents") or "") != "v1":
            return 0
        sent = 0
        for claimed_event in self._claim(limit=limit):
            event = claimed_event
            try:
                event = self._materialize_wire_payload(event)
                receipt = sender(
                    "REPORT_MEDICATION_SAFETY_EVENT",
                    {
                        "event": event.wire_payload,
                        "payloadDigest": event.wire_payload_digest,
                    },
                )
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("eventId") != event.event_id
                ):
                    raise ValueError("安全事件云端回执 eventId 与发送事件不一致。")
                if receipt.get("payloadDigest") != event.wire_payload_digest:
                    raise ValueError(
                        "安全事件云端回执 payloadDigest 与发送载荷不一致。"
                    )
            except Exception:
                self._mark_failed(event)
                raise
            self._mark_sent(event)
            sent += 1
        return sent

    def pending(self, *, limit: int = 20) -> list[PendingMedicationSafetyEvent]:
        db.init_db()
        now_text = self._clock().strftime(_TIMESTAMP_FORMAT)
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, payload_json, payload_digest, attempts,
                       wire_payload_json, wire_payload_digest
                FROM medication_safety_outbox
                WHERE status='pending' AND next_attempt_at<=?
                ORDER BY created_at, event_id
                LIMIT ?
                """,
                (now_text, max(1, min(int(limit), 100))),
            ).fetchall()
        events: list[PendingMedicationSafetyEvent] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            events.append(
                PendingMedicationSafetyEvent(
                    event_id=str(row["event_id"]),
                    payload=payload,
                    payload_digest=str(row["payload_digest"]),
                    attempts=max(0, int(row["attempts"] or 0)),
                    wire_payload=self._wire_payload_from_row(row),
                    wire_payload_digest=str(row["wire_payload_digest"] or ""),
                )
            )
        return events

    def pending_count(self) -> int:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM medication_safety_outbox "
                "WHERE status IN ('pending', 'sending')"
            ).fetchone()
        return int(row["count"])

    def _claim(self, *, limit: int) -> list[PendingMedicationSafetyEvent]:
        """Lease a batch before network I/O so concurrent workers cannot double-send it."""
        db.init_db()
        now = self._clock()
        now_text = now.strftime(_TIMESTAMP_FORMAT)
        lease_until = (now + timedelta(minutes=2)).strftime(_TIMESTAMP_FORMAT)
        maximum = max(1, min(int(limit), 100))
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE medication_safety_outbox
                SET status='pending'
                WHERE status='sending' AND next_attempt_at<=?
                """,
                (now_text,),
            )
            rows = conn.execute(
                """
                SELECT event_id, payload_json, payload_digest, attempts,
                       wire_payload_json, wire_payload_digest
                FROM medication_safety_outbox
                WHERE status='pending' AND next_attempt_at<=?
                ORDER BY created_at, event_id
                LIMIT ?
                """,
                (now_text, maximum),
            ).fetchall()
            claimed_rows = []
            for row in rows:
                cursor = conn.execute(
                    """
                    UPDATE medication_safety_outbox
                    SET status='sending', next_attempt_at=?
                    WHERE event_id=? AND payload_digest=? AND status='pending'
                    """,
                    (lease_until, row["event_id"], row["payload_digest"]),
                )
                if cursor.rowcount == 1:
                    claimed_rows.append(row)
        return self._events_from_rows(claimed_rows)

    @staticmethod
    def _events_from_rows(rows: list[object]) -> list[PendingMedicationSafetyEvent]:
        events: list[PendingMedicationSafetyEvent] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            events.append(
                PendingMedicationSafetyEvent(
                    event_id=str(row["event_id"]),
                    payload=payload,
                    payload_digest=str(row["payload_digest"]),
                    attempts=max(0, int(row["attempts"] or 0)),
                    wire_payload=MedicationSafetyOutbox._wire_payload_from_row(row),
                    wire_payload_digest=str(row["wire_payload_digest"] or ""),
                )
            )
        return events

    @staticmethod
    def _wire_payload_from_row(row: object) -> dict[str, object] | None:
        wire_payload_json = str(row["wire_payload_json"] or "")
        if not wire_payload_json:
            return None
        try:
            payload = json.loads(wire_payload_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _materialize_wire_payload(
        self,
        event: PendingMedicationSafetyEvent,
    ) -> PendingMedicationSafetyEvent:
        if event.wire_payload is not None and event.wire_payload_digest:
            return event
        if event.wire_payload is not None or event.wire_payload_digest:
            raise ValueError("安全事件已持久化的发送载荷不完整。")

        wire_payload = _cloud_event_projection(event.payload)
        wire_payload_json = json.dumps(
            wire_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        wire_payload_digest = hashlib.sha256(
            wire_payload_json.encode("utf-8")
        ).hexdigest()
        with db.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE medication_safety_outbox
                SET wire_payload_json=?, wire_payload_digest=?
                WHERE event_id=? AND payload_digest=? AND status='sending'
                  AND wire_payload_json='' AND wire_payload_digest=''
                """,
                (
                    wire_payload_json,
                    wire_payload_digest,
                    event.event_id,
                    event.payload_digest,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("安全事件发送载荷未能稳定持久化。")
        return PendingMedicationSafetyEvent(
            event_id=event.event_id,
            payload=event.payload,
            payload_digest=event.payload_digest,
            attempts=event.attempts,
            wire_payload=wire_payload,
            wire_payload_digest=wire_payload_digest,
        )

    def _mark_sent(self, event: PendingMedicationSafetyEvent) -> None:
        sent_at = self._clock().strftime(_TIMESTAMP_FORMAT)
        with db.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE medication_safety_outbox
                SET status='sent', sent_at=?
                WHERE event_id=? AND payload_digest=? AND status='sending'
                """,
                (sent_at, event.event_id, event.payload_digest),
            )
            if cursor.rowcount != 1:
                raise ValueError("安全事件在发送期间发生变化，未标记为已发送。")

    def _mark_failed(self, event: PendingMedicationSafetyEvent) -> None:
        attempts = event.attempts + 1
        delay_seconds = min(300, 5 * (2 ** min(attempts - 1, 6)))
        next_attempt_at = (self._clock() + timedelta(seconds=delay_seconds)).strftime(
            _TIMESTAMP_FORMAT
        )
        with db.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE medication_safety_outbox
                SET status='pending', attempts=attempts+1, next_attempt_at=?
                WHERE event_id=? AND payload_digest=? AND status='sending'
                """,
                (next_attempt_at, event.event_id, event.payload_digest),
            )
            if cursor.rowcount != 1:
                raise ValueError("安全事件发送失败状态已发生变化。")
