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
from app.services.admin_service import AdminService, AdminServiceError  # noqa: E402
from app.schemas.inquiry import InquirySessionCreateRequest  # noqa: E402
from app.services.inquiry_orchestrator import InquiryOrchestrator  # noqa: E402


class AdminServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "admin.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_audit_records_are_persisted_and_secrets_are_redacted(self) -> None:
        service = AdminService()
        service.audit("test.action", "host", "success", "Authorization: Bearer token-value sk-secret123456")

        record = service.recent_audit(1)[0]
        self.assertEqual(record.action, "test.action")
        self.assertNotIn("token-value", record.detail)
        self.assertNotIn("sk-secret123456", record.detail)

    def test_logs_only_use_allowlisted_sources_and_redact_tokens(self) -> None:
        log = self.root / "backend.log"
        log.write_text("normal\napi_key=top-secret\n", encoding="utf-8")
        sources = {"backend": ("后端服务", log)}
        with patch.object(AdminService, "_log_sources", sources):
            result = AdminService().logs("../../etc/passwd")

        self.assertEqual(result["source"], "backend")
        self.assertIn("api_key=***", result["lines"][-1])

    def test_system_action_rejects_unknown_commands(self) -> None:
        with self.assertRaises(AdminServiceError):
            AdminService().system_action("rm -rf", "anything")

    def test_overview_collects_all_device_statuses_and_network(self) -> None:
        service = AdminService()
        with (
            patch.object(
                service,
                "_json_status",
                side_effect=lambda url: {"ok": True, "status": url.rsplit("/", 1)[-1], "camera_available": True},
            ) as status,
            patch.object(service, "_tcp_status", return_value={"ok": True, "status": "available"}) as gateway,
            patch("app.services.admin_service.NetworkService.status", return_value={"mode": "wifi"}),
            patch.object(service, "_host_metrics", return_value={"hostname": "station"}),
        ):
            result = service.overview()

        self.assertEqual(status.call_count, 3)
        gateway.assert_called_once()
        self.assertTrue(result["devices"]["gateway"]["ok"])
        self.assertTrue(result["devices"]["camera"]["ok"])
        self.assertEqual(result["network"]["mode"], "wifi")

    def test_protected_network_control_forwards_only_physical_switches_and_audits(self) -> None:
        response = SimpleNamespace(warnings=[])
        with patch(
            "app.services.admin_service.SettingsService.update",
            return_value=response,
        ) as update:
            result = AdminService().update_network_settings(
                wifi_enabled=False,
                sim_enabled=True,
            )

        request = update.call_args.args[0]
        self.assertIs(result, response)
        self.assertFalse(request.wifi_enabled)
        self.assertTrue(request.sim_enabled)
        self.assertIsNone(request.network_mode)
        self.assertEqual(AdminService().recent_audit(1)[0].action, "network.update")

    def test_restart_action_uses_only_configured_server_command(self) -> None:
        configured = SimpleNamespace(
            admin_allow_system_actions=True,
            admin_restart_command="fixed-restart-command",
            admin_reboot_command="fixed-reboot-command",
        )
        with (
            patch("app.services.admin_service.settings", configured),
            patch("app.services.admin_service.threading.Thread") as thread,
        ):
            result = AdminService().system_action("restart_app", "RESTART APP")

        self.assertTrue(result["accepted"])
        thread.assert_called_once_with(
            target=AdminService._run_delayed,
            args=("fixed-restart-command",),
            daemon=True,
        )
        thread.return_value.start.assert_called_once_with()

    def test_inquiry_history_keeps_messages_and_structured_debug_state(self) -> None:
        session = InquiryOrchestrator().create_session(
            InquirySessionCreateRequest(service_user_id="zhangsan")
        )

        result = AdminService().inquiry_history()

        self.assertEqual(result["sessions"][0].session_id, session.session_id)
        self.assertEqual(result["sessions"][0].messages[0].role, "assistant")
        self.assertEqual(result["sessions"][0].extracted_information.symptom_dimensions, [])


if __name__ == "__main__":
    unittest.main()
