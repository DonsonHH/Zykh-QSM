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
from .ai_router import SAFETY_NOTICE, local_ai_health, route_triage, stream_chunks
from .config import (
    AI_API_BASE,
    AI_KEY_FILE,
    AI_MODEL,
    APP_ROOT,
    DATA_DIR,
    DB_PATH,
    DISPENSE_DRY_RUN,
    LOCAL_AI_BASE_URL,
    LOCAL_AI_MODEL,
    LOCAL_AI_PROVIDER,
    QSM_API_BASE,
)
from .db import add_operator_log, add_record, execute, init_db, now_text, row, rows, slot_kind
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
    return rows(
        """
        SELECT slot,name,dosage,stock,expire_date,code,trace_code,box_size,
          category,indication_tags,contraindications,dosage_note,safety_note,
          unit,barcode,image_path,is_emergency,is_daily_plan_medicine,updated_at
        FROM medicines ORDER BY slot
        """
    )


def upsert_medicine_payload(p: dict[str, Any], action: str = "medicine_save") -> None:
    slot = int_value(p.get("slot"))
    if slot < 1 or slot > 23:
        raise HTTPException(400, "slot must be 1-23")
    execute(
        """
        UPDATE medicines SET name=?, dosage=?, stock=?, expire_date=?, code=?,
          trace_code=?, box_size=?, category=?, indication_tags=?, contraindications=?,
          dosage_note=?, safety_note=?, unit=?, barcode=?, image_path=?,
          is_emergency=?, is_daily_plan_medicine=?, updated_at=? WHERE slot=?
        """,
        (
            p.get("name", ""),
            p.get("dosage", ""),
            int_value(p.get("stock")),
            p.get("expire_date", ""),
            p.get("code", ""),
            p.get("trace_code", ""),
            p.get("box_size") or slot_kind(slot),
            p.get("category", "其他应急"),
            p.get("indication_tags", ""),
            p.get("contraindications", ""),
            p.get("dosage_note", ""),
            p.get("safety_note", ""),
            p.get("unit", "件"),
            p.get("barcode") or p.get("code", ""),
            p.get("image_path", ""),
            int_value(p.get("is_emergency"), 1),
            int_value(p.get("is_daily_plan_medicine"), 0),
            now_text(),
            slot,
        ),
    )
    add_record(action, "success", f"保存 {slot} 号仓", slot, p.get("name", ""))
    add_operator_log(action, f"保存 {slot} 号仓", "medicine", str(slot))


def latest_context() -> dict[str, Any]:
    return {
        "profile": row("SELECT * FROM profile WHERE id=1") or {},
        "site": row("SELECT * FROM site_profile WHERE id=1") or {},
        "latest_vitals": rows("SELECT * FROM vitals_records ORDER BY id DESC LIMIT 5"),
        "memories": rows("SELECT * FROM health_memories ORDER BY id DESC LIMIT 8"),
        "medicines": list_medicines(),
    }


