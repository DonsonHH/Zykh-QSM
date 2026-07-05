from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.medicine import (
    MedicineDetailResponse,
    MedicineListResponse,
    MedicineScanFrameRequest,
    MedicineScanRegisterRequest,
    MedicineScanRegisterResponse,
    MedicineScanRequest,
    MedicineScanResult,
    MedicineUpdateRequest,
    MedicineUpdateResponse,
    MedicineVisualRecognizeRequest,
    MedicineVisualRecognizeResponse,
)
from ..services.medicine_scan_service import MedicineScanService
from ..services.medicine_service import MedicineService

router = APIRouter(prefix="/api", tags=["medicines"])


@router.get("/medicines", response_model=MedicineListResponse)
def list_medicines() -> MedicineListResponse:
    return MedicineService().list_medicines()


@router.get("/medicines/{medicine_id}", response_model=MedicineDetailResponse)
def get_medicine(medicine_id: str) -> MedicineDetailResponse:
    medicine = MedicineService().get_medicine(medicine_id)
    if medicine is None:
        raise HTTPException(status_code=404, detail="未找到该药品。")
    return MedicineDetailResponse(medicine=medicine)


@router.patch("/medicines/{medicine_id}", response_model=MedicineUpdateResponse)
def update_medicine(medicine_id: str, request: MedicineUpdateRequest) -> MedicineUpdateResponse:
    response = MedicineService().update_medicine(medicine_id, request)
    if response is None:
        raise HTTPException(status_code=404, detail="未找到该药品。")
    return response


@router.post("/medicine/scan", response_model=MedicineScanResult)
def scan_medicine(request: MedicineScanRequest) -> MedicineScanResult:
    return MedicineScanService().scan(request.manual_code)


@router.post("/medicine/scan-frame", response_model=MedicineScanResult)
def scan_medicine_frame(request: MedicineScanFrameRequest) -> MedicineScanResult:
    return MedicineScanService().scan_frame(request.image_data)


@router.post("/medicine/scan/register", response_model=MedicineScanRegisterResponse)
def register_scan_result(request: MedicineScanRegisterRequest) -> MedicineScanRegisterResponse:
    return MedicineService().register_scan_result(request)


@router.post("/medicine/visual-recognize", response_model=MedicineVisualRecognizeResponse)
def visual_recognize_medicine(request: MedicineVisualRecognizeRequest) -> MedicineVisualRecognizeResponse:
    return MedicineScanService().visual_recognize(request.image_path)
