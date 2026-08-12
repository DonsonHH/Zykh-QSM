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
from app.modules.vitals_session import VitalsSessionModule  # noqa: E402
from app.repositories.demo_vitals_repository import DemoVitalsRepository  # noqa: E402
from app.repositories.inquiry_repository import InquiryRepository  # noqa: E402
from app.repositories.sync_repository import SyncRepository  # noqa: E402
from app.repositories.vitals_repository import VitalsRecord, VitalsRepository  # noqa: E402
from app.services.cloud_sync_service import CloudSyncWorker  # noqa: E402
from app.schemas.inquiry import InquirySessionResponse  # noqa: E402
from app.schemas.inquiry import InquirySessionCreateRequest  # noqa: E402
from app.schemas.records import ServiceUserCreateRequest  # noqa: E402
from app.services.inquiry_orchestrator import InquiryOrchestrator  # noqa: E402
from app.services.records_service import RecordsService  # noqa: E402


class InMemoryVitalsGateway:
    def __init__(self, status_payload: dict[str, object]) -> None:
        self.status_payload = status_payload
        self.prepare_count = 0
        self.replace_active_requested: bool | None = None
        self.cancelled_session_id = ""
        self.start_count = 0

    def prepare_vitals(self) -> dict[str, object]:
        self.prepare_count += 1
        return {"ok": True, "status": "prepared"}

    def start_vitals_session(self, *, replace_active: bool = True) -> dict[str, object]:
        self.start_count += 1
        self.replace_active_requested = replace_active
        return {
            "ok": True,
            "session_id": "module-session",
            "status": "starting",
            "hardware_started": True,
        }

    def get_vitals_session(self, session_id: str) -> dict[str, object]:
        return {**self.status_payload, "session_id": session_id}

    def cancel_vitals_session(self, session_id: str) -> dict[str, object]:
        self.cancelled_session_id = session_id
        return {
            "ok": True,
            "session_id": session_id,
            "status": "cancelled",
            "hardware_started": False,
        }


class BusyVitalsGateway(InMemoryVitalsGateway):
    def __init__(self, busy_session_id: str) -> None:
        super().__init__({"ok": False, "status": "failed"})
        self.busy_session_id = busy_session_id

    def start_vitals_session(self, *, replace_active: bool = True) -> dict[str, object]:
        self.start_count += 1
        self.replace_active_requested = replace_active
        return {
            "ok": False,
            "session_id": self.busy_session_id,
            "status": "failed",
            "hardware_started": False,
            "communication_status": "gateway_available",
            "failure_reason": "session_busy",
            "error_message": "another measurement is still active",
        }


class VitalsSessionModuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "vitals-module.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_complete_real_measurement_is_persisted_once_through_module_interface(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "complete",
                "hardware_started": True,
                "temperature": 36.6,
                "heart_rate": 72,
                "spo2": 98,
                "temperature_source": "gy614_sensor",
                "heart_rate_source": "uart8_sensor",
                "spo2_source": "uart8_sensor",
                "source": "UART8-vitals-24B+GY-614",
                "measured_at": "2026-08-05T15:00:00+08:00",
            }
        )
        module = VitalsSessionModule(gateway=gateway)

        first = module.get("module-session")
        second = module.get("module-session")

        self.assertEqual(first.status, "complete")
        self.assertEqual(second.session_id, "module-session")
        self.assertEqual(VitalsRepository().count(), 1)
        self.assertEqual(SyncRepository().get_status().pending_count, 1)

    def test_demo_fallback_is_recorded_in_main_backend_with_classification_fields(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "complete",
                "hardware_started": True,
                "temperature": 36.6,
                "heart_rate": 72,
                "spo2": 97,
                "temperature_source": "gy614_sensor",
                "heart_rate_source": "uart8_sensor",
                "spo2_source": "demo_fallback",
                "spo2_demo_fallback": True,
                "demo_fallback_reason": "spo2_not_stable",
                "completion_reason": "spo2_not_stable",
                "quality": "demo_fallback",
                "source": "UART8-vitals-24B+GY-614",
                "measured_at": "2026-08-05T15:05:00+08:00",
            }
        )

        module = VitalsSessionModule(gateway=gateway)
        response = module.get("module-demo")
        repeated = module.get("module-demo")

        self.assertEqual(response.status, "complete")
        self.assertEqual(repeated.session_id, "module-demo")
        self.assertEqual(response.spo2_source, "demo_fallback")
        self.assertEqual(VitalsRepository().count(), 1)
        self.assertEqual(DemoVitalsRepository().count(), 0)
        recorded = VitalsRepository().latest()
        self.assertIsNotNone(recorded)
        self.assertEqual(recorded.heart_rate, 72)
        self.assertEqual(recorded.spo2, 97)
        self.assertEqual(recorded.spo2_source, "demo_fallback")
        self.assertEqual(recorded.measurement_quality, "demo_fallback")
        self.assertEqual(recorded.completion_reason, "spo2_not_stable")
        self.assertEqual(SyncRepository().get_status().pending_count, 1)
        snapshot = CloudSyncWorker._build_snapshot()["vitals"]
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["spo2_source"], "demo_fallback")
        self.assertEqual(snapshot[0]["measurement_quality"], "demo_fallback")
        self.assertEqual(snapshot[0]["completion_reason"], "spo2_not_stable")

    def test_approximate_sensor_result_is_recorded_without_remeasurement(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "complete",
                "hardware_started": True,
                "temperature": 36.5,
                "heart_rate": 78,
                "spo2": 96,
                "temperature_source": "gy614_sensor",
                "heart_rate_source": "uart8_sensor",
                "spo2_source": "uart8_sensor",
                "quality": "approximate",
                "completion_reason": "core_not_stable",
                "source": "UART8-vitals-24B+GY-614",
                "measured_at": "2026-08-13T03:05:00+08:00",
            }
        )

        response = VitalsSessionModule(gateway=gateway).get("module-approximate")

        self.assertEqual(response.status, "complete")
        recorded = VitalsRepository().latest()
        self.assertIsNotNone(recorded)
        self.assertEqual(recorded.heart_rate, 78)
        self.assertEqual(recorded.spo2, 96)
        self.assertEqual(recorded.measurement_quality, "approximate")
        self.assertEqual(recorded.completion_reason, "core_not_stable")

    def test_legacy_demo_store_adds_and_backfills_fallback_reason(self) -> None:
        legacy_db_path = Path(self.temp_dir.name) / "legacy-demo-vitals.db"
        with patch("app.db.settings", SimpleNamespace(db_path=legacy_db_path)):
            with db.connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE demo_vitals_records (
                      id TEXT PRIMARY KEY,
                      session_id TEXT NOT NULL UNIQUE,
                      temperature REAL NOT NULL,
                      heart_rate INTEGER NOT NULL,
                      spo2 INTEGER NOT NULL,
                      measured_at TEXT NOT NULL,
                      failure_reason TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO demo_vitals_records(
                      id, session_id, temperature, heart_rate, spo2,
                      measured_at, failure_reason
                    ) VALUES ('legacy-demo', 'legacy-session', 36.5, 72, 97,
                              '2026-08-13T02:45:00+08:00', 'spo2_not_stable')
                    """
                )

            db.init_db()

            with db.connect() as conn:
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(demo_vitals_records)")
                }
                row = conn.execute(
                    "SELECT demo_fallback_reason FROM demo_vitals_records "
                    "WHERE session_id='legacy-session'"
                ).fetchone()
            self.assertIn("demo_fallback_reason", columns)
            self.assertEqual(row["demo_fallback_reason"], "spo2_not_stable")

    def test_failed_measurement_keeps_current_values_separate_from_history(self) -> None:
        VitalsRepository().append(
            VitalsRecord(
                id="previous-complete",
                temperature=36.4,
                heart_rate=75,
                spo2=98,
                status="available",
                source="UART-vitals",
                measured_at="2026-08-05T14:00:00+08:00",
            )
        )
        gateway = InMemoryVitalsGateway(
            {
                "ok": False,
                "mode": "real",
                "status": "failed",
                "hardware_started": True,
                "temperature": 36.6,
                "heart_rate": None,
                "spo2": None,
                "temperature_source": "gy614_sensor",
                "failure_reason": "no_finger",
                "error_message": "手指信号未稳定。",
            }
        )

        response = VitalsSessionModule(gateway=gateway).get("module-history")

        self.assertEqual(response.status, "failed")
        self.assertEqual(response.temperature, 36.6)
        self.assertIsNone(response.heart_rate)
        self.assertIsNone(response.spo2)
        self.assertTrue(response.historical_fallback)
        self.assertEqual(response.historical_temperature, 36.4)
        self.assertEqual(response.historical_heart_rate, 75)
        self.assertEqual(response.historical_spo2, 98)
        self.assertEqual(VitalsRepository().count(), 1)
        snapshot = CloudSyncWorker._build_snapshot()["vitals"]
        self.assertEqual([item["id"] for item in snapshot], ["previous-complete"])
        self.assertFalse(any(key.startswith("historical_") for key in snapshot[0]))

    def test_lifecycle_interface_preserves_session_identity_and_replace_choice(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "starting",
                "hardware_started": True,
            }
        )
        module = VitalsSessionModule(gateway=gateway)

        prepared = module.prepare()
        started = module.start(replace_active=False)
        cancelled = module.cancel(started.session_id)

        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(gateway.prepare_count, 1)
        self.assertFalse(gateway.replace_active_requested)
        self.assertEqual(started.session_id, "module-session")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(gateway.cancelled_session_id, "module-session")

    def test_busy_home_session_cannot_be_reassigned_to_a_new_inquiry(self) -> None:
        owner_session_id = VitalsSessionModule(
            gateway=InMemoryVitalsGateway({"ok": True, "status": "starting"})
        ).start(source_route="HOME").session_id
        InquiryRepository().save_session(
            InquirySessionResponse(
                session_id="inquiry-busy-new-owner",
                user_id="wang-nainai",
                user_name="王奶奶",
                persona_generation="senior-demo-v1",
                stage="vitals",
                reply="请测量体征",
                next_action="measure_vitals",
                created_at="2026-08-11 09:00:00",
                updated_at="2026-08-11 09:00:00",
            )
        )
        busy = BusyVitalsGateway(owner_session_id)

        rejected = VitalsSessionModule(gateway=busy).start(
            replace_active=True,
            source_route="INQUIRY",
            inquiry_session_id="inquiry-busy-new-owner",
        )
        reloaded = VitalsSessionModule(
            gateway=InMemoryVitalsGateway(
                {
                    "ok": False,
                    "status": "failed",
                    "hardware_started": False,
                }
            )
        ).get(owner_session_id)

        self.assertFalse(rejected.hardware_started)
        self.assertEqual(rejected.failure_reason, "session_busy")
        self.assertEqual(rejected.source_route, "HOME")
        self.assertEqual(rejected.inquiry_session_id, "")
        self.assertEqual(reloaded.source_route, "HOME")
        self.assertEqual(reloaded.inquiry_session_id, "")

    def test_busy_inquiry_session_cannot_be_reassigned_to_another_inquiry(self) -> None:
        for inquiry_session_id in ("inquiry-busy-owner-a", "inquiry-busy-owner-b"):
            InquiryRepository().save_session(
                InquirySessionResponse(
                    session_id=inquiry_session_id,
                    user_id="wang-nainai",
                    user_name="王奶奶",
                    persona_generation="senior-demo-v1",
                    stage="vitals",
                    reply="请测量体征",
                    next_action="measure_vitals",
                    created_at="2026-08-11 09:10:00",
                    updated_at="2026-08-11 09:10:00",
                )
            )
        owner_session_id = VitalsSessionModule(
            gateway=InMemoryVitalsGateway({"ok": True, "status": "starting"})
        ).start(
            source_route="INQUIRY",
            inquiry_session_id="inquiry-busy-owner-a",
        ).session_id

        rejected = VitalsSessionModule(
            gateway=BusyVitalsGateway(owner_session_id)
        ).start(
            replace_active=True,
            source_route="INQUIRY",
            inquiry_session_id="inquiry-busy-owner-b",
        )
        reloaded = VitalsSessionModule(
            gateway=InMemoryVitalsGateway(
                {
                    "ok": False,
                    "status": "failed",
                    "hardware_started": False,
                }
            )
        ).get(owner_session_id)

        self.assertFalse(rejected.hardware_started)
        self.assertEqual(rejected.inquiry_session_id, "inquiry-busy-owner-a")
        self.assertEqual(reloaded.source_route, "INQUIRY")
        self.assertEqual(reloaded.inquiry_session_id, "inquiry-busy-owner-a")
        self.assertEqual(reloaded.service_user_id, "wang-nainai")

    def test_inquiry_start_derives_person_and_persists_attribution_across_module_instances(self) -> None:
        InquiryRepository().save_session(
            InquirySessionResponse(
                session_id="inquiry-vitals-owner",
                user_id="wang-nainai",
                user_name="王奶奶",
                persona_generation="senior-demo-v1",
                stage="vitals",
                reply="请测量体征",
                next_action="measure_vitals",
                created_at="2026-08-10 20:00:00",
                updated_at="2026-08-10 20:00:00",
            )
        )
        with db.connect() as conn:
            conn.execute(
                "UPDATE service_users SET name=? WHERE id=?",
                ("王奶奶（资料新名）", "wang-nainai"),
            )
        start_gateway = InMemoryVitalsGateway({"ok": True, "status": "starting"})

        started = VitalsSessionModule(gateway=start_gateway).start(
            replace_active=True,
            source_route="INQUIRY",
            inquiry_session_id="inquiry-vitals-owner",
        )

        self.assertEqual(started.source_route, "INQUIRY")
        self.assertEqual(started.inquiry_session_id, "inquiry-vitals-owner")
        self.assertEqual(started.attribution_source, "INQUIRY_SESSION")
        self.assertEqual(started.service_user_id, "wang-nainai")
        self.assertEqual(started.service_user_name_snapshot, "王奶奶")
        self.assertTrue(started.persona_generation)

        complete_gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "complete",
                "hardware_started": True,
                "temperature": 36.6,
                "heart_rate": 72,
                "spo2": 98,
                "temperature_source": "gy614_sensor",
                "heart_rate_source": "uart8_sensor",
                "spo2_source": "uart8_sensor",
                "source": "UART8-vitals-24B+GY-614",
                "measured_at": "2026-08-10T20:01:00+08:00",
            }
        )
        completed = VitalsSessionModule(gateway=complete_gateway).get(started.session_id)
        record = VitalsRepository().latest()
        assert record is not None

        self.assertEqual(completed.service_user_id, "wang-nainai")
        self.assertEqual(record.source_route, "INQUIRY")
        self.assertEqual(record.inquiry_session_id, "inquiry-vitals-owner")
        self.assertEqual(record.attribution_source, "INQUIRY_SESSION")
        self.assertEqual(record.service_user_id, "wang-nainai")
        cloud = CloudSyncWorker._build_snapshot()["vitals"][0]
        self.assertEqual(cloud["serviceUserId"], "wang-nainai")
        self.assertEqual(cloud["personaGeneration"], started.persona_generation)

    def test_guest_inquiry_can_complete_vitals_without_binding_a_registered_person(self) -> None:
        InquiryRepository().save_session(
            InquirySessionResponse(
                session_id="inquiry-guest-vitals",
                user_id="",
                user_name="现场访客",
                persona_generation="",
                stage="vitals",
                reply="请测量体征",
                next_action="measure_vitals",
                created_at="2026-08-11 10:00:00",
                updated_at="2026-08-11 10:00:00",
            )
        )
        start_gateway = InMemoryVitalsGateway({"ok": True, "status": "starting"})

        started = VitalsSessionModule(gateway=start_gateway).start(
            source_route="INQUIRY",
            inquiry_session_id="inquiry-guest-vitals",
        )

        self.assertEqual(started.source_route, "INQUIRY")
        self.assertEqual(started.inquiry_session_id, "inquiry-guest-vitals")
        self.assertEqual(started.attribution_source, "INQUIRY_SESSION")
        self.assertEqual(started.service_user_id, "")
        self.assertEqual(started.service_user_name_snapshot, "现场访客")
        self.assertEqual(started.persona_generation, "")
        complete_gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "complete",
                "hardware_started": True,
                "temperature": 36.6,
                "heart_rate": 72,
                "spo2": 98,
                "temperature_source": "gy614_sensor",
                "heart_rate_source": "uart8_sensor",
                "spo2_source": "uart8_sensor",
                "source": "UART8-vitals-24B+GY-614",
                "measured_at": "2026-08-11T10:01:00+08:00",
            }
        )

        completed = VitalsSessionModule(gateway=complete_gateway).get(started.session_id)
        record = VitalsRepository().latest()
        assert record is not None

        self.assertEqual(completed.status, "complete")
        self.assertEqual(record.inquiry_session_id, "inquiry-guest-vitals")
        self.assertEqual(record.attribution_source, "INQUIRY_SESSION")
        self.assertEqual(record.service_user_id, "")
        self.assertEqual(record.service_user_name_snapshot, "现场访客")
        self.assertEqual(record.persona_generation, "")

    def test_new_service_user_and_inquiry_snapshot_receive_a_server_generation(self) -> None:
        person = RecordsService().create_service_user(
            ServiceUserCreateRequest(name="体征归属测试人物")
        )
        orchestrator = InquiryOrchestrator(
            interpreter=SimpleNamespace(
                opening_question=lambda _profile, fallback: (fallback, "test")
            )
        )

        created = orchestrator.create_session(
            InquirySessionCreateRequest(service_user_id=person.id)
        )
        loaded = InquiryRepository().get_session(created.session_id)

        self.assertRegex(person.persona_generation, r"^persona-[0-9a-f]{32}$")
        self.assertEqual(created.persona_generation, person.persona_generation)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.persona_generation, person.persona_generation)

    def test_startup_backfills_one_stable_generation_without_rebinding_identity(self) -> None:
        with db.connect() as conn:
            conn.executemany(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  persona_generation, archived
                ) VALUES (?, ?, 70, '既有资料', '', '历史自建人物', '正常', ?, ?)
                """,
                (
                    ("legacy-active-person", "既有自建人物", "", 0),
                    ("legacy-archived-person", "已归档人物", "", 1),
                    ("existing-generation-person", "已有代次人物", "persona-kept-v2", 0),
                ),
            )
            conn.execute(
                """
                INSERT INTO face_identities(
                  subject, service_user_id, confidence, match_count,
                  enrolled_at, last_seen_at
                ) VALUES ('legacy-face-subject', 'legacy-active-person', 0.97, 3,
                          '2026-08-01 10:00:00', '2026-08-09 10:00:00')
                """
            )

        db.init_db()
        with db.connect() as conn:
            first = {
                str(row["id"]): str(row["persona_generation"] or "")
                for row in conn.execute(
                    """
                    SELECT id, persona_generation FROM service_users
                    WHERE id IN (
                      'legacy-active-person', 'legacy-archived-person',
                      'existing-generation-person'
                    )
                    """
                ).fetchall()
            }
            binding_after_first = dict(
                conn.execute(
                    "SELECT * FROM face_identities WHERE subject='legacy-face-subject'"
                ).fetchone()
            )

        db.init_db()
        with db.connect() as conn:
            generations_after_restart = {
                str(row["id"]): str(row["persona_generation"] or "")
                for row in conn.execute(
                    """
                    SELECT id, persona_generation FROM service_users
                    WHERE id IN ('legacy-active-person', 'legacy-archived-person')
                    """
                ).fetchall()
            }
            binding_after_restart = dict(
                conn.execute(
                    "SELECT * FROM face_identities WHERE subject='legacy-face-subject'"
                ).fetchone()
            )

        self.assertRegex(first["legacy-active-person"], r"^persona-[0-9a-f]{32}$")
        self.assertRegex(first["legacy-archived-person"], r"^persona-[0-9a-f]{32}$")
        self.assertEqual(
            generations_after_restart["legacy-active-person"],
            first["legacy-active-person"],
        )
        self.assertEqual(
            generations_after_restart["legacy-archived-person"],
            first["legacy-archived-person"],
        )
        self.assertEqual(first["existing-generation-person"], "persona-kept-v2")
        self.assertEqual(binding_after_restart, binding_after_first)

        InquiryRepository().save_session(
            InquirySessionResponse(
                session_id="inquiry-backfilled-person",
                user_id="legacy-active-person",
                user_name="既有自建人物",
                persona_generation=first["legacy-active-person"],
                stage="vitals",
                reply="请测量体征",
                next_action="measure_vitals",
                created_at="2026-08-10 20:00:00",
                updated_at="2026-08-10 20:00:00",
            )
        )
        started = VitalsSessionModule(
            gateway=InMemoryVitalsGateway({"ok": True, "status": "starting"})
        ).start(
            source_route="INQUIRY",
            inquiry_session_id="inquiry-backfilled-person",
        )
        self.assertEqual(started.service_user_id, "legacy-active-person")
        self.assertEqual(started.persona_generation, first["legacy-active-person"])

    def test_inquiry_start_rejects_a_session_without_a_persona_snapshot(self) -> None:
        InquiryRepository().save_session(
            InquirySessionResponse(
                session_id="inquiry-missing-persona",
                user_id="wang-nainai",
                user_name="王奶奶",
                stage="vitals",
                reply="请测量体征",
                next_action="measure_vitals",
                created_at="2026-08-10 20:00:00",
                updated_at="2026-08-10 20:00:00",
            )
        )
        gateway = InMemoryVitalsGateway({"ok": True, "status": "starting"})

        with self.assertRaisesRegex(ValueError, "代次快照"):
            VitalsSessionModule(gateway=gateway).start(
                source_route="INQUIRY",
                inquiry_session_id="inquiry-missing-persona",
            )

        self.assertEqual(gateway.start_count, 0)

    def test_invalid_inquiry_context_fails_before_starting_hardware(self) -> None:
        gateway = InMemoryVitalsGateway({"ok": True, "status": "starting"})

        with self.assertRaises(ValueError):
            VitalsSessionModule(gateway=gateway).start(
                source_route="INQUIRY",
                inquiry_session_id="missing-session",
            )

        self.assertEqual(gateway.start_count, 0)

    def test_inquiry_start_rejects_a_stale_persona_snapshot_before_hardware(self) -> None:
        InquiryRepository().save_session(
            InquirySessionResponse(
                session_id="inquiry-stale-persona",
                user_id="wang-nainai",
                user_name="旧人物快照",
                persona_generation="retired-persona-v0",
                stage="vitals",
                reply="请测量体征",
                next_action="measure_vitals",
                created_at="2026-08-10 20:00:00",
                updated_at="2026-08-10 20:00:00",
            )
        )
        gateway = InMemoryVitalsGateway({"ok": True, "status": "starting"})

        with self.assertRaisesRegex(ValueError, "代次"):
            VitalsSessionModule(gateway=gateway).start(
                source_route="INQUIRY",
                inquiry_session_id="inquiry-stale-persona",
            )

        self.assertEqual(gateway.start_count, 0)

    def test_inquiry_start_requires_the_session_to_be_at_the_vitals_stage(self) -> None:
        InquiryRepository().save_session(
            InquirySessionResponse(
                session_id="inquiry-old-result",
                user_id="wang-nainai",
                user_name="王奶奶",
                persona_generation="senior-demo-v1",
                stage="result",
                reply="问询已结束",
                next_action="complete",
                created_at="2026-08-10 20:00:00",
                updated_at="2026-08-10 20:00:00",
            )
        )
        gateway = InMemoryVitalsGateway({"ok": True, "status": "starting"})

        with self.assertRaisesRegex(ValueError, "当前阶段"):
            VitalsSessionModule(gateway=gateway).start(
                source_route="INQUIRY",
                inquiry_session_id="inquiry-old-result",
            )

        self.assertEqual(gateway.start_count, 0)

    def test_failed_inquiry_measurement_never_shows_another_persons_history(self) -> None:
        VitalsRepository().append(
            VitalsRecord(
                id="li-yeye-previous",
                temperature=36.5,
                heart_rate=70,
                spo2=98,
                status="available",
                source="UART8-vitals-24B+GY-614",
                measured_at="2026-08-10T19:00:00+08:00",
                source_route="INQUIRY",
                inquiry_session_id="inquiry-li-previous",
                attribution_source="INQUIRY_SESSION",
                service_user_id="li-yeye",
                service_user_name_snapshot="李爷爷",
                persona_generation="senior-demo-v1",
            )
        )
        InquiryRepository().save_session(
            InquirySessionResponse(
                session_id="inquiry-wang-no-history",
                user_id="wang-nainai",
                user_name="王奶奶",
                persona_generation="senior-demo-v1",
                stage="vitals",
                reply="请测量体征",
                next_action="measure_vitals",
                created_at="2026-08-10 20:00:00",
                updated_at="2026-08-10 20:00:00",
            )
        )
        failed_gateway = InMemoryVitalsGateway(
            {
                "ok": False,
                "mode": "real",
                "status": "failed",
                "hardware_started": True,
                "temperature": 36.6,
                "heart_rate": None,
                "spo2": None,
                "failure_reason": "no_finger",
            }
        )
        module = VitalsSessionModule(gateway=failed_gateway)
        started = module.start(
            source_route="INQUIRY",
            inquiry_session_id="inquiry-wang-no-history",
        )

        response = module.get(started.session_id)

        self.assertFalse(response.historical_fallback)
        self.assertIsNone(response.historical_heart_rate)

    def test_failed_inquiry_measurement_never_shows_a_previous_persona_generation(self) -> None:
        VitalsRepository().append(
            VitalsRecord(
                id="wang-previous-persona",
                temperature=36.5,
                heart_rate=70,
                spo2=98,
                status="available",
                source="UART8-vitals-24B+GY-614",
                measured_at="2026-08-10T19:00:00+08:00",
                source_route="INQUIRY",
                inquiry_session_id="inquiry-wang-retired",
                attribution_source="INQUIRY_SESSION",
                service_user_id="wang-nainai",
                service_user_name_snapshot="王奶奶",
                persona_generation="retired-persona-v0",
            )
        )
        InquiryRepository().save_session(
            InquirySessionResponse(
                session_id="inquiry-wang-current",
                user_id="wang-nainai",
                user_name="王奶奶",
                persona_generation="senior-demo-v1",
                stage="vitals",
                reply="请测量体征",
                next_action="measure_vitals",
                created_at="2026-08-10 20:00:00",
                updated_at="2026-08-10 20:00:00",
            )
        )
        failed_gateway = InMemoryVitalsGateway(
            {
                "ok": False,
                "mode": "real",
                "status": "failed",
                "hardware_started": True,
                "temperature": 36.6,
                "heart_rate": None,
                "spo2": None,
                "failure_reason": "no_finger",
            }
        )
        module = VitalsSessionModule(gateway=failed_gateway)
        started = module.start(
            source_route="INQUIRY",
            inquiry_session_id="inquiry-wang-current",
        )

        response = module.get(started.session_id)

        self.assertFalse(response.historical_fallback)
        self.assertIsNone(response.historical_heart_rate)

    def test_gateway_diagnostics_and_provenance_cross_the_module_interface(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "complete",
                "hardware_started": True,
                "temperature": 36.6,
                "heart_rate": 72,
                "spo2": 98,
                "temperature_source": "gy614_sensor",
                "heart_rate_source": "uart8_sensor",
                "spo2_source": "uart8_sensor",
                "stable_core": True,
                "communication_status": "receiving_protocol_frames",
                "valid_frame_count": 8,
                "contact_frame_count": 6,
                "heart_rate_frame_count": 5,
                "spo2_frame_count": 4,
                "first_heart_rate_frame": 3,
                "first_spo2_frame": 5,
                "spo2_stabilization_extended": True,
                "prewarmed": True,
                "prewarm_age": 2.4,
                "minimum_measurement_seconds": 5.6,
                "source": "UART8-vitals-24B+GY-614",
                "measured_at": "2026-08-05T15:10:00+08:00",
            }
        )

        response = VitalsSessionModule(gateway=gateway).get("module-diagnostics")

        self.assertTrue(response.stable_core)
        self.assertEqual(response.communication_status, "receiving_protocol_frames")
        self.assertEqual(response.valid_frame_count, 8)
        self.assertEqual(response.contact_frame_count, 6)
        self.assertEqual(response.heart_rate_frame_count, 5)
        self.assertEqual(response.spo2_frame_count, 4)
        self.assertEqual(response.first_heart_rate_frame, 3)
        self.assertEqual(response.first_spo2_frame, 5)
        self.assertTrue(response.spo2_stabilization_extended)
        self.assertTrue(response.prewarmed)
        self.assertEqual(response.prewarm_age, 2.4)
        self.assertEqual(response.minimum_measurement_seconds, 5.6)
        self.assertEqual(response.temperature_source, "gy614_sensor")
        self.assertEqual(response.heart_rate_source, "uart8_sensor")
        self.assertEqual(response.spo2_source, "uart8_sensor")

    def test_replaced_session_keeps_its_lifecycle_reason(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "cancelled",
                "hardware_started": False,
                "communication_status": "receiving_protocol_frames",
                "cancel_reason": "replaced",
            }
        )

        response = VitalsSessionModule(gateway=gateway).get("module-replaced")

        self.assertEqual(response.status, "cancelled")
        self.assertEqual(response.cancel_reason, "replaced")
        self.assertIsNone(response.failure_reason)

    def test_failed_measurement_without_history_stays_failed_without_reference(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": False,
                "mode": "real",
                "status": "failed",
                "hardware_started": True,
                "temperature": 36.5,
                "heart_rate": None,
                "spo2": None,
                "failure_reason": "no_finger",
            }
        )

        response = VitalsSessionModule(gateway=gateway).get("module-no-history")

        self.assertEqual(response.status, "failed")
        self.assertFalse(response.historical_fallback)


if __name__ == "__main__":
    unittest.main()
