from __future__ import annotations

from pydantic import BaseModel


class Medicine(BaseModel):
    id: str
    slot: str
    hardware_slot: int = 0
    barcode: str = ""
    name: str
    category: str
    tags: list[str]
    contraindications: list[str]
    stock: int
    unit: str
    expire_date: str
    image_hint: str
    is_otc: bool
    is_emergency: bool
    safety_note: str


class MedicineListResponse(BaseModel):
    ok: bool = True
    total: int
    warehouse_total: int = 23
    categories: list[str]
    medicines: list[Medicine]


class MedicineDetailResponse(BaseModel):
    ok: bool = True
    medicine: Medicine


class MedicineScanRequest(BaseModel):
    mode: str = "药品识别"
    manual_code: str | None = None


class MedicineScanFrameRequest(BaseModel):
    mode: str = "药品识别"
    image_data: str


class MedicineScanResult(BaseModel):
    ok: bool
    status: str
    image_path: str | None = None
    image_url: str | None = None
    barcode: str | None = None
    medicine_id: str | None = None
    name: str | None = None
    match_percent: int | None = None
    spec: str | None = None
    quantity: str | None = None
    expire_date: str | None = None
    slot: str | None = None
    source: str = "local"
    error_message: str | None = None


class MedicineScanRegisterRequest(BaseModel):
    barcode: str | None = None
    name: str | None = None
    spec: str | None = None
    expire_date: str | None = None
    slot: int | None = None
    stock: int = 1
    unit: str = "盒"
    category: str = "扫码录入"
    safety_note: str | None = None


class MedicineScanRegisterResponse(BaseModel):
    ok: bool
    created: bool
    message: str
    medicine: Medicine | None = None


class MedicineVisualRecognizeRequest(BaseModel):
    image_path: str | None = None


class MedicineVisualRecognizeResponse(BaseModel):
    ok: bool
    source: str
    raw_text: str | None = None
    barcode: str | None = None
    name: str | None = None
    expire_date: str | None = None
    error_message: str | None = None
