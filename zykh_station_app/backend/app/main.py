from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .routers import ai, audio, camera, dashboard, device, dispense, fingerprint, health, identity, inquiry, medicines, network, qsm, records, site, status, sync, vitals


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(site.router)
    app.include_router(dashboard.router)
    app.include_router(device.router)
    app.include_router(network.router)
    app.include_router(qsm.router)
    app.include_router(vitals.router)
    app.include_router(camera.router)
    app.include_router(identity.router)
    app.include_router(fingerprint.router)
    app.include_router(audio.router)
    app.include_router(ai.router)
    app.include_router(medicines.router)
    app.include_router(dispense.router)
    app.include_router(inquiry.router)
    app.include_router(records.router)
    app.include_router(sync.router)
    dist_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")
    return app


app = create_app()


@app.on_event("startup")
def startup() -> None:
    db.init_db()
