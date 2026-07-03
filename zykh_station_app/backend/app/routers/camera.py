from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter

from ..db import now_text
from ..repositories.device_action_repository import DeviceActionRecord, DeviceActionRepository
from ..services.local_camera import LocalCameraService

router = APIRouter(prefix="/api/camera", tags=["camera"])


@router.post("/capture")
def capture_camera() -> dict[str, object]:
    payload = LocalCameraService().capture()
    DeviceActionRepository().append(
        DeviceActionRecord(
            id=f"device-{uuid4().hex[:12]}",
            created_at=now_text(),
            type="摄像头拍照",
            title="摄像头拍照" if payload.get("ok") else "摄像头暂不可用",
            description=str(payload.get("image_path") or payload.get("error_message") or "摄像头动作已记录。"),
            status="已记录" if payload.get("ok") else "暂不可用",
        )
    )
    return payload
