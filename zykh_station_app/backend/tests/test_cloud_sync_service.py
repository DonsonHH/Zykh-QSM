from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.repositories.sync_repository import SyncRepository  # noqa: E402
from app.services.cloud_sync_service import CloudSyncError, CloudSyncWorker  # noqa: E402


class FakeCloudSyncWorker(CloudSyncWorker):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _call(self, action: str, data: dict[str, object]):
        self.calls.append((action, data))
        if action == "PING":
            return {"ok": True, "schemaVersion": 1}
        if action == "PULL_COMMANDS":
            return []
        return {"ok": True}


class FakeV2CloudSyncWorker(FakeCloudSyncWorker):
    def __init__(self, revision: str = "2.1") -> None:
        super().__init__()
        self.revision = revision

    def _call(self, action: str, data: dict[str, object]):
        self.calls.append((action, data))
        if action == "PING":
            return {"ok": True, "schemaVersion": 2, "schemaRevision": self.revision}
        if action == "PULL_COMMANDS":
            return []
        if action == "UPSERT_SNAPSHOT_BATCH":
            rows = data.get("rows", [])
            return {"ok": True, "count": len(rows), "ids": [f"id-{index}" for index, _ in enumerate(rows)]}
        return {"ok": True}


class AckFailureWorker(FakeCloudSyncWorker):
    def __init__(self) -> None:
        super().__init__()
        self.fail_ack = True
        self.executions = 0

    def _call(self, action: str, data: dict[str, object]):
        if action == "ACK_COMMAND" and self.fail_ack:
            raise CloudSyncError("temporary ack failure")
        return super()._call(action, data)

    def _execute_command(self, command_type: str, command: dict[str, object]) -> dict[str, object]:
        self.executions += 1
        return {"ok": True, "command_type": command_type}


class CloudSyncServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "cloud-sync.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_v1_cloud_uses_compatible_actions_and_marks_synced(self) -> None:
        worker = FakeCloudSyncWorker()
        count, _ = worker.run_once()

        actions = [action for action, _ in worker.calls]
        self.assertEqual(actions[0], "PULL_COMMANDS")
        self.assertIn("REPORT_DEVICE", actions)
        self.assertIn("UPLOAD_MEDICINES", actions)
        self.assertNotIn("UPLOAD_SNAPSHOT", actions)
        self.assertGreater(count, 0)
        self.assertEqual(SyncRepository().get_status().sync_status, "已同步")

    def test_completed_command_is_acknowledged_without_reexecution(self) -> None:
        worker = FakeCloudSyncWorker()
        now = db.now_text()
        worker._save_command("command-1", "AUDIO_BEEP", "done", {"ok": True}, now)

        worker._handle_command({"_id": "command-1", "type": "AUDIO_BEEP", "payload": {}})

        ack = [payload for action, payload in worker.calls if action == "ACK_COMMAND"]
        self.assertEqual(len(ack), 1)
        self.assertEqual(ack[0]["commandId"], "command-1")
        self.assertEqual(ack[0]["status"], "done")

    def test_v2_cloud_sends_bounded_batches_and_finalizes_each_collection(self) -> None:
        worker = FakeV2CloudSyncWorker()

        count, _ = worker.run_once()

        batches = [payload for action, payload in worker.calls if action == "UPSERT_SNAPSHOT_BATCH"]
        finalized = [payload["kind"] for action, payload in worker.calls if action == "FINALIZE_SNAPSHOT"]
        self.assertGreater(count, 0)
        self.assertEqual(set(finalized), {"medicines", "serviceUsers", "plans", "inquiries", "vitals", "records"})
        self.assertTrue(all(len(payload["rows"]) <= 20 for payload in batches))
        self.assertTrue(all(len(__import__("json").dumps(payload, ensure_ascii=False).encode("utf-8")) < 60_000 for payload in batches))

    def test_schema_revision_change_forces_full_snapshot_resync(self) -> None:
        first = FakeV2CloudSyncWorker("2.1")
        first.run_once()
        second = FakeV2CloudSyncWorker("2.2")

        count, _ = second.run_once()

        self.assertGreater(count, 0)
        self.assertTrue(any(action == "UPSERT_SNAPSHOT_BATCH" for action, _ in second.calls))

    def test_ack_failure_never_reexecutes_completed_hardware_command(self) -> None:
        worker = AckFailureWorker()
        command = {"_id": "open-1", "type": "OPEN_CABINET", "payload": {}}

        with self.assertRaises(CloudSyncError):
            worker._handle_command(command)

        self.assertEqual(worker.executions, 1)
        self.assertEqual(worker._command_history("open-1")["status"], "done_unacked")

        worker.fail_ack = False
        worker._flush_unacked_commands()
        worker._handle_command(command)

        self.assertEqual(worker.executions, 1)
        self.assertEqual(worker._command_history("open-1")["status"], "done")

    def test_restart_marks_inflight_command_ambiguous_instead_of_retrying(self) -> None:
        worker = FakeCloudSyncWorker()
        worker._save_command("open-2", "OPEN_CABINET", "running", {}, db.now_text())

        worker._recover_interrupted_commands()

        history = worker._command_history("open-2")
        self.assertEqual(history["status"], "failed_unacked")
        self.assertIn("禁止自动重试", history["result_json"])

    def test_recent_remote_open_blocks_only_the_same_slot(self) -> None:
        worker = FakeCloudSyncWorker()
        worker._save_command("open-8", "OPEN_CABINET", "done", {"ok": True, "slot": 8}, db.now_text())

        self.assertTrue(worker._recent_remote_open(8))
        self.assertFalse(worker._recent_remote_open(9))


if __name__ == "__main__":
    unittest.main()
