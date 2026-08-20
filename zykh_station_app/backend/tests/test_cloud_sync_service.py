from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.config import Settings, settings  # noqa: E402
from app.repositories.medicine_repository import MedicineRepository  # noqa: E402
from app.repositories.sync_repository import SyncRepository  # noqa: E402
from app.schemas.sync import SyncStatus  # noqa: E402
from app.repositories.vitals_repository import VitalsRecord, VitalsRepository  # noqa: E402
from app.services.cloud_sync_service import CloudSyncError, CloudSyncWorker  # noqa: E402
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402
from app.services.qsm_client import QsmClient  # noqa: E402


class FakeCloudSyncWorker(CloudSyncWorker):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _call(self, action: str, data: dict[str, object]):
        self.calls.append((action, data))
        if action == "PING":
            return {
                "ok": True,
                "schemaVersion": 2,
                "schemaRevision": "3.0-three-box-library",
                "capabilities": {"medicineStorageBoxes": "v1"},
            }
        if action == "PULL_COMMANDS":
            return []
        return {"ok": True}


class LegacyCloudSyncWorker(FakeCloudSyncWorker):
    def _call(self, action: str, data: dict[str, object]):
        self.calls.append((action, data))
        if action == "PING":
            return {"ok": True, "schemaVersion": 1}
        return {"ok": True}


class FakeV2CloudSyncWorker(FakeCloudSyncWorker):
    def __init__(self, revision: str = "3.0-three-box-library") -> None:
        super().__init__()
        self.revision = revision

    def _call(self, action: str, data: dict[str, object]):
        self.calls.append((action, data))
        if action == "PING":
            return {
                "ok": True,
                "schemaVersion": 2,
                "schemaRevision": self.revision,
                "capabilities": {"medicineStorageBoxes": "v1"},
            }
        if action == "PULL_COMMANDS":
            return []
        if action == "UPSERT_SNAPSHOT_BATCH":
            rows = data.get("rows", [])
            return {"ok": True, "count": len(rows), "ids": [f"id-{index}" for index, _ in enumerate(rows)]}
        return {"ok": True}


class FakeSafetyEventCloudSyncWorker(FakeV2CloudSyncWorker):
    def _call(self, action: str, data: dict[str, object]):
        self.calls.append((action, data))
        if action == "PING":
            return {
                "ok": True,
                "schemaVersion": 2,
                "schemaRevision": "3.0-three-box-library",
                "capabilities": {
                    "medicineStorageBoxes": "v1",
                    "medicationSafetyEvents": "v1",
                },
            }
        if action == "PULL_COMMANDS":
            return []
        if action == "UPSERT_SNAPSHOT_BATCH":
            rows = data.get("rows", [])
            return {
                "ok": True,
                "count": len(rows),
                "ids": [f"id-{index}" for index, _ in enumerate(rows)],
            }
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


class MedicineRoundTripWorker(FakeV2CloudSyncWorker):
    def __init__(self, command: dict[str, object]) -> None:
        super().__init__()
        self.command = command
        self.delivered = False

    def _call(self, action: str, data: dict[str, object]):
        self.calls.append((action, data))
        if action == "PULL_COMMANDS":
            if self.delivered:
                return []
            self.delivered = True
            return [self.command]
        if action == "PING":
            return {
                "ok": True,
                "schemaVersion": 2,
                "schemaRevision": self.revision,
                "capabilities": {"medicineStorageBoxes": "v1"},
            }
        if action == "UPSERT_SNAPSHOT_BATCH":
            rows = data.get("rows", [])
            return {
                "ok": True,
                "count": len(rows),
                "ids": [f"id-{data.get('kind')}-{index}" for index, _ in enumerate(rows)],
            }
        return {"ok": True}


