from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db
from app.services.medication_safety_outbox import MedicationSafetyOutbox


class MedicationSafetyOutboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "medication-safety-outbox.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _insert_pending_event(
        self,
        event_id: str = "event-001",
        payload: dict[str, object] | None = None,
        *,
        attempts: int = 0,
    ) -> str:
        payload = payload or {
            "event_id": event_id,
            "check_id": "safety-check-001",
            "medicine_id": "slot-01-fufang-ganmaoling",
            "check_status": "BLOCKED",
            "dispense_status": "NOT_STARTED",
        }
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO medication_safety_outbox(
                  event_id, aggregate_id, event_type, payload_json, payload_digest,
                  status, attempts, next_attempt_at, created_at, sent_at
                ) VALUES (?, 'safety-check-001', 'MEDICATION_SAFETY_EVENT_RECORDED',
                          ?, ?, 'pending', ?, ?, ?, '')
                """,
                (
                    event_id,
                    payload_json,
                    digest,
                    attempts,
                    db.now_text(),
                    db.now_text(),
                ),
            )
        return digest

    def _replace_with_legacy_outbox_schema(self) -> None:
        with db.connect() as conn:
            conn.execute("DROP TABLE medication_safety_outbox")
            conn.execute(
                """
                CREATE TABLE medication_safety_outbox (
                  event_id TEXT PRIMARY KEY,
                  aggregate_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  payload_digest TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'pending',
                  attempts INTEGER NOT NULL DEFAULT 0,
                  next_attempt_at TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  sent_at TEXT NOT NULL DEFAULT ''
                )
                """
            )

    def test_flush_reports_once_and_marks_sent_only_after_success(self) -> None:
        digest = self._insert_pending_event()
        calls: list[tuple[str, dict[str, object]]] = []

        def sender(action: str, payload: dict[str, object]) -> dict[str, object]:
            calls.append((action, payload))
            return {"ok": True, "replayed": False}

        outbox = MedicationSafetyOutbox()
        first = outbox.flush(
            sender,
            capabilities={"medicationSafetyEvents": "v1"},
        )
        replay = outbox.flush(
            sender,
            capabilities={"medicationSafetyEvents": "v1"},
        )

        self.assertEqual((first, replay), (1, 0))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "REPORT_MEDICATION_SAFETY_EVENT")
        self.assertEqual(calls[0][1]["payloadDigest"], digest)
        self.assertEqual(calls[0][1]["event"]["event_id"], "event-001")
        self.assertEqual(outbox.pending_count(), 0)

    def test_flush_projects_local_medicine_identity_and_recomputes_cloud_digest(self) -> None:
        local_payload = {
            "event_id": "event-ibuprofen-001",
            "medicine_id": "slot-13-ibuprofen",
            "slot": "S13",
            "medicine": {
                "id": "slot-13-ibuprofen",
                "name": "布洛芬缓释胶囊",
                "slot": 13,
            },
            "check_status": "BLOCKED",
            "dispense_status": "NOT_APPLICABLE",
        }
        local_digest = self._insert_pending_event(
            "event-ibuprofen-001",
            local_payload,
        )
        calls: list[tuple[str, dict[str, object]]] = []

        MedicationSafetyOutbox().flush(
            lambda action, payload: calls.append((action, payload)),
            capabilities={"medicationSafetyEvents": "v1"},
        )

        sent_payload = calls[0][1]
        sent_event = sent_payload["event"]
        self.assertEqual(sent_event["medicine_id"], "slot-03-ibuprofen")
        self.assertEqual(sent_event["medicine"]["id"], "slot-03-ibuprofen")
        self.assertEqual(sent_event["slot"], 3)
        self.assertEqual(sent_event["medicine"]["slot"], 3)
        encoded = json.dumps(
            sent_event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(
            sent_payload["payloadDigest"],
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(sent_payload["payloadDigest"], local_digest)
        with db.connect() as conn:
            row = conn.execute(
                "SELECT payload_digest, status FROM medication_safety_outbox WHERE event_id=?",
                ("event-ibuprofen-001",),
            ).fetchone()
        self.assertEqual(row["payload_digest"], local_digest)
        self.assertEqual(row["status"], "sent")

    def test_retry_reuses_wire_payload_materialized_before_first_send(self) -> None:
        self._insert_pending_event(
            "event-ibuprofen-retry-001",
            {
                "event_id": "event-ibuprofen-retry-001",
                "medicine_id": "slot-13-ibuprofen",
                "slot": 13,
                "check_status": "BLOCKED",
                "dispense_status": "NOT_APPLICABLE",
            },
        )
        now = [datetime(2026, 8, 21, 12, 0, 0)]
        first_attempts: list[dict[str, object]] = []

        def failing_sender(_action: str, payload: dict[str, object]) -> None:
            first_attempts.append(payload)
            raise RuntimeError("temporary network failure")

        with self.assertRaisesRegex(RuntimeError, "temporary network failure"):
            MedicationSafetyOutbox(clock=lambda: now[0]).flush(
                failing_sender,
                capabilities={"medicationSafetyEvents": "v1"},
            )

        with db.connect() as conn:
            persisted = conn.execute(
                """
                SELECT wire_payload_json, wire_payload_digest
                FROM medication_safety_outbox
                WHERE event_id='event-ibuprofen-retry-001'
                """
            ).fetchone()
        self.assertEqual(json.loads(persisted["wire_payload_json"]), first_attempts[0]["event"])
        self.assertEqual(persisted["wire_payload_digest"], first_attempts[0]["payloadDigest"])

        now[0] += timedelta(seconds=6)
        retries: list[dict[str, object]] = []
        with patch(
            "app.services.medication_safety_outbox._cloud_event_projection",
            return_value={
                "event_id": "event-ibuprofen-retry-001",
                "medicine_id": "future-projection",
                "slot": 99,
            },
        ):
            sent = MedicationSafetyOutbox(clock=lambda: now[0]).flush(
                lambda _action, payload: retries.append(payload),
                capabilities={"medicationSafetyEvents": "v1"},
            )

        self.assertEqual(sent, 1)
        self.assertEqual(retries, first_attempts)

    def test_migration_preserves_attempted_legacy_event_as_wire_payload(self) -> None:
        self._replace_with_legacy_outbox_schema()
        legacy_payload = {
            "event_id": "event-legacy-attempted-001",
            "medicine_id": "slot-13-ibuprofen",
            "slot": 13,
            "check_status": "BLOCKED",
            "dispense_status": "NOT_APPLICABLE",
        }
        legacy_digest = self._insert_pending_event(
            "event-legacy-attempted-001",
            legacy_payload,
            attempts=2,
        )
        calls: list[dict[str, object]] = []

        with patch(
            "app.services.medication_safety_outbox._cloud_event_projection",
            return_value={
                "event_id": "event-legacy-attempted-001",
                "medicine_id": "future-projection",
                "slot": 99,
            },
        ) as projector:
            sent = MedicationSafetyOutbox().flush(
                lambda _action, payload: calls.append(payload),
                capabilities={"medicationSafetyEvents": "v1"},
            )

        self.assertEqual(sent, 1)
        self.assertEqual(calls[0]["event"], legacy_payload)
        self.assertEqual(calls[0]["payloadDigest"], legacy_digest)
        projector.assert_not_called()
        with db.connect() as conn:
            persisted = conn.execute(
                """
                SELECT wire_payload_json, wire_payload_digest
                FROM medication_safety_outbox
                WHERE event_id='event-legacy-attempted-001'
                """
            ).fetchone()
        self.assertEqual(json.loads(persisted["wire_payload_json"]), legacy_payload)
        self.assertEqual(persisted["wire_payload_digest"], legacy_digest)

    def test_migration_preserves_expired_legacy_sending_lease_before_retry(self) -> None:
        self._replace_with_legacy_outbox_schema()
        legacy_payload = {
            "event_id": "event-legacy-sending-001",
            "medicine_id": "slot-13-ibuprofen",
            "slot": 13,
            "check_status": "BLOCKED",
            "dispense_status": "NOT_APPLICABLE",
        }
        legacy_digest = self._insert_pending_event(
            "event-legacy-sending-001",
            legacy_payload,
        )
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medication_safety_outbox
                SET status='sending', next_attempt_at='2000-01-01 00:00:00'
                WHERE event_id='event-legacy-sending-001'
                """
            )
        calls: list[dict[str, object]] = []

        with patch(
            "app.services.medication_safety_outbox._cloud_event_projection",
            return_value={
                "event_id": "event-legacy-sending-001",
                "medicine_id": "future-projection",
                "slot": 99,
            },
        ) as projector:
            sent = MedicationSafetyOutbox().flush(
                lambda _action, payload: calls.append(payload),
                capabilities={"medicationSafetyEvents": "v1"},
            )

        self.assertEqual(sent, 1)
        self.assertEqual(calls[0]["event"], legacy_payload)
        self.assertEqual(calls[0]["payloadDigest"], legacy_digest)
        projector.assert_not_called()

    def test_unknown_medicine_never_passes_through_or_materializes_on_retry(self) -> None:
        self._insert_pending_event(
            "event-unknown-medicine-001",
            {
                "event_id": "event-unknown-medicine-001",
                "medicine_id": "unknown-medicine",
                "slot": 99,
                "check_status": "BLOCKED",
                "dispense_status": "NOT_APPLICABLE",
            },
        )
        now = [datetime(2026, 8, 21, 12, 0, 0)]
        calls: list[dict[str, object]] = []
        outbox = MedicationSafetyOutbox(clock=lambda: now[0])

        with self.assertRaisesRegex(ValueError, "无法识别"):
            outbox.flush(
                lambda _action, payload: calls.append(payload),
                capabilities={"medicationSafetyEvents": "v1"},
            )

        now[0] += timedelta(seconds=6)
        with self.assertRaisesRegex(ValueError, "无法识别"):
            outbox.flush(
                lambda _action, payload: calls.append(payload),
                capabilities={"medicationSafetyEvents": "v1"},
            )

        self.assertEqual(calls, [])
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT status, attempts, wire_payload_json, wire_payload_digest
                FROM medication_safety_outbox
                WHERE event_id='event-unknown-medicine-001'
                """
            ).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["wire_payload_json"], "")
        self.assertEqual(row["wire_payload_digest"], "")

    def test_conflicting_medicine_slot_alias_fails_closed_before_send(self) -> None:
        self._insert_pending_event(
            "event-conflicting-slot-001",
            {
                "event_id": "event-conflicting-slot-001",
                "medicine_id": "slot-13-ibuprofen",
                "slot": "S04",
                "medicine": {
                    "id": "slot-13-ibuprofen",
                    "slot": 13,
                },
                "check_status": "BLOCKED",
                "dispense_status": "NOT_APPLICABLE",
            },
        )
        calls: list[dict[str, object]] = []

        with self.assertRaisesRegex(ValueError, "仓位别名"):
            MedicationSafetyOutbox().flush(
                lambda _action, payload: calls.append(payload),
                capabilities={"medicationSafetyEvents": "v1"},
            )

        self.assertEqual(calls, [])
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT status, attempts, wire_payload_json, wire_payload_digest
                FROM medication_safety_outbox
                WHERE event_id='event-conflicting-slot-001'
                """
            ).fetchone()
        self.assertEqual((row["status"], row["attempts"]), ("pending", 1))
        self.assertEqual((row["wire_payload_json"], row["wire_payload_digest"]), ("", ""))

    def test_missing_capability_keeps_event_pending_without_fallback(self) -> None:
        self._insert_pending_event()
        calls: list[object] = []

        sent = MedicationSafetyOutbox().flush(
            lambda action, payload: calls.append((action, payload)),
            capabilities={},
        )

        self.assertEqual(sent, 0)
        self.assertEqual(calls, [])
        self.assertEqual(MedicationSafetyOutbox().pending_count(), 1)

    def test_two_workers_atomically_claim_an_event_before_sending(self) -> None:
        self._insert_pending_event("event-concurrent-001")
        first_sender_entered = threading.Event()
        allow_sender_to_finish = threading.Event()
        calls: list[str] = []
        results: list[int] = []
        errors: list[BaseException] = []

        def sender(_action: str, payload: dict[str, object]) -> dict[str, object]:
            calls.append(str(payload["event"]["event_id"]))
            first_sender_entered.set()
            allow_sender_to_finish.wait(timeout=2)
            return {"ok": True}

        def run_worker() -> None:
            try:
                results.append(
                    MedicationSafetyOutbox().flush(
                        sender,
                        capabilities={"medicationSafetyEvents": "v1"},
                    )
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        first = threading.Thread(target=run_worker)
        second = threading.Thread(target=run_worker)
        first.start()
        self.assertTrue(first_sender_entered.wait(timeout=2))
        second.start()
        second.join(timeout=0.25)
        allow_sender_to_finish.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(calls, ["event-concurrent-001"])
        self.assertEqual(sorted(results), [0, 1])
        self.assertEqual(MedicationSafetyOutbox().pending_count(), 0)


if __name__ == "__main__":
    unittest.main()
