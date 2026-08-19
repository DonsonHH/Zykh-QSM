from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.qsm_client import QsmClient  # noqa: E402


class QsmDispenseClientTest(unittest.TestCase):
    def test_physical_dispense_posts_one_v2_cabinet_without_legacy_slot_or_control_code(self) -> None:
        client = QsmClient(mode="real", base_url="http://qsm.invalid")

        with patch.object(
            client,
            "_request_json",
            return_value=({"ok": True, "result": "success"}, None),
        ) as request:
            result = client.dispense(
                2,
                1,
                dry_run=False,
                operation_id="cabinet-v2-single-write-001",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["cabinet_id"], 2)
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(
            payload,
            {
                "cabinet_id": 2,
                "quantity": 1,
                "operation_id": "cabinet-v2-single-write-001",
            },
        )
        self.assertNotIn("slot", payload)
        self.assertNotIn("control_code", payload)

    def test_physical_dispense_never_reposts_with_another_body_format_after_an_unknown_result(self) -> None:
        client = QsmClient(mode="real", base_url="http://qsm.invalid")
        responses = [
            ({}, "外设网关返回空响应。"),
            ({"ok": True, "result": "success"}, None),
        ]

        with patch.object(
            client,
            "_single_request_json",
            side_effect=responses,
        ) as request:
            result = client.dispense(
                2,
                1,
                dry_run=False,
                operation_id="dispense-single-write-001",
            )

        self.assertEqual(request.call_count, 1)
        self.assertFalse(result["ok"])
        self.assertTrue(result["result_unknown"])
        self.assertFalse(result["retry_safe"])

    def test_cabinet_light_off_posts_exactly_once_to_the_v2_gateway(self) -> None:
        client = QsmClient(mode="real", base_url="http://qsm.invalid")

        with patch.object(
            client,
            "_request_json",
            return_value=({"ok": True, "result": "success", "status": "off"}, None),
        ) as request:
            result = client.cabinet_light_off()

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "off")
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], "/api/cabinet/light/off")
        self.assertEqual(request.call_args.kwargs["method"], "POST")
        self.assertEqual(request.call_args.kwargs["payload"], {})
        self.assertEqual(request.call_args.kwargs["body_format"], "json")

    def test_cabinet_light_off_does_not_claim_success_after_transport_error(self) -> None:
        client = QsmClient(mode="real", base_url="http://qsm.invalid")

        with patch.object(
            client,
            "_request_json",
            return_value=({}, "外设网关连接超时。"),
        ):
            result = client.cabinet_light_off()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["result_unknown"])
        self.assertTrue(result["retry_safe"])

    def test_cabinet_light_status_is_a_read_only_get(self) -> None:
        client = QsmClient(mode="real", base_url="http://qsm.invalid")

        with patch.object(
            client,
            "_request_json",
            return_value=({"ok": True, "status": "cabinet_3", "cabinet_id": 3}, None),
        ) as request:
            result = client.cabinet_light_status()

        self.assertTrue(result["ok"])
        self.assertEqual(result["cabinet_id"], 3)
        request.assert_called_once_with("/api/cabinet/light/status", method="GET")


if __name__ == "__main__":
    unittest.main()
