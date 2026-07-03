from __future__ import annotations

from pydantic import BaseModel


class Medicine(BaseModel):
    id: str
    slot: str
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
