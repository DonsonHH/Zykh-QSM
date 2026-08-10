from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.qsm_client import QsmClient  # noqa: E402


class QsmDispenseClientTest(unittest.TestCase):
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
                "13",
                1,
                dry_run=False,
                operation_id="dispense-single-write-001",
            )

        self.assertEqual(request.call_count, 1)
        self.assertFalse(result["ok"])
        self.assertTrue(result["result_unknown"])
        self.assertFalse(result["retry_safe"])


if __name__ == "__main__":
    unittest.main()
