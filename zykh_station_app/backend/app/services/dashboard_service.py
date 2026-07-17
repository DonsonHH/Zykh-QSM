from __future__ import annotations

from ..config import real_dispense_enabled, settings
from ..core.constants import SAFETY_NOTICE
from ..db import now_text
from ..schemas.dashboard import (
    DashboardPayload,
    InquirySummary,
    MedicationPlanItem,
    MedicationSummary,
    QuickAction,
    StationStat,
)
from ..schemas.status import ApiStatus, StatusChip
from .qsm_client import QsmClient
from .medicine_service import MedicineService
from .records_service import RecordsService
from .station_service import StationService
from .sync_service import SyncService


class DashboardService:
    def __init__(
        self,
        station_service: StationService | None = None,
        qsm_client: QsmClient | None = None,
        medicine_service: MedicineService | None = None,
        records_service: RecordsService | None = None,
        sync_service: SyncService | None = None,
    ) -> None:
        self.station_service = station_service or StationService()
        self.qsm_client = qsm_client or QsmClient()
        self.medicine_service = medicine_service or MedicineService()
        self.records_service = records_service or RecordsService()
        self.sync_service = sync_service or SyncService()

    def get_status(self) -> ApiStatus:
        site = self.station_service.get_site()
        qsm = self.qsm_client.get_qsm_status()
        sync_status = self.sync_service.get_status()
        chips = [
            StatusChip(id="network", label="网络", value=self._network_label(site.network_mode), tone="warn"),
            StatusChip(id="ai", label="AI模式", value=self._ai_label(site.ai_mode), tone="warn"),
            StatusChip(id="device", label="设备", value=qsm.status_label, tone="good" if qsm.connected else "warn"),
            StatusChip(id="sync", label="同步", value=sync_status.sync_status, tone="good" if sync_status.pending_count == 0 and sync_status.sync_status != "未配置" else "warn"),
        ]
        return ApiStatus(
            network_mode=site.network_mode,
            ai_mode=site.ai_mode,
            device_status=qsm.status_label,
            sync_status=sync_status.sync_status,
            qsm_mode=qsm.mode,
            qsm_connected=qsm.connected,
            qsm_error_message=qsm.error_message,
            dry_run=not real_dispense_enabled(),
            chips=chips,
        )

    def get_dashboard(self, target_user: str | None = None) -> DashboardPayload:
        site = self.station_service.get_site()
        status = self.get_status()
        qsm = self.qsm_client.get_qsm_status()
        medicines = self.medicine_service.list_medicines().medicines
        plans = self.records_service.list_today_plans(due_only=True)
        if target_user:
            plans = [plan for plan in plans if plan.target_user == target_user]
        pending_plans = [plan for plan in plans if plan.status == "待执行"]
        next_plan = pending_plans[0] if pending_plans else None
        temperature = qsm.vitals.get("temperature_c")
        return DashboardPayload(
            site=site,
            chips=status.chips,
            medication=MedicationSummary(
                pending_people=len({plan.target_user for plan in pending_plans}),
                pending_plans=len(pending_plans),
                next_time=next_plan.time if next_plan else "--:--",
                featured_subject=next_plan.target_user if next_plan else (target_user or "家庭药柜"),
                featured_medicine=next_plan.medicine if next_plan else "今日暂无待执行计划",
                plans=[
                    MedicationPlanItem(
                        id=plan.id,
                        time=plan.time,
                        timing_label=plan.timing_label,
                        medicine=plan.medicine,
                        status=plan.status,
                        target_user=plan.target_user,
                        medicine_id=plan.medicine_id,
                        service_user_id=plan.service_user_id,
                        dose=plan.dose,
                        frequency_label=plan.frequency_label,
                        due_today=plan.due_today,
                        next_due_date=plan.next_due_date,
                    )
                    for plan in plans
                ],
            ),
            inquiry=InquirySummary(
                title="AI应急问询",
                description="结合体征、症状和家庭药柜库存，给出风险提示与药品信息匹配。",
                action_label="开始问询",
            ),
            quick_actions=[
                QuickAction(id="scan", title="扫码识别", subtitle="药盒 / 条码 / 药柜编号", tone="green"),
                QuickAction(id="vitals", title="身体状态测量", subtitle="额温 / 心率 / 血氧", tone="blue"),
                QuickAction(id="records", title="服务记录", subtitle="本地记录与同步", tone="purple"),
            ],
            stats=[
                StationStat(id="cabinet", label="药柜", value=f"{sum(1 for medicine in medicines if medicine.stock > 0)}/23", tone="blue"),
                StationStat(
                    id="temperature",
                    label="体温",
                    value=f"{float(temperature):.1f}" if temperature is not None else "未测量",
                    unit="℃" if temperature is not None else "",
                    tone="cyan",
                ),
                StationStat(id="device", label="设备", value=qsm.status_label, tone="soft"),
            ],
            safety_notice=SAFETY_NOTICE,
            updated_at=now_text(),
        )

    @staticmethod
    def _network_label(value: str) -> str:
        return {"online": "在线", "weak": "弱网", "offline": "离线"}.get(value, "弱网")

    @staticmethod
    def _ai_label(value: str) -> str:
        return {
            "cloud": "云端",
            "local": "离线模型",
            "local_llm": "离线模型",
            "rules": "安全规则",
            "rules_fallback": "安全规则",
        }.get(value, "安全规则")

    @staticmethod
    def _sync_label(value: str) -> str:
        return {"synced": "已同步", "pending": "待同步", "offline": "本地保存"}.get(value, "已同步")
