from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .ai import stream_chat
from .config import AI_API_BASE, AI_KEY_FILE, AI_MODEL, APP_ROOT, DATA_DIR, DB_PATH, QSM_API_BASE
from .db import add_record, execute, init_db, now_text, row, rows, slot_kind
from .demo_data import clear_demo_data, seed_demo_data
from .qsm_client import qsm


DIST_DIR = APP_ROOT / "frontend" / "dist"

app = FastAPI(title="Zykh QSM Master", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()
    qsm.ensure_forward()


def ok(**data: Any) -> dict[str, Any]:
    return {"ok": True, **data}


def fail(message: str, **data: Any) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message, **data}, status_code=400)


async def parse_payload(request: Request) -> dict[str, Any]:
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        return await request.json()
    form = await request.form()
    return dict(form)


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def float_value(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def list_medicines() -> list[dict[str, Any]]:
    return rows("SELECT slot,name,dosage,stock,expire_date,code,trace_code,box_size,updated_at FROM medicines ORDER BY slot")


def upsert_medicine_payload(p: dict[str, Any], action: str = "medicine_save") -> None:
    slot = int_value(p.get("slot"))
    if slot < 1 or slot > 23:
        raise HTTPException(400, "slot must be 1-23")
    execute(
        """
        UPDATE medicines SET name=?, dosage=?, stock=?, expire_date=?, code=?,
          trace_code=?, box_size=?, updated_at=? WHERE slot=?
        """,
        (
            p.get("name", ""),
            p.get("dosage", ""),
            int_value(p.get("stock")),
            p.get("expire_date", ""),
            p.get("code", ""),
            p.get("trace_code", ""),
            p.get("box_size") or slot_kind(slot),
            now_text(),
            slot,
        ),
    )
    add_record(action, "success", f"保存 {slot} 号仓", slot, p.get("name", ""))


def latest_context() -> dict[str, Any]:
    return {
        "profile": row("SELECT * FROM profile WHERE id=1") or {},
        "latest_vitals": rows("SELECT * FROM vitals_records ORDER BY id DESC LIMIT 5"),
        "memories": rows("SELECT * FROM health_memories ORDER BY id DESC LIMIT 8"),
        "medicines": list_medicines(),
    }


@app.get("/api/status")
def status() -> dict[str, Any]:
    forward = qsm.ensure_forward()
    qsm_status = qsm.get("/api/status", timeout=5.0)
    adb = qsm.adb_devices()
    main_status = {
        "host": platform.node(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "time": now_text(),
        "data_dir": str(DATA_DIR),
    }
    return ok(
        qsm_main=main_status,
        qsm={
            "online": bool(qsm_status.get("ok")),
            "status": qsm_status,
            "adb": adb,
            "forward": forward,
        },
    )


@app.get("/api/profile")
def get_profile() -> dict[str, Any]:
    return ok(profile=row("SELECT * FROM profile WHERE id=1") or {})


@app.post("/api/profile")
async def save_profile(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    execute(
        """
        UPDATE profile SET name=?, gender=?, age=?, height=?, weight=?, conditions=?,
          allergies=?, notes=?, updated_at=? WHERE id=1
        """,
        (
            p.get("name", ""),
            p.get("gender", ""),
            int_value(p.get("age")),
            p.get("height", ""),
            p.get("weight", ""),
            p.get("conditions", ""),
            p.get("allergies", ""),
            p.get("notes", ""),
            now_text(),
        ),
    )
    return get_profile()


@app.get("/api/medicines")
def medicines() -> dict[str, Any]:
    return ok(medicines=list_medicines())


@app.post("/api/medicines")
async def save_medicine(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    upsert_medicine_payload(p)
    return medicines()


@app.get("/api/plans")
def plans() -> dict[str, Any]:
    got = rows(
        """
        SELECT plans.id, plans.slot, medicines.name AS medicine_name, plans.time,
          plans.amount, plans.enabled, plans.created_at
        FROM plans LEFT JOIN medicines ON medicines.slot = plans.slot
        ORDER BY plans.time, plans.id
        """
    )
    return ok(plans=got)


@app.post("/api/plans")
async def add_plan(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    slot = int_value(p.get("slot"))
    time = str(p.get("time") or "")
    if slot < 1 or slot > 23 or len(time) != 5:
        raise HTTPException(400, "slot/time invalid")
    execute(
        "INSERT INTO plans(slot,time,amount,enabled,created_at) VALUES (?,?,?,?,?)",
        (slot, time, p.get("amount", "1片"), int(p.get("enabled", 1)), now_text()),
    )
    return plans()


@app.get("/api/records")
def records() -> dict[str, Any]:
    return ok(records=rows("SELECT * FROM records ORDER BY id DESC LIMIT 80"))


@app.get("/api/vitals")
def vitals() -> dict[str, Any]:
    return ok(vitals=rows("SELECT * FROM vitals_records ORDER BY id DESC LIMIT 50"))


@app.post("/api/vitals")
async def add_vitals(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    execute(
        """
        INSERT INTO vitals_records(temperature,heart_rate,spo2,systolic,diastolic,source,quality,created_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            float_value(p.get("temperature")),
            int_value(p.get("heart_rate")),
            int_value(p.get("spo2")),
            int_value(p.get("systolic")),
            int_value(p.get("diastolic")),
            p.get("source", "manual"),
            p.get("quality", ""),
            now_text(),
        ),
    )
    return vitals()


@app.post("/api/vitals/read_all")
def read_all_vitals() -> dict[str, Any]:
    data = qsm.post("/api/vitals/read_all", timeout=40.0)
    if not data.get("ok"):
        fallback = qsm.post("/api/vitals/read", timeout=25.0)
        if fallback.get("ok"):
            data = fallback
    if not data.get("ok"):
        add_record("vitals_read", "failed", data.get("error", "外设设备体征读取失败"))
        return {"ok": False, **data}
    v = data.get("vitals", {})
    execute(
        """
        INSERT INTO vitals_records(temperature,heart_rate,spo2,systolic,diastolic,source,quality,created_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            float_value(v.get("temperature")),
            int_value(v.get("heart_rate")),
            int_value(v.get("spo2")),
            int_value(v.get("systolic")),
            int_value(v.get("diastolic")),
            v.get("source", "外设设备"),
            v.get("quality", ""),
            now_text(),
        ),
    )
    add_record("vitals_read", "success", "外设设备体征读取完成")
    return ok(vitals=v, qsm=data)


@app.get("/api/memories")
def memories() -> dict[str, Any]:
    return ok(memories=rows("SELECT * FROM health_memories ORDER BY id DESC LIMIT 80"))


@app.post("/api/memories")
async def add_memory(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    execute(
        "INSERT INTO health_memories(type,title,content,happened_at,source,created_at) VALUES (?,?,?,?,?,?)",
        (p.get("type", "note"), p.get("title", ""), p.get("content", ""), p.get("happened_at", ""), p.get("source", "qsm-main"), now_text()),
    )
    return memories()


@app.post("/api/dispense")
async def dispense(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    slot = int_value(p.get("slot"))
    if slot < 1 or slot > 23:
        raise HTTPException(400, "slot must be 1-23")
    med = row("SELECT * FROM medicines WHERE slot=?", (slot,)) or {}
    if int(med.get("stock") or 0) <= 0:
        add_record("dispense", "failed", "库存不足", slot, med.get("name", ""))
        return {"ok": False, "error": "库存不足或仓位未绑定药品"}
    qsm_res = qsm.post("/api/dispense", {"slot": slot}, timeout=15.0)
    if not qsm_res.get("ok"):
        add_record("dispense", "failed", qsm_res.get("error", "外设设备开仓失败"), slot, med.get("name", ""))
        return {"ok": False, "error": "外设设备开仓失败", "qsm": qsm_res}
    execute("UPDATE medicines SET stock=MAX(stock-1,0), updated_at=? WHERE slot=?", (now_text(), slot))
    add_record("dispense", "success", qsm_res.get("detail", "开仓完成"), slot, med.get("name", ""))
    return ok(detail=qsm_res.get("detail", "开仓完成"), qsm=qsm_res, medicines=list_medicines())


@app.get("/api/camera/stream")
def camera_stream(width: int = 640, height: int = 480, fps: int = 30):
    path = f"/api/camera/stream?width={width}&height={height}&fps={fps}"
    return StreamingResponse(qsm.stream_bytes(path), media_type="multipart/x-mixed-replace; boundary=zykhframe")


@app.post("/api/camera/capture")
def camera_capture() -> dict[str, Any]:
    data = qsm.post("/api/camera/capture", timeout=20.0)
    if data.get("ok"):
        data["image_url"] = "/api/camera/latest.jpg"
    return data


@app.get("/api/camera/latest.jpg")
def camera_latest():
    content, media_type = qsm.get_bytes("/camera/latest.jpg")
    return StreamingResponse(iter([content]), media_type=media_type)


@app.post("/api/medicine/scan")
async def medicine_scan(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    if str(p.get("confirm", "")).lower() in {"1", "true", "yes"}:
        upsert_medicine_payload(p, action="medicine_scan_confirm")
        return medicines()
    data = qsm.post("/api/medicine/scan", timeout=45.0)
    if not data.get("ok"):
        capture = qsm.post("/api/camera/capture", timeout=20.0)
        data = {"ok": bool(capture.get("ok")), "capture": capture, "detail": capture.get("detail", capture.get("error", ""))}
    suggestion = {"slot": first_empty_slot(), "stock": 1, "box_size": "medium"}
    return ok(scan=data, suggestion=suggestion)


def first_empty_slot() -> int:
    got = rows("SELECT slot,stock FROM medicines ORDER BY slot")
    for item in got:
        if int(item.get("stock") or 0) <= 0:
            return int(item["slot"])
    return 1


@app.post("/api/audio/asr")
async def audio_asr(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    return qsm.post("/api/audio/asr", p, timeout=45.0)


@app.post("/api/audio/speak")
async def audio_speak(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    return qsm.post("/api/audio/speak", {"text": p.get("text", "")}, timeout=30.0)


@app.get("/api/settings")
def settings() -> dict[str, Any]:
    return ok(
        settings={
            "qsm_api_base": QSM_API_BASE,
            "ai_api_base": AI_API_BASE,
            "ai_model": os.getenv("AI_MODEL", AI_MODEL),
            "ai_key_configured": bool(os.getenv("AI_API_KEY", "").strip() or AI_KEY_FILE.exists()),
            "db_path": str(DB_PATH),
            "data_dir": str(DATA_DIR),
        }
    )


@app.post("/api/settings/ai_key")
async def save_ai_key(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    key = str(p.get("api_key", "")).strip()
    if key:
        AI_KEY_FILE.write_text(key + "\n", encoding="utf-8")
        os.chmod(AI_KEY_FILE, 0o600)
    elif AI_KEY_FILE.exists():
        AI_KEY_FILE.unlink()
    add_record("settings", "success", "AI Key 配置已更新")
    return settings()


@app.post("/api/ai/chat/stream")
async def ai_chat_stream(request: Request):
    p = await parse_payload(request)
    message = str(p.get("message") or "").strip()
    if not message:
        return fail("请输入问诊内容")

    def events():
        reply = ""
        try:
            for delta in stream_chat(message, latest_context()):
                reply += delta
                yield f"event: delta\ndata: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'ok': True, 'reply': reply}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'ok': False}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/admin/reset")
def reset_database(confirm: str = Form("")) -> dict[str, Any]:
    if confirm != "RESET":
        raise HTTPException(400, "confirm must be RESET")
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(DB_PATH) + suffix)
        if target.exists():
            target.unlink()
    init_db()
    return ok(detail="QSM 主库已重新初始化")


@app.post("/api/demo/seed")
def seed_demo() -> dict[str, Any]:
    seed_demo_data()
    return ok(detail="演示模式已开启", profile=get_profile()["profile"], medicines=list_medicines())


@app.post("/api/demo/clear")
def clear_demo(confirm: str = Form("")) -> dict[str, Any]:
    if confirm != "CLEAR":
        raise HTTPException(400, "confirm must be CLEAR")
    clear_demo_data()
    return ok(detail="演示数据已清空", medicines=list_medicines())


if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    target = DIST_DIR / path
    if path and target.exists() and target.is_file():
        return FileResponse(target)
    index = DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"ok": True, "detail": "Frontend has not been built yet"})
