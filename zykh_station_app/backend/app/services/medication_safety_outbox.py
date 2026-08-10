from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import json

from .. import db


_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class PendingMedicationSafetyEvent:
    event_id: str
    payload: dict[str, object]
    payload_digest: str
    attempts: int


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
        for event in self._claim(limit=limit):
            try:
                sender(
                    "REPORT_MEDICATION_SAFETY_EVENT",
                    {
                        "event": event.payload,
                        "payloadDigest": event.payload_digest,
                    },
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
                SELECT event_id, payload_json, payload_digest, attempts
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
                SELECT event_id, payload_json, payload_digest, attempts
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
                )
            )
        return events

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
