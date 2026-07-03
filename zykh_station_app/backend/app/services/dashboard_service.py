from __future__ import annotations

from ..config import settings
from ..core.constants import SAFETY_NOTICE
from ..db import now_text
from ..schemas.dashboard import (
    DashboardPayload,
    InquirySummary,
    MedicationSummary,
    QuickAction,
    StationStat,
)
from ..schemas.status import ApiStatus, StatusChip
from .qsm_client import QsmClient
from .station_service import StationService


class DashboardService:
    def __init__(
        self,
        station_service: StationService | None = None,
        qsm_client: QsmClient | None = None,
    ) -> None:
        self.station_service = station_service or StationService()
        self.qsm_client = qsm_client or QsmClient()

    def get_status(self) -> ApiStatus:
        site = self.station_service.get_site()
        qsm = self.qsm_client.get_qsm_status()
        chips = [
            StatusChip(id="network", label="网络", value=self._network_label(site.network_mode), tone="warn"),
            StatusChip(id="ai", label="AI模式", value=self._ai_label(site.ai_mode), tone="warn"),
            StatusChip(id="device", label="设备", value=qsm.status_label, tone="soft"),
            StatusChip(id="sync", label="同步", value=self._sync_label(site.sync_status), tone="good"),
        ]
        return ApiStatus(
            network_mode=site.network_mode,
            ai_mode=site.ai_mode,
            device_status=qsm.status_label,
            sync_status=site.sync_status,
            dry_run=settings.dispense_dry_run,
            chips=chips,
        )

    def get_dashboard(self) -> DashboardPayload:
        site = self.station_service.get_site()
        status = self.get_status()
        qsm = self.qsm_client.get_qsm_status()
        temperature = qsm.vitals.get("temperature_c") or 35.7
        return DashboardPayload(
            site=site,
            chips=status.chips,
            medication=MedicationSummary(
                pending_people=3,
                pending_plans=5,
                next_time="08:00",
                featured_subject="张三",
                featured_medicine="阿司匹林肠溶片",
            ),
            inquiry=InquirySummary(
                title="AI应急问询",
                description="整理症状和禁忌信息，给出风险提示与药品信息匹配。",
                action_label="开始问询",
            ),
            quick_actions=[
                QuickAction(id="scan", title="扫码识别", subtitle="药盒 / 条码 / 站点码", tone="green"),
                QuickAction(id="medicines", title="站点药品", subtitle="查看库存与说明", tone="blue"),
                QuickAction(id="records", title="服务记录", subtitle="本地记录与同步", tone="purple"),
            ],
            stats=[
                StationStat(id="cabinet", label="药柜", value="8/23", tone="blue"),
                StationStat(id="temperature", label="体温", value=f"{float(temperature):.1f}", unit="℃", tone="cyan"),
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
        return {"cloud": "云端", "local": "本地", "rules": "规则兜底"}.get(value, "规则兜底")

    @staticmethod
    def _sync_label(value: str) -> str:
        return {"synced": "已同步", "pending": "待同步", "offline": "本地保存"}.get(value, "已同步")
