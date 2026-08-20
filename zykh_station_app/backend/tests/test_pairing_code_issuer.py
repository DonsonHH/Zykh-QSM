from __future__ import annotations

import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.services.pairing_code_issuer import (  # noqa: E402
    CAREGIVER_READ_PERMISSIONS,
    PairingCodeIssueError,
    PairingCodeIssueRequest,
    PairingCodeIssuer,
    PairingCodePlaintextOnce,
)


class PairingCodeIssuerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pairing.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_issue_returns_plaintext_once_and_publishes_only_its_hash_and_scope(self) -> None:
        published: list[dict[str, object]] = []

        def publish(payload: dict[str, object]) -> dict[str, object]:
            published.append(payload)
            return {
                "expiresAt": "2026-08-10T12:10:00+08:00",
                "serviceUserScopes": ["wang-nainai"],
                "serviceUserGenerations": {"wang-nainai": "senior-demo-v1"},
                "role": "CAREGIVER",
                "permissions": list(CAREGIVER_READ_PERMISSIONS),
                "status": "UNUSED",
            }

        issuer = PairingCodeIssuer(
            publish=publish,
            token_factory=lambda: "ZYKH-QSM-PAIR-20260810-A1",
            now=lambda: datetime.fromisoformat("2026-08-10T12:00:00+08:00"),
        )

        result = issuer.issue(
            PairingCodeIssueRequest(service_user_ids=("wang-nainai",), ttl_minutes=10)
        )

        self.assertEqual(result.pairing_code, "ZYKH-QSM-PAIR-20260810-A1")
        self.assertEqual(result.expires_at, "2026-08-10T12:10:00+08:00")
        self.assertEqual(result.ttl_seconds, 600)
        self.assertEqual(result.service_user_ids, ("wang-nainai",))
        self.assertIn("CREATE_COMMAND", CAREGIVER_READ_PERMISSIONS)
        self.assertEqual(
            published,
            [
                {
                    "codeHash": "313cbcaa996cfeb1d82bf42258227129db77d12a54bead2641d9a002c0cb3111",
                    "serviceUserScopes": ["wang-nainai"],
                    "serviceUserGenerations": {"wang-nainai": "senior-demo-v1"},
                    "ttlSeconds": 600,
                }
            ],
        )
        self.assertNotIn("pairingCode", published[0])
        self.assertNotIn("role", published[0])
        self.assertNotIn("permissions", published[0])

    def test_issue_rejects_ttl_outside_five_to_fifteen_minutes(self) -> None:
        published: list[dict[str, object]] = []
        issuer = PairingCodeIssuer(publish=published.append)

        for ttl_minutes in (4, 16):
            with self.subTest(ttl_minutes=ttl_minutes):
                with self.assertRaisesRegex(PairingCodeIssueError, "5 到 15"):
                    issuer.issue(
                        PairingCodeIssueRequest(
                            service_user_ids=("wang-nainai",),
                            ttl_minutes=ttl_minutes,
                        )
                    )

        self.assertEqual(published, [])

    def test_issue_rejects_archived_scope_and_a_weak_generated_token(self) -> None:
        published: list[dict[str, object]] = []
        with db.connect() as conn:
            conn.execute("UPDATE service_users SET archived=1 WHERE id='wang-nainai'")
        issuer = PairingCodeIssuer(publish=published.append)
        with self.assertRaisesRegex(PairingCodeIssueError, "不存在或已停用"):
            issuer.issue(PairingCodeIssueRequest(service_user_ids=("wang-nainai",)))

        with self.assertRaisesRegex(PairingCodeIssueError, "安全的配对码"):
            PairingCodeIssuer(
                publish=published.append,
                token_factory=lambda: "123456",
            ).issue(PairingCodeIssueRequest(service_user_ids=("li-yeye",)))

        self.assertEqual(published, [])

    def test_default_generator_requests_256_bits_of_csprng_input(self) -> None:
        def publish(_: dict[str, object]) -> dict[str, object]:
            return {
                "expiresAt": "2026-08-10T12:10:00+08:00",
                "serviceUserScopes": ["wang-nainai"],
                "serviceUserGenerations": {"wang-nainai": "senior-demo-v1"},
                "role": "CAREGIVER",
                "permissions": list(CAREGIVER_READ_PERMISSIONS),
                "status": "UNUSED",
            }

        with patch(
            "app.services.pairing_code_issuer.secrets.token_urlsafe",
            return_value="A" * 43,
        ) as token_urlsafe:
            result = PairingCodeIssuer(
                publish=publish,
                now=lambda: datetime.fromisoformat("2026-08-10T12:00:00+08:00"),
            ).issue(
                PairingCodeIssueRequest(service_user_ids=("wang-nainai",))
            )

        token_urlsafe.assert_called_once_with(32)
        self.assertEqual(result.pairing_code, "A" * 43)

    def test_issue_rejects_a_cloud_response_for_a_different_scope(self) -> None:
        issuer = PairingCodeIssuer(
            publish=lambda _: {
                "expiresAt": "2026-08-10T12:10:00+08:00",
                "serviceUserScopes": ["li-yeye"],
            },
            token_factory=lambda: "ZYKH-QSM-PAIR-20260810-A1",
        )

        with self.assertRaisesRegex(PairingCodeIssueError, "授权对象"):
            issuer.issue(
                PairingCodeIssueRequest(service_user_ids=("wang-nainai",), ttl_minutes=10)
            )

    def test_issue_rejects_a_cloud_response_with_elevated_authority(self) -> None:
        issuer = PairingCodeIssuer(
            publish=lambda _: {
                "expiresAt": "2026-08-10T12:10:00+08:00",
                "serviceUserScopes": ["wang-nainai"],
                "serviceUserGenerations": {"wang-nainai": "senior-demo-v1"},
                "role": "OWNER",
                "permissions": [*CAREGIVER_READ_PERMISSIONS, "CREATE_COMMAND"],
                "status": "UNUSED",
            },
            token_factory=lambda: "ZYKH-QSM-PAIR-20260810-A1",
            now=lambda: datetime.fromisoformat("2026-08-10T12:00:00+08:00"),
        )

        with self.assertRaisesRegex(PairingCodeIssueError, "权限"):
            issuer.issue(
                PairingCodeIssueRequest(service_user_ids=("wang-nainai",), ttl_minutes=10)
            )

    def test_issue_rejects_an_unparseable_or_overlong_cloud_expiry(self) -> None:
        def response(expires_at: str) -> dict[str, object]:
            return {
                "expiresAt": expires_at,
                "serviceUserScopes": ["wang-nainai"],
                "serviceUserGenerations": {"wang-nainai": "senior-demo-v1"},
                "role": "CAREGIVER",
                "permissions": list(CAREGIVER_READ_PERMISSIONS),
                "status": "UNUSED",
            }

        for expires_at in ("not-a-time", "2026-08-10T13:00:00+08:00"):
            with self.subTest(expires_at=expires_at):
                issuer = PairingCodeIssuer(
                    publish=lambda _, value=expires_at: response(value),
                    token_factory=lambda: "ZYKH-QSM-PAIR-20260810-A1",
                    now=lambda: datetime.fromisoformat("2026-08-10T12:00:00+08:00"),
                )
                with self.assertRaisesRegex(PairingCodeIssueError, "有效期"):
                    issuer.issue(
                        PairingCodeIssueRequest(
                            service_user_ids=("wang-nainai",),
                            ttl_minutes=10,
                        )
                    )

    def test_admin_issue_route_reuses_admin_auth_and_has_a_constrained_request(self) -> None:
        from app.schemas.admin import AdminPairingCodeIssueRequest

        request = AdminPairingCodeIssueRequest(
            service_user_ids=["wang-nainai"],
            ttl_minutes=10,
        )
        self.assertEqual(request.service_user_ids, ["wang-nainai"])
        router_source = (BACKEND_ROOT / "app" / "routers" / "admin.py").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            router_source,
            re.compile(
                r'@router\.post\("/pairing-codes"[^\n]*\)\s*'
                r'def admin_issue_pairing_code\([\s\S]{0,180}?'
                r'_: str = Depends\(require_admin\)',
            ),
        )
        self.assertIn("PairingCodeIssuer().issue(", router_source)

    def test_admin_issue_route_audits_scope_without_recording_the_plaintext_code(self) -> None:
        from app.routers.admin import admin_issue_pairing_code
        from app.schemas.admin import AdminPairingCodeIssueRequest

        request = AdminPairingCodeIssueRequest(
            service_user_ids=["wang-nainai"],
            ttl_minutes=10,
        )
        plaintext = "ZYKH-QSM-PAIR-20260810-A1"
        with (
            patch("app.routers.admin.PairingCodeIssuer") as issuer_type,
            patch("app.routers.admin.AdminService") as admin_service_type,
        ):
            issuer_type.return_value.issue.return_value = PairingCodePlaintextOnce(
                pairing_code=plaintext,
                expires_at="2026-08-10T12:10:00+08:00",
                ttl_seconds=600,
                service_user_ids=("wang-nainai",),
            )

            response = admin_issue_pairing_code(request, "admin-session")

        self.assertEqual(response.pairing_code, plaintext)
        admin_service_type.return_value.audit.assert_called_once()
        audit_arguments = repr(admin_service_type.return_value.audit.call_args)
        self.assertIn("pairing-code.issue", audit_arguments)
        self.assertIn("wang-nainai", audit_arguments)
        self.assertNotIn(plaintext, audit_arguments)


if __name__ == "__main__":
    unittest.main()
