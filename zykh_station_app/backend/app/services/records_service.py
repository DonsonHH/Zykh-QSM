from __future__ import annotations

from ..repositories.device_action_repository import DeviceActionRepository
from ..repositories.dispense_repository import DispenseRepository
from ..repositories.inquiry_repository import InquiryRepository
from ..schemas.records import RecentRecord, RecordsSummary
from .sync_service import SyncService


MOCK_RECORDS = [
    RecentRecord(
        id="mock-vitals-001",
        time="10:20",
        type="体征读取",
        title="体温 35.7℃",
        description="本地设备 mock 体征记录，供弱网场景追踪。",
        target_user="张三",
        status="已记录",
        sync_status="待同步",
    ),
    RecentRecord(
        id="mock-inquiry-001",
        time="10:16",
        type="AI应急问询",
        title="低风险问询完成",
        description="已生成风险提示、药品信息匹配和禁忌核验结果。",
        target_user="王五",
        status="已评估",
        sync_status="待同步",
    ),
    RecentRecord(
        id="mock-scan-001",
        time="10:12",
        type="药品扫码",
        title="药盒条码识别",
        description="识别站点药品信息并保存在本地记录。",
        target_user="李四",
        status="已记录",
        sync_status="待同步",
    ),
    RecentRecord(
        id="mock-dispense-001",
        time="10:05",
        type="取药确认",
        title="蒙脱石散 dry-run",
        description="完成取药确认记录，本阶段未真实出药。",
        target_user="王五",
        status="已记录",
        sync_status="待同步",
    ),
    RecentRecord(
        id="mock-sync-001",
        time="09:20",
        type="同步状态",
        title="弱网本地保存",
        description="网络不稳定时先保存到本地同步队列。",
        target_user="站点",
        status="本地保存",
        sync_status="待同步",
    ),
]


class RecordsService:
    def __init__(
        self,
        inquiry_repository: InquiryRepository | None = None,
        dispense_repository: DispenseRepository | None = None,
        device_action_repository: DeviceActionRepository | None = None,
        sync_service: SyncService | None = None,
    ) -> None:
        self.inquiry_repository = inquiry_repository or InquiryRepository()
        self.dispense_repository = dispense_repository or DispenseRepository()
        self.device_action_repository = device_action_repository or DeviceActionRepository()
        self.sync_service = sync_service or SyncService()

    def get_summary(self) -> RecordsSummary:
        sync_status = self.sync_service.get_status()
        return RecordsSummary(
            today_service_users=3,
            pending_sync_count=sync_status.pending_count,
            local_record_count=387
            + len(self.inquiry_repository.list_records())
            + len(self.dispense_repository.list_records())
            + len(self.device_action_repository.list_records()),
            today_plan_count=3,
        )

    def get_recent_records(self) -> list[RecentRecord]:
        sync_status = self.sync_service.get_status()
        records = self._mock_records(sync_status.sync_status)
        inquiry_records = self._inquiry_records(sync_status.sync_status)
        dispense_records = self._dispense_records(sync_status.sync_status)
        device_records = self._device_records(sync_status.sync_status)
        if inquiry_records:
            records = self._replace_record_type(records, "AI应急问询", inquiry_records[0])
        if dispense_records:
            records = self._replace_record_type(records, "取药确认", dispense_records[0])
        replaced_device_types: set[str] = set()
        for device_record in device_records:
            if device_record.type in replaced_device_types:
                continue
            records = self._replace_record_type(records, device_record.type, device_record)
            replaced_device_types.add(device_record.type)
        return records[:5]

    def _inquiry_records(self, sync_status: str) -> list[RecentRecord]:
        return [
            RecentRecord(
                id=record.inquiry_id,
                time=self._time_part(record.created_at),
                type="AI应急问询",
                title=record.risk_label,
                description=f"{record.symptoms_summary[:38]}",
                target_user="王五",
                status="已评估",
                sync_status=sync_status,
            )
            for record in self.inquiry_repository.list_records()
        ]

    def _dispense_records(self, sync_status: str) -> list[RecentRecord]:
        return [
            RecentRecord(
                id=record.id,
                time=self._time_part(record.created_at),
                type="取药确认",
                title=record.medicine_name,
                description=f"dry-run 记录：{record.quantity}{record.unit}，未真实出药。",
                target_user="张三",
                status="已记录",
                sync_status=sync_status,
            )
            for record in self.dispense_repository.list_records()
        ]

    def _device_records(self, sync_status: str) -> list[RecentRecord]:
        return [
            RecentRecord(
                id=record.id,
                time=self._time_part(record.created_at),
                type=record.type,
                title=record.title,
                description=record.description,
                target_user=record.target_user,
                status=record.status,
                sync_status=sync_status,
            )
            for record in self.device_action_repository.list_records()
        ]

    def _mock_records(self, sync_status: str) -> list[RecentRecord]:
        if sync_status == "已同步":
            return [record.model_copy(update={"sync_status": "已同步"}) for record in MOCK_RECORDS]
        return MOCK_RECORDS

    @staticmethod
    def _replace_record_type(records: list[RecentRecord], record_type: str, replacement: RecentRecord) -> list[RecentRecord]:
        return [replacement if record.type == record_type else record for record in records]

    @staticmethod
    def _time_part(value: str) -> str:
        if " " in value:
            return value.split(" ", 1)[1][:5]
        return value[:5] or "--:--"
