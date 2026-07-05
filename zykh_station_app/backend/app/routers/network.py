from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.network_service import NetworkService

router = APIRouter(prefix="/api/network", tags=["network"])


class NetworkModeRequest(BaseModel):
    mode: str


@router.get("/status")
def network_status() -> dict[str, object]:
    return NetworkService().status()


@router.post("/mode")
def set_network_mode(request: NetworkModeRequest) -> dict[str, object]:
    return NetworkService().set_mode(request.mode)


@router.post("/start-4g")
def start_4g_network() -> dict[str, object]:
    return NetworkService().start_4g()
