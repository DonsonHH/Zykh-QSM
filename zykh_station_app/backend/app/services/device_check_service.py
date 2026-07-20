from __future__ import annotations

from ..config import real_dispense_enabled
from ..schemas.device import DeviceCheckResponse
from .qsm_camera_service import QsmCameraService
from .qsm_client import QsmClient
from .local_ai_client import LocalAiClient
from .local_inquiry_status import local_inquiry_status
from .fingerprint_service import FingerprintService


class DeviceCheckService:
    def __init__(
        self,
        qsm_client: QsmClient | None = None,
        qsm_camera: QsmCameraService | None = None,
        local_ai: LocalAiClient | None = None,
        fingerprint: FingerprintService | None = None,
    ) -> None:
        self.qsm_client = qsm_client or QsmClient()
        self.qsm_camera = qsm_camera or QsmCameraService()
        self.local_ai = local_ai or LocalAiClient()
        self.fingerprint = fingerprint or FingerprintService()

    def check(self) -> DeviceCheckResponse:
        errors: list[str] = []
        warnings: list[str] = []
        recommendations: list[str] = []

        qsm_status = self.qsm_client.get_qsm_status()
        vitals = self.qsm_client.read_vitals()
        camera_status = self.qsm_camera.capabilities()
        local_ai_status = local_inquiry_status(self.local_ai.status())
        fingerprint_status = self.fingerprint.status()

        qsm_status_ok = qsm_status.connected if qsm_status.mode == "real" else True
        vitals_ok = True if qsm_status.mode != "real" else vitals.get("source") == "real"
        camera_ok = camera_status == "available"
        local_ai_ok = bool(local_ai_status.get("ready"))
        fingerprint_ok = fingerprint_status.ok

        if qsm_status.mode == "real" and not qsm_status.connected:
            warnings.append("外设网关未连接。")
            recommendations.append("请确认设备连接、端口转发和外设网关服务。")
        if qsm_status.mode != "real":
            warnings.append("当前未启用真实外设模式。")
            recommendations.append("请设置 QSM_MODE=real。")
        if not vitals_ok:
            warnings.append("体征模块暂不可用。")
            recommendations.append("请检查体征外设和外设网关体征接口。")
        if not camera_ok:
            warnings.append("外设摄像头暂不可用。")
            recommendations.append("请检查外设摄像头连接和摄像头网关服务。")
        if not local_ai_ok:
            warnings.append("离线问询暂未就绪。")
            recommendations.append("请运行 scripts/deploy_offline_ai.sh 或检查 QSM 模型进程。")
        if not fingerprint_ok:
            warnings.append("指纹模块暂不可用。")
            recommendations.append("请检查 AS608 USB 连接、指纹网关和 18086 端口转发；取药时可改用面部确认。")
        if not real_dispense_enabled():
            warnings.append("开柜当前未启用真实联动。")
            recommendations.append("真实开柜需要 DISPENSE_DRY_RUN=false、ENABLE_REAL_DISPENSE=1，并完成取药安全确认。")
        if not recommendations:
            recommendations.append("系统检查通过，可以继续真实外设流程。")

        return DeviceCheckResponse(
            ok=len(errors) == 0,
            qsm_mode=qsm_status.mode,
            qsm_connected=qsm_status.connected,
            qsm_base_url=qsm_status.base_url,
            qsm_status_ok=qsm_status_ok,
            vitals_ok=vitals_ok,
            # Kept for API compatibility; these fields now describe the QSM camera.
            local_camera_ok=camera_ok,
            local_camera_mode="qsm",
            local_camera_status=camera_status,
            fingerprint_ok=fingerprint_ok,
            fingerprint_status=fingerprint_status.status,
            fingerprint_bound_users=fingerprint_status.bound_users,
            local_ai_ok=local_ai_ok,
            local_ai_model=str(local_ai_status.get("model") or ""),
            local_ai_status=str(local_ai_status.get("status") or "unavailable"),
            dispense_dry_run=not real_dispense_enabled(),
            errors=errors,
            warnings=warnings,
            recommendations=recommendations,
        )
