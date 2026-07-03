from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import settings
from .routers import dashboard, health, qsm, site, status


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
    app.include_router(qsm.router)
    return app


app = create_app()


@app.on_event("startup")
def startup() -> None:
    db.init_db()
