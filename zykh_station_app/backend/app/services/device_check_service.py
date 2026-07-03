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
            recommendations.append("请确认设备连接、端口转发和外设网关服务，或切回 mock 模式。")
        if qsm_status.mode != "real":
            recommendations.append("当前为 mock 演示模式，真实联调前请手动切换为 real 模式。")
        if not vitals_ok:
            warnings.append("体征模块暂不可用。")
            recommendations.append("请检查体征外设和外设网关体征接口。")
        if not local_camera_ok:
            warnings.append("本机摄像头暂不可用。")
            recommendations.append("请检查本机摄像头模式、设备编号和摄像头连接。")
        if not settings.dispense_dry_run:
            errors.append("DISPENSE_DRY_RUN 未开启。")
            recommendations.append("演示和联调阶段请保持 DISPENSE_DRY_RUN=true。")
        if not recommendations:
            recommendations.append("系统检查通过，可以继续演示主流程。")

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
