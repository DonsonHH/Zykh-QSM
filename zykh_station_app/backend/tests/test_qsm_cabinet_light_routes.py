from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.routers.qsm import qsm_cabinet_light_off, qsm_cabinet_light_status  # noqa: E402


class QsmCabinetLightRoutesTest(unittest.TestCase):
    def test_off_route_only_reports_success_after_gateway_confirms_off(self) -> None:
        client = Mock()
        client.cabinet_light_off.return_value = {
            "ok": True,
            "mode": "real",
            "result": "success",
            "status": "off",
            "detail": "三个分类柜的指示灯均已关闭。",
            "result_unknown": False,
            "retry_safe": True,
        }
        with patch("app.routers.qsm.QsmClient", return_value=client):
            response = qsm_cabinet_light_off()

        self.assertTrue(response.ok)
        self.assertEqual(response.status, "off")
        self.assertEqual(response.message, "三个分类柜的指示灯均已关闭。")
        client.cabinet_light_off.assert_called_once_with()

    def test_status_route_preserves_active_cabinet(self) -> None:
        client = Mock()
        client.cabinet_light_status.return_value = {
            "ok": True,
            "mode": "real",
            "result": "success",
            "status": "cabinet_3",
            "cabinet_id": 3,
            "detail": "3 号分类柜指示灯当前亮起。",
        }
        with patch("app.routers.qsm.QsmClient", return_value=client):
            response = qsm_cabinet_light_status()

        self.assertTrue(response.ok)
        self.assertEqual(response.status, "cabinet_3")
        self.assertEqual(response.cabinet_id, 3)
        client.cabinet_light_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
