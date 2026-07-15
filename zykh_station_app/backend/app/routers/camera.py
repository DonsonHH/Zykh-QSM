from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from ..db import now_text
from ..repositories.device_action_repository import DeviceActionRecord, DeviceActionRepository
from ..services.qsm_camera_service import QsmCameraService

router = APIRouter(prefix="/api/camera", tags=["camera"])


@router.post("/capture")
def capture_camera() -> dict[str, object]:
    payload = QsmCameraService().capture()
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


@router.get("/stream")
def camera_stream() -> StreamingResponse:
    service = QsmCameraService()
    response, content_type, error = service.open_stream()
    if response is None:
        raise HTTPException(status_code=503, detail=error or "外设摄像头视频流不可用。")
    return StreamingResponse(
        service.stream_chunks(response),
        media_type=content_type,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "X-Accel-Buffering": "no"},
    )


@router.get("/image/latest")
def latest_camera_image() -> FileResponse:
    service = QsmCameraService()
    path = service.latest_frame(max_age_seconds=60)
    if path is None:
        raise HTTPException(status_code=404, detail="当前没有可用摄像头画面。")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
