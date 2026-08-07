from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.repositories.medicine_repository import MedicineRepository  # noqa: E402
from app.repositories.sync_repository import SyncRepository  # noqa: E402
from app.schemas.sync import SyncStatus  # noqa: E402
from app.repositories.vitals_repository import VitalsRecord, VitalsRepository  # noqa: E402
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


class MedicineRoundTripWorker(FakeV2CloudSyncWorker):
    def __init__(self, command: dict[str, object]) -> None:
        super().__init__(revision="2.3-medicine-sync-contract")
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
            return {"ok": True, "schemaVersion": 2, "schemaRevision": self.revision}
        if action == "UPSERT_SNAPSHOT_BATCH":
            rows = data.get("rows", [])
            return {
                "ok": True,
                "count": len(rows),
                "ids": [f"id-{data.get('kind')}-{index}" for index, _ in enumerate(rows)],
            }
        return {"ok": True}


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

    def test_local_display_mode_pauses_miniprogram_realtime_calls(self) -> None:
        db.set_setting("network_mode", "local")
        worker = FakeCloudSyncWorker()

        with self.assertRaisesRegex(CloudSyncError, "本地模式"):
            worker.run_once()

        self.assertEqual(worker.calls, [])

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
                "messages": [{"role": "user", "content": "有些头晕"}],
                "created_at": "2026-07-19 08:00:00",
                "updated_at": "2026-07-19 08:03:00",
            },
        )
        with patch("app.services.cloud_sync_service.InquiryRepository") as repository_class:
            repository_class.return_value.list_sessions.return_value = [session]
            repository_class.return_value.list_records.return_value = []

            snapshot = CloudSyncWorker._build_snapshot()

        row = snapshot["inquiries"][0]
        self.assertEqual(row["inquiry_id"], "session-current")
        self.assertEqual(row["target_user_name"], "张三")
        self.assertEqual(row["symptoms_summary"], "轻微头晕")
        self.assertEqual(row["updatedAt"], "2026-07-19 08:03:00")

    def test_sync_summary_excludes_full_dialogue_messages(self) -> None:
        summary = CloudSyncWorker._sync_summary(
            {
                "medicines": [],
                "serviceUsers": [],
                "plans": [],
                "inquiries": [
                    {
                        "session_id": "session-summary",
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

    def test_medicine_patch_updates_only_explicit_fields_and_preserves_zero_stock(self) -> None:
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

    def test_medicine_upsert_uses_hardware_slot_not_barcode_as_identity(self) -> None:
        repository = MedicineRepository()
        slot_one = repository.get_by_hardware_slot(1)
        self.assertIsNotNone(slot_one)
        with db.connect() as conn:
            conn.execute("DELETE FROM medicines WHERE hardware_slot=23")

        result = CloudSyncWorker._upsert_medicine(
            {
                "hardware_slot": 23,
                "name": "二十三号仓同条码药",
                "barcode": slot_one.barcode,
                "quantity": 0,
                "unit": "盒",
                "category": "家庭常用",
                "spec": "10片",
                "traceCode": "TRACE-023",
                "lowStockLine": 2,
                "expireDate": "2030-02",
            }
        )

        slot_twenty_three = repository.get_by_hardware_slot(23)
        self.assertEqual(result["medicine"]["hardware_slot"], 23)
        self.assertIsNotNone(slot_twenty_three)
        self.assertNotEqual(slot_twenty_three.id, slot_one.id)
        self.assertEqual(slot_twenty_three.barcode, slot_one.barcode)
        self.assertEqual(slot_twenty_three.stock, 0)
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

    def test_remote_cabinet_requires_confirmation_and_miniprogram_identity(self) -> None:
        worker = FakeCloudSyncWorker()

        with self.assertRaisesRegex(CloudSyncError, "明确确认"):
            worker._open_cabinet({"slot": 8}, {"_openid": "wechat-user"})
        with self.assertRaisesRegex(CloudSyncError, "小程序身份"):
            worker._open_cabinet({"slot": 8, "remote_confirmed": True}, {})

    def test_confirmed_miniprogram_command_reaches_dispense_service(self) -> None:
        worker = FakeCloudSyncWorker()
        response = SimpleNamespace(model_dump=lambda mode: {"ok": True, "slot": 8, "mode": mode})
        with patch("app.services.cloud_sync_service.DispenseService") as service_class:
            service_class.return_value.open_cabinet.return_value = response
            result = worker._open_cabinet(
                {
                    "slot": 8,
                    "remote_confirmed": True,
                    "target_user_name": "张三",
                    "reason": "家属端远程开柜",
                },
                {"_openid": "wechat-user"},
            )

        request = service_class.return_value.open_cabinet.call_args.args[0]
        self.assertEqual(result["slot"], 8)
        self.assertEqual(request.slot, 8)
        self.assertTrue(request.confirmed_open)
        self.assertEqual(request.target_user_name, "张三")

    def test_miniprogram_speak_command_announces_the_named_reminder(self) -> None:
        worker = FakeCloudSyncWorker()
        with patch("app.services.cloud_sync_service.get_host_offline_tts") as tts_factory:
            tts_factory.return_value.speak_sync.return_value = {"ok": True, "detail": "played"}

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

        tts_factory.return_value.speak_sync.assert_called_once_with(
            "张三，该服用藿香正气丸了。",
            volume=210,
            speed=None,
        )
        self.assertTrue(result["ok"])

    def test_miniprogram_speak_command_requires_text_or_a_person_name(self) -> None:
        worker = FakeCloudSyncWorker()

        with self.assertRaisesRegex(CloudSyncError, "播报内容"):
            worker._execute_command("AUDIO_SPEAK", {"payload": {}})


if __name__ == "__main__":
    unittest.main()
