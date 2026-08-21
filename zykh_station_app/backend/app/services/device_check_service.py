from __future__ import annotations

from ..config import real_dispense_enabled
from ..schemas.device import DeviceCheckResponse
from .qsm_camera_service import QsmCameraService
from .qsm_client import QsmClient
from .fingerprint_service import FingerprintService
from .speech_service import SpeechService


class DeviceCheckService:
    def __init__(
        self,
        qsm_client: QsmClient | None = None,
        qsm_camera: QsmCameraService | None = None,
        fingerprint: FingerprintService | None = None,
        speech: SpeechService | None = None,
    ) -> None:
        self.qsm_client = qsm_client or QsmClient()
        self.qsm_camera = qsm_camera or QsmCameraService()
        self.fingerprint = fingerprint or FingerprintService()
        self.speech = speech or SpeechService(self.qsm_client)

    def check(self) -> DeviceCheckResponse:
        errors: list[str] = []
        warnings: list[str] = []
        recommendations: list[str] = []

        qsm_status = self.qsm_client.get_qsm_status()
        vitals = self.qsm_client.read_vitals()
        camera_status = self.qsm_camera.capabilities()
        speech_status = self.speech.status()
        offline_voice = speech_status.get("offline")
        offline_voice = offline_voice if isinstance(offline_voice, dict) else {}
        fingerprint_status = self.fingerprint.status()

        qsm_status_ok = qsm_status.connected if qsm_status.mode == "real" else True
        vitals_ok = True if qsm_status.mode != "real" else vitals.get("source") == "real"
        camera_ok = camera_status == "available"
        offline_tts_ok = bool(speech_status.get("offline_available"))
        fingerprint_ok = fingerprint_status.ok
        cabinet_light_enabled = real_dispense_enabled()
        cabinet_light = (
            self.qsm_client.cabinet_light_status()
            if cabinet_light_enabled and qsm_status.mode == "real" and qsm_status.connected
            else {}
        )
        cabinet_light_status = str(cabinet_light.get("status") or "unknown")
        cabinet_light_ok = bool(cabinet_light.get("ok")) and cabinet_light_status == "off"
        cabinet_light_cabinet_id = cabinet_light.get("cabinet_id")
        try:
            cabinet_light_cabinet_id = int(cabinet_light_cabinet_id)
        except (TypeError, ValueError):
            cabinet_light_cabinet_id = None
        if cabinet_light_cabinet_id not in {1, 2, 3}:
            cabinet_light_cabinet_id = None

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
        if not offline_tts_ok:
            warnings.append("本地语音暂未就绪。")
            recommendations.append("请运行 scripts/deploy_offline_tts.sh 或检查外设语音资源。")
        if not fingerprint_ok:
            warnings.append("指纹模块暂不可用。")
            recommendations.append("请检查 AS608 USB 连接、指纹网关和 18086 端口转发；取药时可改用面部确认。")
        if not cabinet_light_enabled:
            warnings.append("分类柜亮灯当前未启用真实联动。")
            recommendations.append("真实亮灯需要 DISPENSE_DRY_RUN=false、ENABLE_REAL_DISPENSE=1，并完成取药安全确认。")
        elif qsm_status.mode == "real" and qsm_status.connected and not cabinet_light.get("ok"):
            warnings.append("分类柜控制器状态暂不可用。")
            recommendations.append("请检查 /dev/ttyACM0、115200 串口协议及 QSM 分类柜网关。")
        elif cabinet_light_status.startswith("cabinet_"):
            active_id = cabinet_light_cabinet_id or cabinet_light_status.removeprefix("cabinet_")
            warnings.append(f"{active_id}号柜指示灯仍亮着。")
            recommendations.append("请确认现场取药完成并执行 OFF，待三个分类柜均熄灭后再继续。")
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
            cabinet_light_ok=cabinet_light_ok,
            cabinet_light_status=cabinet_light_status,
            cabinet_light_cabinet_id=cabinet_light_cabinet_id,
            offline_tts_ok=offline_tts_ok,
            offline_tts_engine=str(offline_voice.get("engine") or ""),
            offline_tts_model=str(offline_voice.get("model") or ""),
            offline_tts_status="available" if offline_tts_ok else "unavailable",
            dispense_dry_run=not real_dispense_enabled(),
            errors=errors,
            warnings=warnings,
            recommendations=recommendations,
        )