class PauseAfterPullWorker(FakeCloudSyncWorker):
    def __init__(self) -> None:
        super().__init__()
        self.handled_commands: list[dict[str, object]] = []

    def _call(self, action: str, data: dict[str, object]):
        self.calls.append((action, data))
        if action == "PING":
            return {
                "ok": True,
                "schemaVersion": 2,
                "schemaRevision": "3.0-three-box-library",
                "capabilities": {"medicineStorageBoxes": "v1"},
            }
        if action == "PULL_COMMANDS":
            db.set_setting("network_mode", "local")
            return [
                {
                    "id": "must-not-run",
                    "type": "AUDIO_BEEP",
                    "payload": {},
                }
            ]
        return {"ok": True}

    def _handle_command(self, command: dict[str, object]) -> None:
        self.handled_commands.append(command)


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

    def test_remote_cabinet_is_disabled_by_default(self) -> None:
        self.assertFalse(Settings().cloud_remote_cabinet_enabled)

    def test_legacy_cloud_contract_is_rejected_before_pull_or_snapshot(self) -> None:
        worker = LegacyCloudSyncWorker()

        with self.assertRaisesRegex(CloudSyncError, "3.0-three-box-library"):
            worker.run_once()

        self.assertEqual([action for action, _ in worker.calls], ["PING"])

    def test_wrong_storage_box_capability_is_rejected_before_pull_or_snapshot(self) -> None:
        worker = FakeCloudSyncWorker()

        def incompatible_ping(action: str, data: dict[str, object]):
            worker.calls.append((action, data))
            if action == "PING":
                return {
                    "ok": True,
                    "schemaVersion": 2,
                    "schemaRevision": "3.0-three-box-library",
                    "capabilities": {"medicineStorageBoxes": "v2"},
                }
            return {"ok": True}

        with patch.object(worker, "_call", side_effect=incompatible_ping):
            with self.assertRaisesRegex(CloudSyncError, "medicineStorageBoxes=v1"):
                worker.run_once()

        self.assertEqual([action for action, _ in worker.calls], ["PING"])

    def test_each_sync_cycle_rechecks_contract_before_pulling_commands(self) -> None:
        worker = FakeCloudSyncWorker()
        ping_count = 0

        def changing_contract(action: str, data: dict[str, object]):
            nonlocal ping_count
            worker.calls.append((action, data))
            if action == "PING":
                ping_count += 1
                if ping_count == 1:
                    return {
                        "ok": True,
                        "schemaVersion": 2,
                        "schemaRevision": "3.0-three-box-library",
                        "capabilities": {"medicineStorageBoxes": "v1"},
                    }
                return {
                    "ok": True,
                    "schemaVersion": 2,
                    "schemaRevision": "2.9-stable-medicine-identity",
                    "capabilities": {"medicineStorageBoxes": "v1"},
                }
            if action == "PULL_COMMANDS":
                return []
            if action == "UPSERT_SNAPSHOT_BATCH":
                rows = data.get("rows", [])
                return {"ok": True, "count": len(rows), "ids": []}
            return {"ok": True}

        with patch.object(worker, "_call", side_effect=changing_contract):
            worker.run_once()
            second_cycle_start = len(worker.calls)
            with self.assertRaisesRegex(CloudSyncError, "3.0-three-box-library"):
                worker.run_once()

        self.assertEqual(
            [action for action, _ in worker.calls[second_cycle_start:]],
            ["PING"],
        )

    def test_local_display_mode_pauses_miniprogram_realtime_calls(self) -> None:
        db.set_setting("network_mode", "local")
        worker = FakeCloudSyncWorker()

        with self.assertRaisesRegex(CloudSyncError, "本地模式"):
            worker.run_once()

        self.assertEqual(worker.calls, [])

    def test_pairing_issue_port_is_narrow_and_fails_closed_without_cloud_credentials(self) -> None:
        worker = FakeCloudSyncWorker()
        payload = {
            "codeHash": "a" * 64,
            "serviceUserScopes": ["wang-nainai"],
            "ttlSeconds": 600,
        }
        configured = replace(
            settings,
            cloud_sync_endpoint="https://cloud.example.test/pairing",
            cloud_sync_device_secret="device-test-secret",
        )
        with patch("app.services.cloud_sync_service.settings", configured):
            worker.issue_pairing_code_hash(payload)

        self.assertEqual(
            worker.calls,
            [("PING", {}), ("ISSUE_DEVICE_PAIRING_CODE", payload)],
        )

        for missing in (
            replace(configured, cloud_sync_endpoint=""),
            replace(configured, cloud_sync_device_secret="", cloud_sync_device_secret_file=self.db_path / "missing"),
        ):
            with self.subTest(missing=missing):
                with patch("app.services.cloud_sync_service.settings", missing):
                    with self.assertRaises(CloudSyncError):
                        worker.issue_pairing_code_hash(payload)

        self.assertEqual(
            worker.calls,
            [("PING", {}), ("ISSUE_DEVICE_PAIRING_CODE", payload)],
        )

        legacy_worker = LegacyCloudSyncWorker()
        with patch("app.services.cloud_sync_service.settings", configured):
            with self.assertRaisesRegex(CloudSyncError, "3.0-three-box-library"):
                legacy_worker.issue_pairing_code_hash(payload)
        self.assertEqual(legacy_worker.calls, [("PING", {})])

    def test_pairing_stops_if_local_mode_is_selected_after_contract_ping(self) -> None:
        worker = FakeCloudSyncWorker()
        payload = {
            "codeHash": "b" * 64,
            "serviceUserScopes": ["wang-nainai"],
            "ttlSeconds": 600,
        }
        configured = replace(
            settings,
            cloud_sync_endpoint="https://cloud.example.test/pairing",
            cloud_sync_device_secret="device-test-secret",
        )

        def pause_after_ping(action: str, data: dict[str, object]):
            worker.calls.append((action, data))
            if action == "PING":
                db.set_setting("network_mode", "local")
                return {
                    "ok": True,
                    "schemaVersion": 2,
                    "schemaRevision": "3.0-three-box-library",
                    "capabilities": {"medicineStorageBoxes": "v1"},
                }
            return {"ok": True}

        with (
            patch("app.services.cloud_sync_service.settings", configured),
            patch.object(worker, "_call", side_effect=pause_after_ping),
        ):
            with self.assertRaisesRegex(CloudSyncError, "本地模式"):
                worker.issue_pairing_code_hash(payload)

        self.assertEqual(worker.calls, [("PING", {})])

    def test_switching_local_after_pull_stops_the_remaining_sync_cycle(self) -> None:
        worker = PauseAfterPullWorker()

        with self.assertRaisesRegex(CloudSyncError, "本地模式"):
            worker.run_once()

        self.assertEqual(
            [action for action, _ in worker.calls],
            ["PING", "PULL_COMMANDS"],
        )
        self.assertEqual(worker.handled_commands, [])

    def test_local_display_mode_hides_stale_cloud_connection_error(self) -> None:
        db.set_setting("network_mode", "local")
        worker = FakeCloudSyncWorker()
        worker._connected = True
        worker._last_error = "previous cloud timeout"

        status = worker.runtime_status(
            SyncStatus(
                sync_status="待同步",
                pending_count=2,
                last_sync_at="",
                network_mode="家庭网络",
            )
        )

        self.assertFalse(status.connected)
        self.assertEqual(status.last_error, "")

    def test_completed_command_is_acknowledged_without_reexecution(self) -> None:
        worker = FakeCloudSyncWorker()
        now = db.now_text()
        worker._save_command("command-1", "AUDIO_BEEP", "done", {"ok": True}, now)

        worker._handle_command({"_id": "command-1", "type": "AUDIO_BEEP", "payload": {}})

        ack = [payload for action, payload in worker.calls if action == "ACK_COMMAND"]
        self.assertEqual(len(ack), 1)
        self.assertEqual(ack[0]["commandId"], "command-1")
        self.assertEqual(ack[0]["status"], "done")

    def test_legacy_completed_remote_open_is_reclassified_as_failed_when_redelivered(self) -> None:
        worker = FakeCloudSyncWorker()
        now = db.now_text()
        worker._save_command("legacy-open-done", "OPEN_CABINET", "done", {"ok": True}, now)

        with patch.object(QsmClient, "dispense") as qsm_dispense:
            worker._handle_command(
                {
                    "_id": "legacy-open-done",
                    "type": "OPEN_CABINET",
                    "payload": {"slot": 8, "remote_confirmed": True},
                }
            )

        acknowledgements = [payload for action, payload in worker.calls if action == "ACK_COMMAND"]
        self.assertEqual(len(acknowledgements), 1)
        self.assertEqual(acknowledgements[0]["status"], "failed")
        self.assertIn("远程开柜已禁用", acknowledgements[0]["result"]["error"])
        self.assertEqual(worker._command_history("legacy-open-done")["status"], "failed")
        qsm_dispense.assert_not_called()

    def test_legacy_unacked_remote_open_is_flushed_as_failed(self) -> None:
        worker = FakeCloudSyncWorker()
        worker._save_command(
            "legacy-open-unacked",
            "OPEN_CABINET",
            "done_unacked",
            {"ok": True, "slot": 8},
            db.now_text(),
        )

        with patch.object(QsmClient, "dispense") as qsm_dispense:
            worker._flush_unacked_commands()

        acknowledgements = [payload for action, payload in worker.calls if action == "ACK_COMMAND"]
        self.assertEqual(len(acknowledgements), 1)
        self.assertEqual(acknowledgements[0]["status"], "failed")
        self.assertIn("远程开柜已禁用", acknowledgements[0]["result"]["error"])
        self.assertEqual(worker._command_history("legacy-open-unacked")["status"], "failed")
        qsm_dispense.assert_not_called()

    def test_legacy_remote_open_is_locally_reclassified_before_failed_ack_retry(self) -> None:
        worker = AckFailureWorker()
        worker._save_command(
            "legacy-open-ack-retry",
            "OPEN_CABINET",
            "done_unacked",
            {"ok": True, "slot": 8},
            db.now_text(),
        )

        with self.assertRaises(CloudSyncError):
            worker._flush_unacked_commands()

        history = worker._command_history("legacy-open-ack-retry")
        self.assertEqual(history["status"], "failed_unacked")
        self.assertIn("远程开柜已禁用", history["result_json"])

    def test_v2_cloud_never_finalizes_truncated_inquiry_or_vitals_history(self) -> None:
        worker = FakeV2CloudSyncWorker()

        count, _ = worker.run_once()

        batches = [payload for action, payload in worker.calls if action == "UPSERT_SNAPSHOT_BATCH"]
        finalized = [payload["kind"] for action, payload in worker.calls if action == "FINALIZE_SNAPSHOT"]
        self.assertGreater(count, 0)
        self.assertEqual(set(finalized), {"medicines", "serviceUsers", "plans", "records"})
        self.assertNotIn("inquiries", finalized)
        self.assertNotIn("vitals", finalized)
        self.assertTrue(all(len(payload["rows"]) <= 20 for payload in batches))
        self.assertTrue(all(len(__import__("json").dumps(payload, ensure_ascii=False).encode("utf-8")) < 60_000 for payload in batches))

    def test_v2_snapshot_projects_active_people_and_archived_tombstones_together(self) -> None:
        with db.connect() as conn:
            conn.executemany(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  persona_generation, archived
                ) VALUES (?, ?, ?, '', '', '', '已归档', 'legacy-family-demo-v6', 1)
                """,
                [
                    ("legacy-zhang-dynamic", "张三", 70),
                    ("legacy-li-dynamic", "李四", 8),
                ],
            )
        worker = FakeV2CloudSyncWorker()

        worker.run_once()

        rows = [
            row
            for action, payload in worker.calls
            if action == "UPSERT_SNAPSHOT_BATCH" and payload["kind"] == "serviceUsers"
            for row in payload["rows"]
        ]
        projected = {
            row["id"]: (row["name"], row["persona_generation"], row["archived"])
            for row in rows
            if row["id"] in {
                "wang-nainai",
                "li-yeye",
                "legacy-zhang-dynamic",
                "legacy-li-dynamic",
            }
        }
        self.assertEqual(
            projected,
            {
                "wang-nainai": ("王奶奶", "senior-demo-v1", False),
                "li-yeye": ("李爷爷", "senior-demo-v1", False),
                "legacy-zhang-dynamic": ("张三", "legacy-family-demo-v6", True),
                "legacy-li-dynamic": ("李四", "legacy-family-demo-v6", True),
            },
        )
        device_summary = next(
            payload["syncSummary"]
            for action, payload in worker.calls
            if action == "REPORT_DEVICE"
        )
        self.assertEqual(
            [row["id"] for row in device_summary["serviceUsers"]],
            ["li-yeye", "wang-nainai"],
        )
        self.assertIs(device_summary["serviceUsersSnapshotComplete"], True)
        self.assertTrue(
            all(row["persona_generation"] == "senior-demo-v1" for row in device_summary["serviceUsers"])
        )

    def test_v2_capability_flushes_safety_outbox_outside_snapshot_finalize(self) -> None:
        payload = {
            "event_id": "event-sync-001",
            "check_id": "safety-check-sync-001",
            "medicine_id": "slot-01-fufang-ganmaoling",
            "check_status": "BLOCKED",
        }
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = __import__("hashlib").sha256(payload_json.encode("utf-8")).hexdigest()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO medication_safety_outbox(
                  event_id, aggregate_id, event_type, payload_json, payload_digest,
                  status, attempts, next_attempt_at, created_at, sent_at
                ) VALUES ('event-sync-001', 'safety-check-sync-001',
                          'MEDICATION_SAFETY_EVENT_RECORDED', ?, ?,
                          'pending', 0, ?, ?, '')
                """,
                (payload_json, digest, db.now_text(), db.now_text()),
            )
        worker = FakeSafetyEventCloudSyncWorker()

        worker.run_once()

        reports = [data for action, data in worker.calls if action == "REPORT_MEDICATION_SAFETY_EVENT"]
        finalized = [data["kind"] for action, data in worker.calls if action == "FINALIZE_SNAPSHOT"]
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["payloadDigest"], digest)
        self.assertNotIn("medicationSafetyEvents", finalized)
        with db.connect() as conn:
            status = conn.execute(
                "SELECT status FROM medication_safety_outbox WHERE event_id='event-sync-001'"
            ).fetchone()["status"]
        self.assertEqual(status, "sent")

    def test_sync_cycle_uses_its_validated_contract_snapshot_if_shared_probe_state_changes(self) -> None:
        payload = {
            "event_id": "event-contract-snapshot-001",
            "check_id": "safety-check-contract-snapshot-001",
            "medicine_id": "slot-01-fufang-ganmaoling",
            "check_status": "BLOCKED",
        }
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = __import__("hashlib").sha256(payload_json.encode("utf-8")).hexdigest()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO medication_safety_outbox(
                  event_id, aggregate_id, event_type, payload_json, payload_digest,
                  status, attempts, next_attempt_at, created_at, sent_at
                ) VALUES (?, ?, 'MEDICATION_SAFETY_EVENT_RECORDED', ?, ?,
                          'pending', 0, ?, ?, '')
                """,
                (
                    payload["event_id"],
                    payload["check_id"],
                    payload_json,
                    digest,
                    db.now_text(),
                    db.now_text(),
                ),
            )
        worker = FakeSafetyEventCloudSyncWorker()
        original_call = worker._call

        def mutate_shared_probe_after_report(action: str, data: dict[str, object]):
            result = original_call(action, data)
            if action == "REPORT_DEVICE":
                worker._cloud_schema_version = 1
                worker._cloud_schema_revision = "legacy-concurrent-probe"
                worker._cloud_capabilities = {}
            return result

        with patch.object(worker, "_call", side_effect=mutate_shared_probe_after_report):
            worker.run_once()

        actions = [action for action, _ in worker.calls]
        self.assertIn("REPORT_MEDICATION_SAFETY_EVENT", actions)
        self.assertIn("UPSERT_SNAPSHOT_BATCH", actions)
        self.assertNotIn("UPLOAD_MEDICINES", actions)

    def test_wrong_three_box_schema_revision_fails_closed(self) -> None:
        worker = FakeV2CloudSyncWorker("2.9-stable-medicine-identity")

        with self.assertRaisesRegex(CloudSyncError, "3.0-three-box-library"):
            worker.run_once()

        self.assertEqual([action for action, _ in worker.calls], ["PING"])

    def test_detects_current_three_box_cloud_contract_without_local_cloud_deployment(self) -> None:
        worker = CloudSyncWorker()
        with patch.object(
            worker,
            "_request",
            return_value={
                "ok": True,
                "schemaVersion": 2,
                "schemaRevision": "3.0-three-box-library",
                "capabilities": {
                    "medicineStorageBoxes": "v1",
                    "explicitInventoryState": "v1",
                },
            },
        ):
            version = worker._detect_schema_version()

        self.assertEqual(version, 2)
        self.assertEqual(worker._cloud_schema_revision, "3.0-three-box-library")
        self.assertEqual(worker._cloud_capabilities["medicineStorageBoxes"], "v1")

    def test_snapshot_publishes_current_inquiry_sessions_for_miniprogram_history(self) -> None:
        session = SimpleNamespace(
            session_id="session-current",
            user_id="user-zhangsan",
            user_name="张三",
            extracted_information=SimpleNamespace(symptoms_text="轻微头晕"),
            title="张三头晕问询",
            created_at="2026-07-19 08:00:00",
            updated_at="2026-07-19 08:03:00",
            model_dump=lambda mode: {
                "session_id": "session-current",
                "user_id": "user-zhangsan",
                "user_name": "张三",
                "title": "张三头晕问询",
                "risk_level": "medium",
                "primary_candidate": {
                    "id": "slot-01-test",
                    "cabinet_id": 1,
                    "cabinet_label": "仅本地分类柜",
                },
                "treatment_options": [
                    {
                        "medicines": [
                            {
                                "id": "slot-01-test",
                                "cabinet_id": 1,
                                "cabinet_label": "仅本地分类柜",
                                "cabinet_description": "仅本地展示",
                            }
                        ]
                    }
                ],
                "action_items": [
                    {
                        "medicine_id": "slot-01-test",
                        "cabinet_id": 1,
                        "cabinet_label": "仅本地分类柜",
                    }
                ],
                "messages": [{"role": "user", "content": "有些头晕"}],
                "created_at": "2026-07-19 08:00:00",
                "updated_at": "2026-07-19 08:03:00",
            },
        )
        legacy_result = SimpleNamespace(
            inquiry_id="result-local-cabinet-projection",
            created_at="2026-07-19 07:00:00",
            model_dump=lambda mode: {
                "inquiry_id": "result-local-cabinet-projection",
                "candidate_medicines": [
                    {
                        "id": "slot-02-test",
                        "cabinet_id": 2,
                        "cabinet_label": "仅本地分类柜",
                    }
                ],
                "created_at": "2026-07-19 07:00:00",
            },
        )
        with patch("app.services.cloud_sync_service.InquiryRepository") as repository_class:
            repository_class.return_value.list_sessions.return_value = [session]
            repository_class.return_value.list_records.return_value = [legacy_result]

            snapshot = CloudSyncWorker._build_snapshot()

        row = next(
            item for item in snapshot["inquiries"] if item["inquiry_id"] == "session-current"
        )
        self.assertEqual(row["inquiry_id"], "session-current")
        self.assertEqual(row["target_user_name"], "张三")
        self.assertEqual(row["symptoms_summary"], "轻微头晕")
        self.assertEqual(row["updatedAt"], "2026-07-19 08:03:00")
        self.assertNotIn("cabinet_id", json.dumps(row, ensure_ascii=False))
        self.assertNotIn("cabinet_label", json.dumps(row, ensure_ascii=False))
        self.assertNotIn("cabinet_description", json.dumps(row, ensure_ascii=False))
        result_row = next(
            item
            for item in snapshot["inquiries"]
            if item["inquiry_id"] == "result-local-cabinet-projection"
        )
        self.assertNotIn("cabinet_id", json.dumps(result_row, ensure_ascii=False))
        self.assertNotIn("cabinet_label", json.dumps(result_row, ensure_ascii=False))
        self.assertNotIn("cabinet_id", json.dumps(snapshot["medicines"], ensure_ascii=False))
        self.assertNotIn("cabinet_label", json.dumps(snapshot["medicines"], ensure_ascii=False))

    def test_sync_summary_excludes_full_dialogue_messages(self) -> None:
        summary = CloudSyncWorker._sync_summary(
            {
                "medicines": [],
                "serviceUsers": [],
                "plans": [],
                "inquiries": [
                    {
                        "session_id": "session-summary",
                        "persona_generation": "persona-summary-v1",
                        "target_user_name": "张三",
                        "title": "头晕问询",
                        "reply": "建议先休息并观察。",
                        "messages": [
                            {"role": "user", "content": "有些头晕"},
                            {"role": "assistant", "content": "持续多久了？"},
                        ],
                        "created_at": "2026-07-19 08:00:00",
                        "updated_at": "2026-07-19 08:03:00",
                    }
                ],
                "vitals": [],
                "records": [],
            }
        )

        inquiry = summary["recentInquiries"][0]
        self.assertNotIn("messages", inquiry)
        self.assertEqual(inquiry["messageCount"], 2)
        self.assertEqual(inquiry["reply"], "建议先休息并观察。")
        self.assertEqual(inquiry["persona_generation"], "persona-summary-v1")

    def test_medicine_patch_updates_only_explicit_fields_and_preserves_explicit_depleted(self) -> None:
        repository = MedicineRepository()
        original = repository.get_by_hardware_slot(1)
        self.assertIsNotNone(original)

        result = CloudSyncWorker._upsert_medicine(
            {
                "slot": 1,
                "operation": "patch",
                "patch": {
                    "name": "一号仓演示药",
                    "quantity": 0,
                    "inventoryState": "DEPLETED",
                    "spec": "0.3克×10袋",
                    "traceCode": "TRACE-001",
                    "lowStockLine": 0,
                },
            }
        )

        updated = repository.get_by_hardware_slot(1)
        self.assertEqual(result["medicine"]["hardware_slot"], 1)
        self.assertEqual(updated.name, "一号仓演示药")
        self.assertEqual(updated.stock, 0)
        self.assertEqual(updated.spec, "0.3克×10袋")
        self.assertEqual(updated.trace_code, "TRACE-001")
        self.assertEqual(updated.low_stock_line, 0)
        self.assertEqual(updated.barcode, original.barcode)
        self.assertEqual(updated.category, original.category)
        self.assertEqual(updated.unit, original.unit)
        self.assertEqual(updated.expire_date, original.expire_date)

    def test_medicine_patch_rejects_zero_quantity_without_explicit_depleted(self) -> None:
        repository = MedicineRepository()
        seeded = repository.get_by_hardware_slot(1)
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET stock=1, inventory_state='AVAILABLE', inventory_revision=5
                WHERE id=?
                """,
                (seeded.id,),
            )
        original = repository.get_by_hardware_slot(1)

        with self.assertRaisesRegex(CloudSyncError, "明确 DEPLETED"):
            CloudSyncWorker._upsert_medicine(
                {
                    "operation": "patch",
                    "hardware_slot": 1,
                    "patch": {"quantity": 0},
                }
            )

        unchanged = repository.get_by_hardware_slot(1)
        self.assertEqual(unchanged.inventory_state, original.inventory_state)
        self.assertEqual(unchanged.stock, original.stock)
        self.assertEqual(unchanged.inventory_revision, original.inventory_revision)

    def test_medicine_patch_maps_explicit_stocked_to_available_flag(self) -> None:
        repository = MedicineRepository()
        original = repository.get_by_hardware_slot(1)
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET stock=0, inventory_state='DEPLETED', inventory_revision=11
                WHERE id=?
                """,
                (original.id,),
            )

        result = CloudSyncWorker._upsert_medicine(
            {
                "operation": "patch",
                "hardware_slot": 1,
                "patch": {
                    "inventoryState": "STOCKED",
                    "inventory_state": "STOCKED",
                },
            }
        )

        updated = repository.get_by_hardware_slot(1)
        self.assertEqual(result["medicine"]["inventory_state"], "AVAILABLE")
        self.assertEqual(updated.inventory_state, "AVAILABLE")
        self.assertEqual(updated.stock, 1)
        self.assertEqual(updated.inventory_revision, 12)

    def test_medicine_patch_maps_depleted_and_unknown_without_implicit_zero(self) -> None:
        repository = MedicineRepository()
        original = repository.get_by_hardware_slot(1)
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET stock=1, inventory_state='AVAILABLE', inventory_revision=20
                WHERE id=?
                """,
                (original.id,),
            )

        CloudSyncWorker._upsert_medicine(
            {
                "operation": "patch",
                "hardware_slot": 1,
                "patch": {"inventoryState": "DEPLETED"},
            }
        )
        depleted = repository.get_by_hardware_slot(1)
        self.assertEqual(depleted.inventory_state, "DEPLETED")
        self.assertEqual(depleted.stock, 0)
        self.assertEqual(depleted.inventory_revision, 21)

        CloudSyncWorker._upsert_medicine(
            {
                "operation": "patch",
                "hardware_slot": 1,
                "patch": {"inventory_state": "UNKNOWN"},
            }
        )
        unknown = repository.get_by_hardware_slot(1)
        self.assertEqual(unknown.inventory_state, "UNKNOWN")
        self.assertEqual(unknown.stock, 1)
        self.assertEqual(unknown.inventory_revision, 22)

    def test_medicine_patch_rejects_inventory_state_quantity_conflicts(self) -> None:
        conflicting_payloads = (
            {"inventoryState": "STOCKED", "quantity": 0},
            {"inventoryState": "DEPLETED", "quantity": 1},
            {"inventoryState": "UNKNOWN", "quantity": 0},
        )
        for patch_payload in conflicting_payloads:
            with self.subTest(patch_payload=patch_payload):
                with self.assertRaisesRegex(CloudSyncError, "状态与 quantity 存在冲突"):
                    CloudSyncWorker._upsert_medicine(
                        {
                            "operation": "patch",
                            "hardware_slot": 1,
                            "patch": patch_payload,
                        }
                    )

    def test_medicine_patch_rejects_conflicting_outer_and_inner_inventory_state(self) -> None:
        with self.assertRaisesRegex(CloudSyncError, "库存状态存在冲突值"):
            CloudSyncWorker._upsert_medicine(
                {
                    "operation": "patch",
                    "hardware_slot": 1,
                    "inventoryState": "STOCKED",
                    "patch": {
                        "inventory_state": "DEPLETED",
                        "quantity": 0,
                    },
                }
            )

    def test_identity_patch_invalidates_reviewed_guidance_and_safety_facts(self) -> None:
        repository = MedicineRepository()
        original = repository.get_by_hardware_slot(13)
        repository.update(
            original.id,
            {
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "测试药师",
                "safety_reviewed_at": "2026-08-08 10:00:00",
            },
        )
        original = repository.get_by_id(original.id)
        self.assertEqual(original.safety_review_status, "reviewed")
        self.assertEqual(original.active_ingredients, ["布洛芬"])

        CloudSyncWorker._upsert_medicine(
            {
                "operation": "patch",
                "hardware_slot": 3,
                "patch": {"spec": "身份已变化的新规格"},
            }
        )

        updated = repository.get_by_hardware_slot(13)
        self.assertFalse(updated.package_verified)
        self.assertEqual(updated.guidance_source, "pending")
        self.assertEqual(updated.indications, "")
        self.assertEqual(updated.dosage, "")
        self.assertEqual(updated.contraindications, [])
        self.assertEqual(updated.aliases, [])
        self.assertEqual(updated.active_ingredients, [])
        self.assertEqual(updated.structured_contraindications, [])
        self.assertEqual(updated.safety_review_status, "draft")
        self.assertEqual(updated.safety_reviewed_by, "")
        self.assertEqual(updated.safety_reviewed_at, "")

    def test_remote_medicine_patch_cannot_mark_safety_facts_as_reviewed(self) -> None:
        with self.assertRaisesRegex(CloudSyncError, "不能远程标记为已审核"):
            CloudSyncWorker._upsert_medicine(
                {
                    "operation": "patch",
                    "hardware_slot": 13,
                    "patch": {
                        "quantity": 1,
                        "safety_review_status": "reviewed",
                        "safety_reviewed_by": "远程自称药师",
                        "safety_reviewed_at": "2026-08-08 14:00:00",
                    },
                }
            )

    def test_remote_safety_facts_are_persisted_only_as_an_unreviewed_draft(self) -> None:
        CloudSyncWorker._upsert_medicine(
            {
                "operation": "patch",
                "hardware_slot": 3,
                "patch": {
                    "aliases": ["远程草稿别名"],
                    "active_ingredients": ["远程草稿成分"],
                    "structured_contraindications": [
                        {
                            "concept_code": "ingredient_allergy",
                            "display_text": "远程草稿辅料过敏者禁用",
                        }
                    ],
                    "safety_review_status": "draft",
                },
            }
        )

        repository = MedicineRepository()
        updated = repository.get_by_hardware_slot(13)
        self.assertEqual(updated.aliases, ["远程草稿别名"])
        self.assertEqual(updated.active_ingredients, ["远程草稿成分"])
        self.assertEqual(
            updated.structured_contraindications,
            [
                {
                    "concept_code": "ingredient_allergy",
                    "display_text": "远程草稿辅料过敏者禁用",
                }
            ],
        )
        self.assertEqual(updated.safety_review_status, "draft")
        self.assertEqual(updated.safety_reviewed_by, "")
        self.assertEqual(updated.safety_reviewed_at, "")
        self.assertNotIn(
            updated.id,
            {item.id for item in MedicineKnowledgeRepository(repository).safe_candidate_pool("")},
        )

    def test_identity_patch_keeps_explicit_new_draft_facts_and_clears_omitted_old_facts(self) -> None:
        CloudSyncWorker._upsert_medicine(
            {
                "operation": "patch",
                "hardware_slot": 3,
                "patch": {
                    "spec": "新身份规格",
                    "aliases": ["新身份草稿别名"],
                    "active_ingredients": ["新身份草稿成分"],
                    "structured_contraindications": [
                        {
                            "concept_code": "ingredient_allergy",
                            "display_text": "新身份草稿辅料过敏者禁用",
                        }
                    ],
                    "safety_review_status": "draft",
                },
            }
        )

        updated = MedicineRepository().get_by_hardware_slot(13)
        self.assertEqual(updated.spec, "新身份规格")
        self.assertEqual(updated.aliases, ["新身份草稿别名"])
        self.assertEqual(updated.active_ingredients, ["新身份草稿成分"])
        self.assertEqual(
            updated.structured_contraindications,
            [
                {
                    "concept_code": "ingredient_allergy",
                    "display_text": "新身份草稿辅料过敏者禁用",
                }
            ],
        )
        self.assertEqual(updated.indications, "")
        self.assertEqual(updated.dosage, "")
        self.assertEqual(updated.contraindications, [])
        self.assertEqual(updated.safety_review_status, "draft")
        self.assertFalse(updated.package_verified)

    def test_empty_fixed_slot_rejects_remote_creation_with_dynamic_identity(self) -> None:
        MedicineRepository().list_all()
        with db.connect() as conn:
            conn.execute("DELETE FROM medicines WHERE hardware_slot=23")

        with self.assertRaisesRegex(CloudSyncError, "本地固定药品.*缺失"):
            CloudSyncWorker._upsert_medicine(
                {
                    "operation": "upsert",
                    "hardware_slot": 23,
                    "name": "云端新建草稿药品",
                    "manufacturer": "草稿厂家",
                    "barcode": "draft-create-barcode",
                    "spec": "草稿规格",
                    "expireDate": "2030-12",
                    "inventoryState": "UNKNOWN",
                    "aliases": ["新建草稿别名"],
                    "active_ingredients": ["新建草稿成分"],
                    "structured_contraindications": [
                        {
                            "concept_code": "ingredient_allergy",
                            "display_text": "新建草稿辅料过敏者禁用",
                        }
                    ],
                    "safety_review_status": "draft",
                }
            )

        self.assertIsNone(MedicineRepository().get_by_hardware_slot(23))

    def test_medicine_patch_rejects_an_unknown_operation(self) -> None:
        with self.assertRaisesRegex(CloudSyncError, "不支持的药品操作"):
            CloudSyncWorker._upsert_medicine(
                {
                    "operation": "replace-all",
                    "hardware_slot": 1,
                    "name": "不应写入的药品",
                }
            )

    def test_medicine_patch_rejects_conflicting_outer_and_inner_slots(self) -> None:
        with self.assertRaisesRegex(CloudSyncError, "仓位存在冲突"):
            CloudSyncWorker._upsert_medicine(
                {
                    "operation": "patch",
                    "hardware_slot": 1,
                    "patch": {
                        "hardwareSlot": 2,
                        "name": "不应串仓的药品",
                    },
                }
            )

    def test_medicine_upsert_does_not_recreate_missing_fixed_identity_from_barcode(self) -> None:
        repository = MedicineRepository()
        slot_one = repository.get_by_hardware_slot(1)
        self.assertIsNotNone(slot_one)
        with db.connect() as conn:
            conn.execute("DELETE FROM medicines WHERE hardware_slot=23")

        with self.assertRaisesRegex(CloudSyncError, "本地固定药品.*缺失"):
            CloudSyncWorker._upsert_medicine(
                {
                    "hardware_slot": 23,
                    "name": "二十三号仓同条码药",
                    "barcode": slot_one.barcode,
                    "quantity": 0,
                    "inventoryState": "DEPLETED",
                    "unit": "盒",
                    "category": "家庭常用",
                    "spec": "10片",
                    "traceCode": "TRACE-023",
                    "lowStockLine": 2,
                    "expireDate": "2030-02",
                }
            )

        self.assertIsNone(repository.get_by_hardware_slot(23))
        self.assertEqual(repository.get_by_hardware_slot(1).id, slot_one.id)

    def test_snapshot_preserves_medicine_extension_fields_and_expiry_precision(self) -> None:
        repository = MedicineRepository()
        medicine = repository.get_by_hardware_slot(1)
        repository.update(
            medicine.id,
            {
                "spec": "20毫克×12粒",
                "trace_code": "TRACE-MONTH",
                "low_stock_line": 3,
                "expire_date": "2029-01",
            },
        )

        monthly = next(row for row in CloudSyncWorker._build_snapshot()["medicines"] if row["slot"] == 1)
        self.assertEqual(monthly["spec"], "20毫克×12粒")
        self.assertEqual(monthly["traceCode"], "TRACE-MONTH")
        self.assertEqual(monthly["lowStockLine"], 3)
        self.assertEqual(monthly["expireDate"], "2029-01")
        self.assertEqual(monthly["expiryPrecision"], "month")

        repository.update(medicine.id, {"expire_date": "2029-01-31"})
        daily = next(row for row in CloudSyncWorker._build_snapshot()["medicines"] if row["slot"] == 1)
        self.assertEqual(daily["expireDate"], "2029-01-31")
        self.assertEqual(daily["expiryPrecision"], "day")

    def test_snapshot_publishes_stable_medicine_identity_independent_of_legacy_slot(self) -> None:
        medicine = MedicineRepository().get_by_hardware_slot(1)

        row = next(
            item
            for item in CloudSyncWorker._build_snapshot()["medicines"]
            if item["slot"] == 1
        )

        self.assertEqual(row["medicineId"], medicine.id)
        self.assertEqual(row["medicine_id"], medicine.id)
        self.assertEqual(row["legacySlot"], medicine.hardware_slot)
        self.assertEqual(row["storageBox"], "DAILY")
        self.assertEqual(row["storage_box"], "DAILY")

    def test_snapshot_translates_local_slot_three_and_thirteen_to_cloud_catalog_identities(self) -> None:
        rows = {
            row["id"]: row
            for row in CloudSyncWorker._build_snapshot()["medicines"]
        }

        montmorillonite = rows["slot-03-diosmectite"]
        ibuprofen = rows["slot-13-ibuprofen"]
        self.assertEqual(
            (
                montmorillonite["medicineId"],
                montmorillonite["medicine_id"],
                montmorillonite["legacySlot"],
                montmorillonite["slot"],
                montmorillonite["hardwareSlot"],
                montmorillonite["hardware_slot"],
            ),
            ("slot-13-montmorillonite", "slot-13-montmorillonite", 13, 13, 13, 13),
        )
        self.assertEqual(
            (
                ibuprofen["medicineId"],
                ibuprofen["medicine_id"],
                ibuprofen["legacySlot"],
                ibuprofen["slot"],
                ibuprofen["hardwareSlot"],
                ibuprofen["hardware_slot"],
            ),
            ("slot-03-ibuprofen", "slot-03-ibuprofen", 3, 3, 3, 3),
        )

    def test_snapshot_projects_the_confirmed_three_cabinet_distribution(self) -> None:
        rows = CloudSyncWorker._build_snapshot()["medicines"]
        counts: dict[str, int] = {}
        for row in rows:
            self.assertEqual(row["storageBox"], row["storage_box"])
            counts[row["storageBox"]] = counts.get(row["storageBox"], 0) + 1

        self.assertEqual(counts, {"DAILY": 9, "CARE": 8, "PRESCRIPTION": 5, "COLD": 1})

    def test_snapshot_rejects_an_unmapped_historical_medicine(self) -> None:
        MedicineRepository().list_all()
        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET id='scan-legacy-unmapped' WHERE hardware_slot=1"
            )

        with self.assertRaisesRegex(CloudSyncError, "未配置小程序同步投影"):
            CloudSyncWorker._build_snapshot()

    def test_snapshot_rejects_a_missing_fixed_medicine_before_finalize(self) -> None:
        MedicineRepository().list_all()
        with db.connect() as conn:
            conn.execute("DELETE FROM medicines WHERE id='slot-23-desloratadine'")

        with self.assertRaisesRegex(CloudSyncError, "本地固定药品目录.*不完整"):
            CloudSyncWorker._build_snapshot()

    def test_snapshot_rejects_a_local_identity_slot_mismatch(self) -> None:
        MedicineRepository().list_all()
        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET hardware_slot=99 WHERE id='slot-23-desloratadine'"
            )

        with self.assertRaisesRegex(CloudSyncError, "身份或兼容仓位错位"):
            CloudSyncWorker._build_snapshot()

    def test_medicine_patch_translates_cloud_catalog_slot_to_local_identity(self) -> None:
        repository = MedicineRepository()
        local_ibuprofen = repository.get_by_hardware_slot(13)
        local_montmorillonite = repository.get_by_hardware_slot(3)

        result = CloudSyncWorker._upsert_medicine(
            {
                "operation": "patch",
                "slot": 3,
                "patch": {"spec": "云端布洛芬规格"},
            }
        )

        self.assertEqual(result["medicine"]["id"], local_ibuprofen.id)
        self.assertEqual(repository.get_by_hardware_slot(13).spec, "云端布洛芬规格")
        self.assertEqual(
            repository.get_by_hardware_slot(3).spec,
            local_montmorillonite.spec,
        )

    def test_medicine_patch_accepts_canonical_identity_without_legacy_slot(self) -> None:
        result = CloudSyncWorker._upsert_medicine(
            {
                "operation": "patch",
                "medicineId": "slot-13-montmorillonite",
                "patch": {
                    "medicine_id": "slot-13-montmorillonite",
                    "spec": "云端蒙脱石规格",
                },
            }
        )

        self.assertEqual(result["medicine"]["id"], "slot-03-diosmectite")
        self.assertEqual(
            MedicineRepository().get_by_hardware_slot(3).spec,
            "云端蒙脱石规格",
        )

    def test_medicine_upsert_rejects_a_missing_fixed_local_identity(self) -> None:
        MedicineRepository().list_all()
        with db.connect() as conn:
            conn.execute("DELETE FROM medicines WHERE id='slot-23-desloratadine'")

        with self.assertRaisesRegex(CloudSyncError, "本地固定药品.*缺失"):
            CloudSyncWorker._upsert_medicine(
                {
                    "operation": "upsert",
                    "medicineId": "slot-23-desloratadine",
                    "slot": 23,
                    "storageBox": "DAILY",
                    "name": "枸地氯雷他定胶囊",
                }
            )

        self.assertIsNone(MedicineRepository().get_by_hardware_slot(23))

    def test_medicine_patch_rejects_conflicting_canonical_identity_and_storage(self) -> None:
        with self.assertRaisesRegex(CloudSyncError, "药品身份与兼容仓位不一致"):
            CloudSyncWorker._upsert_medicine(
                {
                    "operation": "patch",
                    "medicineId": "slot-03-ibuprofen",
                    "slot": 13,
                    "patch": {"spec": "不应写入"},
                }
            )

        with self.assertRaisesRegex(CloudSyncError, "storageBox 与固定药品目录不一致"):
            CloudSyncWorker._upsert_medicine(
                {
                    "operation": "patch",
                    "slot": 9,
                    "storageBox": "PRESCRIPTION",
                    "patch": {"spec": "不应写入"},
                }
            )

    def test_snapshot_projects_available_inventory_with_explicit_cloud_aliases(self) -> None:
        repository = MedicineRepository()
        medicine = repository.get_by_hardware_slot(1)
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET stock=1, inventory_state='AVAILABLE', inventory_revision=7
                WHERE id=?
                """,
                (medicine.id,),
            )

        refreshed = repository.get_by_hardware_slot(1)
        row = next(
            item
            for item in CloudSyncWorker._build_snapshot()["medicines"]
            if item["slot"] == 1
        )

        self.assertEqual(refreshed.inventory_state, "AVAILABLE")
        self.assertEqual(refreshed.inventory_revision, 7)
        self.assertEqual(row["quantity"], 1)
        self.assertEqual(row["inventoryState"], "STOCKED")
        self.assertEqual(row["inventory_state"], "STOCKED")
        self.assertEqual(row["inventoryStateRevision"], 7)
        self.assertEqual(row["inventory_state_revision"], 7)

    def test_snapshot_only_projects_zero_quantity_for_explicit_depleted(self) -> None:
        repository = MedicineRepository()
        medicine = repository.get_by_hardware_slot(1)
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET stock=0, inventory_state='UNKNOWN', inventory_revision=8
                WHERE id=?
                """,
                (medicine.id,),
            )

        row = next(
            item
            for item in CloudSyncWorker._build_snapshot()["medicines"]
            if item["slot"] == 1
        )

        self.assertEqual(row["inventoryState"], "UNKNOWN")
        self.assertEqual(row["quantity"], 1)
        self.assertEqual(row["stock"], 1)

    def test_snapshot_does_not_invent_depletion_confirmation_provenance(self) -> None:
        repository = MedicineRepository()
        medicine = repository.get_by_hardware_slot(1)
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET stock=0, inventory_state='DEPLETED',
                    inventory_confirmed_at='2026-08-20 16:30:00', inventory_revision=9
                WHERE id=?
                """,
                (medicine.id,),
            )

        row = next(
            item
            for item in CloudSyncWorker._build_snapshot()["medicines"]
            if item["slot"] == 1
        )

        self.assertEqual(row["inventoryState"], "DEPLETED")
        self.assertNotIn("depletionConfirmedAt", row)
        self.assertNotIn("depletion_confirmed_at", row)
        self.assertNotIn("depletionConfirmationSource", row)
        self.assertNotIn("depletion_confirmation_source", row)

    def test_medicine_schema_migration_contains_sync_extension_columns(self) -> None:
        with db.connect() as conn:
            columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(medicines)").fetchall()}

        self.assertTrue({"spec", "trace_code", "low_stock_line"}.issubset(columns))

    def test_pulled_miniprogram_medicine_patch_round_trips_to_cloud_snapshot(self) -> None:
        worker = MedicineRoundTripWorker(
            {
                "_id": "medicine-command-1",
                "type": "UPSERT_MEDICINE",
                "payload": {
                    "operation": "patch",
                    "hardware_slot": 1,
                    "patch": {
                        "name": "同步演示药",
                        "spec": "0.3克×10袋",
                        "traceCode": "TRACE-ROUNDTRIP",
                        "quantity": 0,
                        "inventoryState": "DEPLETED",
                        "inventory_state": "DEPLETED",
                        "lowStockLine": 2,
                        "expireDate": "2030-02",
                        "expiryPrecision": "month",
                    },
                },
            }
        )

        worker.run_once()

        medicine_batches = [
            payload for action, payload in worker.calls
            if action == "UPSERT_SNAPSHOT_BATCH" and payload.get("kind") == "medicines"
        ]
        synced = next(row for batch in medicine_batches for row in batch["rows"] if row["slot"] == 1)
        self.assertEqual(synced["name"], "同步演示药")
        self.assertEqual(synced["spec"], "0.3克×10袋")
        self.assertEqual(synced["traceCode"], "TRACE-ROUNDTRIP")
        self.assertEqual(synced["quantity"], 0)
        self.assertEqual(synced["lowStockLine"], 2)
        self.assertEqual(synced["expireDate"], "2030-02")
        self.assertEqual(synced["expiryPrecision"], "month")
        history = worker._command_history("medicine-command-1")
        self.assertEqual(history["status"], "done")

    def test_snapshot_excludes_legacy_demo_spo2_records(self) -> None:
        repository = VitalsRepository()
        repository.append(
            VitalsRecord(
                id="real-vitals",
                temperature=36.5,
                heart_rate=73,
                spo2=97,
                status="available",
                source="UART8-vitals-24B+GY-614",
                measured_at="2026-07-14 10:00:00",
            )
        )
        repository.append(
            VitalsRecord(
                id="legacy-demo-vitals",
                temperature=36.6,
                heart_rate=74,
                spo2=98,
                status="available",
                source="UART8-vitals-24B+GY-614+SpO2-demo",
                sensor_model="UART8-vitals-24B+GY-614+SpO2-demo",
                measured_at="2026-07-14 10:02:00",
            )
        )

        snapshot = CloudSyncWorker._build_snapshot()

        self.assertEqual([row["id"] for row in snapshot["vitals"]], ["real-vitals"])

    def test_snapshot_quarantines_legacy_inquiry_vitals_linked_to_demo_spo2(self) -> None:
        measured_at = "2026-07-14T10:02:00+08:00"
        candidate = {
            "id": "medicine-legacy",
            "name": "旧候选药品",
            "category": "感冒用药",
            "slot": "8",
            "stock": 4,
            "unit": "盒",
            "safety_note": "旧结论",
        }
        VitalsRepository().append(
            VitalsRecord(
                id="vitals-session-legacy-demo",
                temperature=36.6,
                heart_rate=74,
                spo2=98,
                status="available",
                source="UART8-vitals-24B+GY-614+SpO2-demo",
                sensor_model="UART8-vitals-24B+GY-614+SpO2-demo",
                measured_at=measured_at,
            )
        )
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO inquiry_sessions(
                  session_id, user_name, stage, reply, source, vitals_json,
                  risk_level, risk_reasons_json, next_action, primary_candidate_json,
                  alternative_candidate_json, treatment_options_json, can_view_medicines,
                  title, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-demo-inquiry",
                    "访客",
                    "result",
                    "问询已完成",
                    "cloud",
                    json.dumps(
                        {
                            "status": "complete",
                            "temperature": 36.6,
                            "heart_rate": 74,
                            "spo2": 98,
                            "measured_at": measured_at,
                        },
                        ensure_ascii=False,
                    ),
                    "medium",
                    json.dumps(["血氧偏低"], ensure_ascii=False),
                    "show_recommendation",
                    json.dumps(candidate, ensure_ascii=False),
                    json.dumps({**candidate, "id": "medicine-alternative"}, ensure_ascii=False),
                    json.dumps(
                        [
                            {
                                "option_id": "option-legacy",
                                "label": "旧候选方案",
                                "when": "旧风险成立时",
                                "medicines": [{**candidate, "role": "主要对症"}],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    1,
                    "历史问询",
                    measured_at,
                    measured_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO inquiry_messages(id, session_id, role, content, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-demo-conclusion",
                    "legacy-demo-inquiry",
                    "assistant",
                    "风险中等，建议查看旧候选药品。",
                    "cloud",
                    measured_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO inquiry_messages(id, session_id, role, content, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-demo-vitals-tool",
                    "legacy-demo-inquiry",
                    "system",
                    "体征测量完成：额温 36.6℃，心率 74次/分，血氧 98%。",
                    "vitals_tool",
                    measured_at,
                ),
            )

        snapshot = CloudSyncWorker._build_snapshot()

        inquiry = next(row for row in snapshot["inquiries"] if row["inquiry_id"] == "legacy-demo-inquiry")
        self.assertEqual(inquiry["vitals"]["status"], "failed")
        self.assertEqual(inquiry["vitals"]["spo2_source"], "demo_fallback")
        self.assertTrue(inquiry["vitals"]["spo2_demo_fallback"])
        self.assertNotIn("temperature", inquiry["vitals"])
        self.assertNotIn("heart_rate", inquiry["vitals"])
        self.assertNotIn("spo2", inquiry["vitals"])
        self.assertIsNone(inquiry["risk_level"])
        self.assertEqual(inquiry["risk_reasons"], [])
        self.assertIsNone(inquiry["primary_candidate"])
        self.assertIsNone(inquiry["alternative_candidate"])
        self.assertEqual(inquiry["treatment_options"], [])
        self.assertFalse(inquiry["can_view_medicines"])
        self.assertEqual(inquiry["stage"], "escalated")
        self.assertEqual(inquiry["next_action"], "escalate")
        self.assertNotIn("旧候选药品", json.dumps(inquiry, ensure_ascii=False))
        self.assertNotIn("体征测量完成", json.dumps(inquiry, ensure_ascii=False))

    def test_similar_real_vitals_with_incomplete_legacy_signature_are_not_quarantined(self) -> None:
        measured_at = "2026-07-14T10:04:00+08:00"
        VitalsRepository().append(
            VitalsRecord(
                id="vitals-session-real-measurement",
                temperature=36.6,
                heart_rate=74,
                spo2=98,
                status="available",
                source="UART8-vitals-24B+GY-614",
                sensor_model="UART8-vitals-24B+GY-614+SpO2-demo",
                measured_at=measured_at,
            )
        )
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO inquiry_sessions(
                  session_id, user_name, stage, reply, source, vitals_json,
                  risk_level, next_action, title, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "real-inquiry-with-similar-values",
                    "访客",
                    "result",
                    "问询已完成",
                    "cloud",
                    json.dumps(
                        {
                            "status": "complete",
                            "temperature": 36.6,
                            "heart_rate": 74,
                            "spo2": 98,
                            "measured_at": measured_at,
                        },
                        ensure_ascii=False,
                    ),
                    "low",
                    "show_recommendation",
                    "真实问询",
                    measured_at,
                    measured_at,
                ),
            )

        snapshot = CloudSyncWorker._build_snapshot()

        inquiry = next(
            row for row in snapshot["inquiries"] if row["inquiry_id"] == "real-inquiry-with-similar-values"
        )
        self.assertEqual(inquiry["vitals"]["status"], "complete")
        self.assertEqual(inquiry["vitals"]["spo2"], 98)
        self.assertEqual(inquiry["risk_level"], "low")

    def test_ack_failure_never_reexecutes_completed_hardware_command(self) -> None:
        worker = AckFailureWorker()
        command = {"_id": "beep-1", "type": "AUDIO_BEEP", "payload": {}}

        with self.assertRaises(CloudSyncError):
            worker._handle_command(command)

        self.assertEqual(worker.executions, 1)
        self.assertEqual(worker._command_history("beep-1")["status"], "done_unacked")

        worker.fail_ack = False
        worker._flush_unacked_commands()
        worker._handle_command(command)

        self.assertEqual(worker.executions, 1)
        self.assertEqual(worker._command_history("beep-1")["status"], "done")

    def test_restart_marks_inflight_command_ambiguous_instead_of_retrying(self) -> None:
        worker = FakeCloudSyncWorker()
        worker._save_command("open-2", "OPEN_CABINET", "running", {}, db.now_text())

        worker._recover_interrupted_commands()

        history = worker._command_history("open-2")
        self.assertEqual(history["status"], "failed_unacked")
        self.assertIn("禁止自动重试", history["result_json"])

    def test_legacy_remote_cabinet_command_is_rejected_without_touching_qsm(self) -> None:
        worker = MedicineRoundTripWorker(
            {
                "_id": "legacy-open-cabinet",
                "type": "OPEN_CABINET",
                "payload": {
                    "slot": 8,
                    "remote_confirmed": True,
                    "target_user_name": "张三",
                },
                "_openid": "legacy-wechat-user",
            }
        )
        legacy_enabled_settings = replace(settings, cloud_remote_cabinet_enabled=True)

        with (
            patch("app.services.cloud_sync_service.settings", legacy_enabled_settings),
            patch.object(QsmClient, "dispense") as qsm_dispense,
        ):
            worker.run_once()

        acknowledgements = [payload for action, payload in worker.calls if action == "ACK_COMMAND"]
        self.assertEqual(len(acknowledgements), 1)
        self.assertEqual(acknowledgements[0]["status"], "failed")
        self.assertIn("远程开柜已禁用", acknowledgements[0]["result"]["error"])
        qsm_dispense.assert_not_called()

    def test_person_scoped_cloud_command_requires_the_current_persona_generation(self) -> None:
        worker = FakeCloudSyncWorker()
        payload = {
            "id": "plan-demo-wang-amlodipine",
            "service_user_id": "wang-nainai",
            "timing_label": "早餐后",
            "persona_generation": "stale-persona-v0",
        }

        with self.assertRaisesRegex(CloudSyncError, "人物代次"):
            worker._execute_command("UPSERT_TODAY_PLAN", {"payload": payload})

        payload["persona_generation"] = "senior-demo-v1"
        result = worker._execute_command("UPSERT_TODAY_PLAN", {"payload": payload})

        self.assertEqual(result["plan"]["service_user_id"], "wang-nainai")
        self.assertEqual(result["plan"]["persona_generation"], "senior-demo-v1")

    def test_remote_vitals_records_the_current_persona_without_an_unregistered_duplicate(self) -> None:
        worker = FakeCloudSyncWorker()
        payload = {
            "service_user_id": "wang-nainai",
            "service_user_name_snapshot": "不应信任的旧姓名",
            "persona_generation": "stale-persona-v0",
            "inquiry_session_id": "inquiry-remote-vitals",
            "attribution_source": "REMOTE_COMMAND",
        }
        fake_vitals = {
            "temperature_c": 36.5,
            "heart_rate": 71,
            "spo2": 98,
            "temperature_source": "gy614_sensor",
            "heart_rate_source": "uart8_sensor",
            "spo2_source": "uart8_sensor",
            "source": "real",
            "quality": "good",
        }

        def fake_qsm_init(client) -> None:
            client.mode = "real"

        with (
            patch.object(QsmClient, "__init__", fake_qsm_init),
            patch.object(QsmClient, "read_full_vitals", return_value=fake_vitals) as read_vitals,
        ):
            with self.assertRaisesRegex(CloudSyncError, "人物代次"):
                worker._execute_command("READ_VITALS_ALL", {"payload": payload})
            read_vitals.assert_not_called()

            payload["persona_generation"] = "senior-demo-v1"
            result = worker._execute_command("READ_VITALS_ALL", {"payload": payload})

        self.assertEqual(VitalsRepository().count(), 1)
        recorded = VitalsRepository().latest()
        self.assertEqual(recorded.service_user_id, "wang-nainai")
        self.assertEqual(recorded.service_user_name_snapshot, "王奶奶")
        self.assertEqual(recorded.persona_generation, "senior-demo-v1")
        self.assertEqual(recorded.inquiry_session_id, "inquiry-remote-vitals")
        self.assertEqual(recorded.attribution_source, "REMOTE_COMMAND")
        self.assertEqual(result["service_user_id"], "wang-nainai")
        self.assertEqual(result["service_user_name_snapshot"], "王奶奶")

    def test_remote_vitals_standalone_is_explicit_and_cannot_mix_person_fields(self) -> None:
        worker = FakeCloudSyncWorker()
        payload = {
            "attribution_source": "STANDALONE",
            "inquiry_session_id": "",
        }
        fake_vitals = {
            "temperature_c": 36.4,
            "heart_rate": 70,
            "spo2": 99,
            "temperature_source": "gy614_sensor",
            "heart_rate_source": "uart8_sensor",
            "spo2_source": "uart8_sensor",
            "source": "real",
            "quality": "good",
        }

        def fake_qsm_init(client) -> None:
            client.mode = "real"

        with (
            patch.object(QsmClient, "__init__", fake_qsm_init),
            patch.object(QsmClient, "read_full_vitals", return_value=fake_vitals) as read_vitals,
        ):
            result = worker._execute_command(
                "READ_VITALS_ALL",
                {"_id": "remote-vitals-standalone", "payload": payload},
            )
            mixed_payload = {
                **payload,
                "service_user_id": "wang-nainai",
                "persona_generation": "senior-demo-v1",
            }
            with self.assertRaisesRegex(CloudSyncError, "独立测量"):
                worker._execute_command(
                    "READ_VITALS_ALL",
                    {"_id": "remote-vitals-invalid-mixed", "payload": mixed_payload},
                )

        read_vitals.assert_called_once()
        self.assertEqual(VitalsRepository().count(), 1)
        recorded = VitalsRepository().latest()
        self.assertEqual(recorded.service_user_id, "")
        self.assertEqual(recorded.persona_generation, "")
        self.assertEqual(recorded.attribution_source, "STANDALONE")
        self.assertEqual(result["attribution_source"], "STANDALONE")

    def test_miniprogram_speak_command_announces_the_named_reminder(self) -> None:
        worker = FakeCloudSyncWorker()
        with patch("app.services.cloud_sync_service.SpeechService") as speech_factory:
            speech_factory.return_value.speak_sync.return_value = {"ok": True, "detail": "played"}

            result = worker._execute_command(
                "AUDIO_SPEAK",
                {
                    "payload": {
                        "target_user_name": "张三",
                        "medicine_name": "藿香正气丸",
                        "volume": 210,
                    }
                },
            )

        speech_factory.return_value.speak_sync.assert_called_once_with(
            "张三，该服用藿香正气丸了。",
            volume=210,
            speed=None,
        )
        self.assertTrue(result["ok"])

    def test_targeted_miniprogram_speak_command_requires_current_persona(self) -> None:
        worker = FakeCloudSyncWorker()
        payload = {
            "target_user_id": "wang-nainai",
            "target_user_name": "王奶奶",
            "text": "王奶奶请及时用药。",
            "persona_generation": "stale-persona-v0",
        }

        with patch("app.services.cloud_sync_service.SpeechService") as speech_factory:
            with self.assertRaisesRegex(CloudSyncError, "人物代次"):
                worker._execute_command("AUDIO_SPEAK", {"payload": payload})
            speech_factory.assert_not_called()

            payload["persona_generation"] = "senior-demo-v1"
            speech_factory.return_value.speak_sync.return_value = {
                "ok": True,
                "detail": "played",
            }
            result = worker._execute_command("AUDIO_SPEAK", {"payload": payload})

        speech_factory.return_value.speak_sync.assert_called_once_with(
            "王奶奶请及时用药。",
            volume=None,
            speed=None,
        )
        self.assertTrue(result["ok"])

    def test_miniprogram_speak_command_requires_text_or_a_person_name(self) -> None:
        worker = FakeCloudSyncWorker()

        with self.assertRaisesRegex(CloudSyncError, "播报内容"):
            worker._execute_command("AUDIO_SPEAK", {"payload": {}})


if __name__ == "__main__":
    unittest.main()
