from __future__ import annotations

from ..config import settings
from ..schemas.device import DeviceCheckResponse
from .local_camera import LocalCameraService
from .qsm_client import QsmClient


class DeviceCheckService:
    def __init__(
        self,
        qsm_client: QsmClient | None = None,
        local_camera: LocalCameraService | None = None,
    ) -> None:
        self.qsm_client = qsm_client or QsmClient()
        self.local_camera = local_camera or LocalCameraService()

    def check(self) -> DeviceCheckResponse:
        errors: list[str] = []
        warnings: list[str] = []
        recommendations: list[str] = []

        qsm_status = self.qsm_client.get_qsm_status()
        vitals = self.qsm_client.read_vitals()
        camera = self.local_camera.check()

        qsm_status_ok = qsm_status.connected if qsm_status.mode == "real" else True
        vitals_ok = True if qsm_status.mode != "real" else vitals.get("source") == "real"
        local_camera_ok = bool(camera.get("ok"))

        if qsm_status.mode == "real" and not qsm_status.connected:
            warnings.append("外设网关未连接。")
            recommendations.append("请确认设备连接、端口转发和外设网关服务。")
        if qsm_status.mode != "real":
            warnings.append("当前未启用真实外设模式。")
            recommendations.append("请设置 QSM_MODE=real。")
        if not vitals_ok:
            warnings.append("体征模块暂不可用。")
            recommendations.append("请检查体征外设和外设网关体征接口。")
        if not local_camera_ok:
            warnings.append("本机摄像头暂不可用。")
            recommendations.append("请检查本机摄像头模式、设备编号和摄像头连接。")
        if settings.dispense_dry_run:
            warnings.append("取药当前为 dry-run，未启用真实外设出药。")
            recommendations.append("如需真实取药，请设置 DISPENSE_DRY_RUN=false 并先确认安全仓位。")
        if not recommendations:
            recommendations.append("系统检查通过，可以继续真实外设流程。")

        return DeviceCheckResponse(
            ok=len(errors) == 0,
            qsm_mode=qsm_status.mode,
            qsm_connected=qsm_status.connected,
            qsm_base_url=qsm_status.base_url,
            qsm_status_ok=qsm_status_ok,
            vitals_ok=vitals_ok,
            local_camera_ok=local_camera_ok,
            local_camera_mode=str(camera.get("mode", settings.local_camera_mode)),
            local_camera_status=str(camera.get("status", "unavailable")),
            dispense_dry_run=settings.dispense_dry_run,
            errors=errors,
            warnings=warnings,
            recommendations=recommendations,
        )
