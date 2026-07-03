from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.medicine import (
    MedicineDetailResponse,
    MedicineListResponse,
    MedicineScanRequest,
    MedicineScanResult,
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


@router.post("/medicine/scan", response_model=MedicineScanResult)
def scan_medicine(request: MedicineScanRequest) -> MedicineScanResult:
    return MedicineScanService().scan(request.manual_code)


@router.post("/medicine/visual-recognize", response_model=MedicineVisualRecognizeResponse)
def visual_recognize_medicine(request: MedicineVisualRecognizeRequest) -> MedicineVisualRecognizeResponse:
    return MedicineScanService().visual_recognize(request.image_path)
