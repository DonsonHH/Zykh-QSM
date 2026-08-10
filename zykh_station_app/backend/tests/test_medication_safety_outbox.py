from __future__ import annotations

import hashlib
import json
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

    def _insert_pending_event(self, event_id: str = "event-001") -> str:
        payload = {
            "event_id": event_id,
            "check_id": "safety-check-001",
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
                          ?, ?, 'pending', 0, ?, ?, '')
                """,
                (event_id, payload_json, digest, db.now_text(), db.now_text()),
            )
        return digest

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
