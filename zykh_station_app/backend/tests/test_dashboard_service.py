from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.records import TodayPlan  # noqa: E402
from app.schemas.site import SiteProfile  # noqa: E402
from app.services.dashboard_service import DashboardService  # noqa: E402


class StaticStationService:
    def get_site(self) -> SiteProfile:
        return SiteProfile(network_mode="online", ai_mode="cloud")


class StaticQsmClient:
    def get_qsm_status(self) -> SimpleNamespace:
        return SimpleNamespace(
            status_label="可用",
            connected=True,
            error_message=None,
            mode="real",
            vitals={"temperature_c": 36.5},
        )


class StaticMedicineService:
    def list_medicines(self) -> SimpleNamespace:
        return SimpleNamespace(medicines=[SimpleNamespace(stock=1), SimpleNamespace(stock=0)])


class StaticRecordsService:
    plans = [
        TodayPlan(id="plan-0800", time="08:00", medicine_id="medicine-a", medicine="阿司匹林肠溶片", service_user_id="zhangsan", status="已执行", target_user="张三"),
        TodayPlan(id="plan-1830", time="18:30", medicine_id="medicine-b", medicine="硝苯地平控释片", service_user_id="zhangsan", status="待执行", target_user="张三"),
        TodayPlan(id="plan-2000", time="20:00", medicine_id="medicine-c", medicine="蒙脱石散", service_user_id="wangwu", status="待执行", target_user="王五"),
    ]

    def list_today_plans(self) -> list[TodayPlan]:
        return self.plans


class StaticSyncService:
    def get_status(self) -> SimpleNamespace:
        return SimpleNamespace(sync_status="已同步", pending_count=0)


class DashboardServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DashboardService(
            station_service=StaticStationService(),
            qsm_client=StaticQsmClient(),
            medicine_service=StaticMedicineService(),
            records_service=StaticRecordsService(),
            sync_service=StaticSyncService(),
        )

    def test_home_dashboard_returns_all_family_plans_without_identity(self) -> None:
        dashboard = self.service.get_dashboard()

        self.assertEqual(dashboard.medication.pending_people, 2)
        self.assertEqual(dashboard.medication.pending_plans, 2)
        self.assertEqual(dashboard.medication.next_time, "18:30")
        self.assertEqual([plan.target_user for plan in dashboard.medication.plans], ["张三", "张三", "王五"])
        self.assertNotIn("等待确认", dashboard.medication.featured_subject)
        self.assertNotIn("确认使用人", dashboard.medication.featured_medicine)

    def test_explicit_target_filter_remains_available_outside_home(self) -> None:
        dashboard = self.service.get_dashboard(target_user="张三")

        self.assertEqual(len(dashboard.medication.plans), 2)
        self.assertTrue(all(plan.target_user == "张三" for plan in dashboard.medication.plans))


if __name__ == "__main__":
    unittest.main()
