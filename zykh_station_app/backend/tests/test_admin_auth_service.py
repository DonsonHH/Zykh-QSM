from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.admin_auth_service import AdminAuthError, AdminAuthService  # noqa: E402


class AdminAuthServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        AdminAuthService.reset_for_tests()
        self.settings_patch = patch(
            "app.services.admin_auth_service.settings",
            SimpleNamespace(admin_debug_pin="1145", admin_session_minutes=30),
        )
        self.settings_patch.start()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        AdminAuthService.reset_for_tests()

    def test_correct_pin_creates_verifiable_session(self) -> None:
        service = AdminAuthService()
        session = service.create_session("1145", "local-test")

        service.verify(session.token)
        service.revoke(session.token)
        with self.assertRaises(AdminAuthError):
            service.verify(session.token)

    def test_wrong_pin_is_rejected(self) -> None:
        with self.assertRaises(AdminAuthError) as context:
            AdminAuthService().create_session("0000", "local-test")

        self.assertEqual(context.exception.status_code, 401)

    def test_repeated_failures_are_rate_limited(self) -> None:
        service = AdminAuthService()
        for _ in range(5):
            with self.assertRaises(AdminAuthError):
                service.create_session("0000", "limited-client")

        with self.assertRaises(AdminAuthError) as context:
            service.create_session("1145", "limited-client")
        self.assertEqual(context.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