def qsm_diagnosis(qsm_status: dict[str, Any], adb: dict[str, Any], forward: dict[str, Any]) -> dict[str, Any]:
    if not adb.get("connected"):
        return {"layer": "adb", "label": "ADB 未连接", "detail": "未检测到外设采集与执行控制平台。"}
    if not forward.get("ok"):
        return {"layer": "forward", "label": "ADB 转发失败", "detail": forward.get("stderr") or "tcp 转发未建立。"}
    if qsm_status.get("ok"):
        return {"layer": "online", "label": "外设服务在线", "detail": "外设 8080 服务可访问。"}
    error = str(qsm_status.get("error") or "")
    if "Server disconnected" in error or "Empty reply" in error:
        return {"layer": "gateway_empty_reply", "label": "8080 空响应", "detail": "ADB 转发已建立，但外设 8080 服务未正常返回，请检查 Perl 网关进程。"}
    if "Connection refused" in error or "connect" in error:
        return {"layer": "gateway_down", "label": "8080 未监听", "detail": "外设网关服务未启动或未绑定 8080。"}
    return {"layer": "gateway_error", "label": "外设服务异常", "detail": error or "外设服务暂不可用。"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    forward = qsm.ensure_forward()
    qsm_status = qsm.get("/api/status", timeout=5.0)
    adb = qsm.adb_devices()
    diagnosis = qsm_diagnosis(qsm_status, adb, forward)
    site = row("SELECT * FROM site_profile WHERE id=1") or {}
    stocked = rows("SELECT COUNT(*) AS count FROM medicines WHERE stock > 0")[0]["count"]
    low_stock = rows("SELECT COUNT(*) AS count FROM medicines WHERE stock BETWEEN 1 AND 5")[0]["count"]
    pending = pending_sync_count()
    main_status = {
        "host": platform.node(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "time": now_text(),
        "data_dir": str(DATA_DIR),
    }
    return ok(
        qsm_main=main_status,
        site=site,
        network={
            "mode": site.get("network_mode", "weak"),
            "ai_mode": site.get("ai_mode", "local"),
            "last_sync_at": site.get("last_sync_at", ""),
            "pending_sync_count": pending,
            "sync_status": "待同步" if pending else (site.get("sync_status") or "已同步"),
        },
        cabinet={
            "total_slots": 23,
            "stocked_slots": stocked,
            "low_stock": low_stock,
        },
        devices={
            "camera": "online" if qsm_status.get("ok") else "unavailable",
            "vitals": "online" if qsm_status.get("ok") else "unavailable",
            "voice": "online" if qsm_status.get("ok") else "unavailable",
            "dispense": "dry-run" if DISPENSE_DRY_RUN else ("online" if qsm_status.get("ok") else "unavailable"),
        },
        qsm={
            "online": bool(qsm_status.get("ok")),
            "status": qsm_status,
            "adb": adb,
            "forward": forward,
            "diagnosis": diagnosis,
        },
    )


def pending_sync_count() -> int:
    total = 0
    for table in ("emergency_sessions", "dispense_records", "network_events", "operator_logs"):
        got = rows(f"SELECT COUNT(*) AS count FROM {table} WHERE sync_status='pending'")
        total += int(got[0]["count"] if got else 0)
    return total


@app.get("/api/site")
def get_site() -> dict[str, Any]:
    return ok(site=row("SELECT * FROM site_profile WHERE id=1") or {})


@app.post("/api/site")
async def save_site(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    execute(
        """
        UPDATE site_profile SET station_name=?, station_type=?, location_name=?,
          altitude=?, environment_tags=?, network_mode=?, ai_mode=?, emergency_contact=?,
          manager_name=?, last_sync_at=?, pending_sync_count=?, sync_status=?, updated_at=?
        WHERE id=1
        """,
        (
            p.get("station_name", "偏远社区康护站"),
            p.get("station_type", "village"),
            p.get("location_name", "村镇智慧用药服务点"),
            int_value(p.get("altitude")),
            p.get("environment_tags", "弱网,村镇,慢病随访,应急药品供给"),
            p.get("network_mode", "weak"),
            p.get("ai_mode", "local"),
            p.get("emergency_contact", "村医 / 管理员"),
            p.get("manager_name", "值守管理员"),
            p.get("last_sync_at", ""),
            int_value(p.get("pending_sync_count")),
            p.get("sync_status", "待同步"),
            now_text(),
        ),
    )
    execute(
        "INSERT INTO network_events(mode,ai_mode,reason,created_at) VALUES (?,?,?,?)",
        (p.get("network_mode", "weak"), p.get("ai_mode", "local"), "站点配置更新", now_text()),
    )
    add_operator_log("site_save", "站点配置已更新", "site", "1")
    return get_site()


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

    session_id = int_value(p.get("session_id"), 0)
    admin_reviewed = int_value(p.get("admin_reviewed"), 0)
    confirmed_by_user = int_value(p.get("confirmed_by_user"), 0)
    reason = str(p.get("reason") or ("应急问询取药" if session_id else "用药计划取药"))
    quantity = max(1, int_value(p.get("quantity"), 1))
    if session_id:
        session = row("SELECT * FROM emergency_sessions WHERE id=?", (session_id,))
        if not session:
            return {"ok": False, "error": "应急问询记录不存在"}
        if int(session.get("allow_self_confirm") or 0) != 1 and not admin_reviewed:
            add_record("dispense", "failed", "风险等级需要管理员复核", slot, med.get("name", ""))
            return {"ok": False, "error": "当前风险等级需要管理员复核后才能取药"}
        if int(session.get("allow_self_confirm") or 0) == 1 and not confirmed_by_user:
            return {"ok": False, "error": "请先完成用户取药确认"}

    dry_run = str(p.get("dry_run", "")).strip().lower()
    dry_run_enabled = DISPENSE_DRY_RUN if dry_run == "" else dry_run not in {"0", "false", "no", "off"}
    qsm_res: dict[str, Any] = {"ok": True, "detail": "dry-run：已完成取药校验和记录，未触发外设开仓"}
    if not dry_run_enabled:
        qsm_res = qsm.post("/api/dispense", {"slot": slot}, timeout=15.0)
        if not qsm_res.get("ok"):
            add_record("dispense", "failed", qsm_res.get("error", "外设采集与执行控制平台开仓失败"), slot, med.get("name", ""))
            execute(
                """
                INSERT INTO dispense_records(session_id,plan_id,slot,medicine_name,quantity,reason,
                  confirmed_by_user,admin_reviewed,dry_run,success,detail,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (session_id or None, int_value(p.get("plan_id")) or None, slot, med.get("name", ""), quantity, reason, confirmed_by_user, admin_reviewed, 0, 0, qsm_res.get("error", ""), now_text()),
            )
            return {"ok": False, "error": "外设采集与执行控制平台开仓失败", "qsm": qsm_res}
        execute("UPDATE medicines SET stock=MAX(stock-?,0), updated_at=? WHERE slot=?", (quantity, now_text(), slot))

    execute(
        """
        INSERT INTO dispense_records(session_id,plan_id,slot,medicine_name,quantity,reason,
          confirmed_by_user,admin_reviewed,dry_run,success,detail,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            session_id or None,
            int_value(p.get("plan_id")) or None,
            slot,
            med.get("name", ""),
            quantity,
            reason,
            confirmed_by_user,
            admin_reviewed,
            1 if dry_run_enabled else 0,
            1,
            qsm_res.get("detail", "开仓完成"),
            now_text(),
        ),
    )
    add_record("dispense", "success", qsm_res.get("detail", "开仓完成"), slot, med.get("name", ""))
    add_operator_log("dispense_dry_run" if dry_run_enabled else "dispense", qsm_res.get("detail", ""), "medicine", str(slot))
    return ok(
        detail=qsm_res.get("detail", "开仓完成"),
        dry_run=dry_run_enabled,
        qsm=qsm_res,
        medicines=list_medicines(),
    )


@app.get("/api/camera/stream")
def camera_stream(width: int = 640, height: int = 480, fps: int = 30):
    path = f"/api/camera/stream?width={width}&height={height}&fps={fps}"
    return StreamingResponse(qsm.stream_bytes(path), media_type="multipart/x-mixed-replace; boundary=zykhframe")


@app.post("/api/camera/capture")
def camera_capture() -> dict[str, Any]:
    qsm.post("/api/camera/stream/stop", timeout=8.0)
    data = qsm.post("/api/camera/capture", timeout=20.0)
    if data.get("ok"):
        data["image_url"] = "/api/camera/latest.jpg"
    return data


@app.post("/api/camera/stream/stop")
def camera_stream_stop() -> dict[str, Any]:
    return qsm.post("/api/camera/stream/stop", timeout=8.0)


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
    qsm.post("/api/camera/stream/stop", timeout=8.0)
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
            "local_ai_provider": os.getenv("LOCAL_AI_PROVIDER", LOCAL_AI_PROVIDER),
            "local_ai_base_url": os.getenv("LOCAL_AI_BASE_URL", LOCAL_AI_BASE_URL),
            "local_ai_model": os.getenv("LOCAL_AI_MODEL", LOCAL_AI_MODEL),
            "dispense_dry_run": DISPENSE_DRY_RUN,
            "ai_key_configured": bool(os.getenv("AI_API_KEY", "").strip() or AI_KEY_FILE.exists()),
            "db_path": str(DB_PATH),
            "data_dir": str(DATA_DIR),
        }
    )


@app.get("/api/local-ai/check")
def local_ai_check() -> dict[str, Any]:
    return ok(check=local_ai_health())


@app.post("/api/admin/hardware_check")
async def hardware_check(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    action = str(p.get("action") or "status").strip()
    result: dict[str, Any]
    if action == "status":
        forward = qsm.ensure_forward()
        adb = qsm.adb_devices()
        peripheral = qsm.get("/api/status", timeout=5.0)
        result = {
            "ok": bool(peripheral.get("ok")),
            "diagnosis": qsm_diagnosis(peripheral, adb, forward),
            "forward": forward,
            "adb": adb,
            "peripheral": peripheral,
            "gateway": qsm.gateway_diagnostics(),
        }
    elif action == "gateway_start":
        result = qsm.start_gateway()
    elif action == "camera":
        result = qsm.post("/api/camera/capture", timeout=20.0)
    elif action == "vitals":
        result = qsm.post("/api/vitals/read_all", timeout=40.0)
        if not result.get("ok"):
            fallback = qsm.post("/api/vitals/read", timeout=25.0)
            if fallback.get("ok"):
                result = fallback
    elif action == "audio_speak":
        text = str(p.get("text") or "智药康护外设设备语音播报测试").strip()
        result = qsm.post("/api/audio/speak", {"text": text}, timeout=30.0)
    elif action == "audio_asr":
        result = qsm.post("/api/audio/asr", {}, timeout=45.0)
    else:
        raise HTTPException(400, "unknown hardware check action")
    add_record("hardware_check", "success" if result.get("ok") else "failed", f"外设检查：{action}")
    return ok(action=action, result=result)


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


def insert_emergency_session(p: dict[str, Any], result: dict[str, Any]) -> int:
    return execute(
        """
        INSERT INTO emergency_sessions(started_at,scene_type,network_mode,symptoms_text,
          vitals_snapshot,allergy_or_contraindication,current_medicine_context,ai_mode,
          risk_level,symptoms_summary,suggested_categories,candidate_medicines,
          safety_warnings,next_steps,need_admin_review,allow_self_confirm,action_summary,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            now_text(),
            p.get("scene_type", ""),
            p.get("network_mode", ""),
            p.get("symptoms_text") or p.get("message", ""),
            json.dumps(p.get("vitals_snapshot", ""), ensure_ascii=False),
            p.get("allergy_or_contraindication", ""),
            json.dumps(p.get("current_medicine_context", ""), ensure_ascii=False),
            result.get("ai_mode", "rules"),
            result.get("risk_level", "low"),
            result.get("symptoms_summary", ""),
            json.dumps(result.get("suggested_categories", []), ensure_ascii=False),
            json.dumps(result.get("candidate_medicines", []), ensure_ascii=False),
            json.dumps(result.get("safety_warnings", []), ensure_ascii=False),
            json.dumps(result.get("next_steps", []), ensure_ascii=False),
            1 if result.get("need_admin_review") else 0,
            1 if result.get("allow_self_confirm") else 0,
            result.get("action_summary", ""),
            now_text(),
        ),
    )


@app.post("/api/emergency/session")
async def emergency_session(request: Request) -> dict[str, Any]:
    p = await parse_payload(request)
    context = latest_context()
    result, _text = route_triage(p, context)
    session_id = insert_emergency_session(p, result)
    add_record("emergency_session", "success", result.get("action_summary", ""), 0, p.get("symptoms_text", ""))
    add_operator_log("emergency_session", result.get("action_summary", ""), "emergency_session", str(session_id))
    return ok(session_id=session_id, **result)


@app.post("/api/ai/triage/stream")
async def ai_triage_stream(request: Request):
    p = await parse_payload(request)
    symptoms = str(p.get("symptoms_text") or p.get("message") or "").strip()
    if not symptoms:
        return fail("请输入症状或问询内容")
    context = latest_context()

    def events():
        try:
            result, text = route_triage(p, context)
            session_id = insert_emergency_session(p, result)
            add_record("ai_triage", "success", result.get("action_summary", ""), 0, symptoms)
            for delta in stream_chunks(text):
                yield f"event: delta\ndata: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
            done = {"ok": True, "session_id": session_id, "result": result, "reply": text}
            yield f"event: done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"
        except Exception as exc:
            fallback = {
                "ok": False,
                "error": str(exc),
                "safety_notice": SAFETY_NOTICE,
            }
            yield f"event: error\ndata: {json.dumps(fallback, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'ok': False}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/local-ai/chat/stream")
async def local_ai_chat_stream(request: Request):
    p = await parse_payload(request)
    p["network_mode"] = "offline"
    context = latest_context()

    def events():
        result, text = route_triage(p, context)
        for delta in stream_chunks(text):
            yield f"event: delta\ndata: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps({'ok': True, 'result': result, 'reply': text}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/admin/logs")
def admin_logs() -> dict[str, Any]:
    return ok(
        emergency_sessions=rows("SELECT * FROM emergency_sessions ORDER BY id DESC LIMIT 50"),
        dispense_records=rows("SELECT * FROM dispense_records ORDER BY id DESC LIMIT 50"),
        network_events=rows("SELECT * FROM network_events ORDER BY id DESC LIMIT 50"),
        operator_logs=rows("SELECT * FROM operator_logs ORDER BY id DESC LIMIT 80"),
        records=rows("SELECT * FROM records ORDER BY id DESC LIMIT 80"),
        pending_sync_count=pending_sync_count(),
    )


@app.post("/api/sync/mock")
def mock_sync() -> dict[str, Any]:
    now = now_text()
    add_operator_log("mock_sync", "本地记录已标记为模拟同步完成", "sync", "local")
    for table in ("emergency_sessions", "dispense_records", "network_events", "operator_logs"):
        execute(f"UPDATE {table} SET sync_status='synced' WHERE sync_status='pending'")
    execute("UPDATE site_profile SET last_sync_at=?, pending_sync_count=0, sync_status='模拟同步完成', updated_at=? WHERE id=1", (now, now))
    return ok(detail="模拟同步完成", last_sync_at=now, pending_sync_count=0)


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
