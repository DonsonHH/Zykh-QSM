from __future__ import annotations

import os
import tempfile
import asyncio
from pathlib import Path

os.environ["QSM_ADB_AUTO_FORWARD"] = "0"
os.environ["QSM_DATA_DIR"] = tempfile.mkdtemp(prefix="zykh-qsm-test-")
os.environ["QSM_DB_PATH"] = str(Path(os.environ["QSM_DATA_DIR"]) / "test.db")
os.environ["AI_API_KEY_FILE"] = str(Path(os.environ["QSM_DATA_DIR"]) / "ai-key.txt")

import pytest

from app import db
from app import main


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {"content-type": "application/x-www-form-urlencoded"}

    async def form(self):
        return self.payload

    async def json(self):
        return self.payload


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def clean_db(monkeypatch):
    for suffix in ("", "-wal", "-shm"):
        target = Path(os.environ["QSM_DB_PATH"] + suffix)
        if target.exists():
            target.unlink()
    db.init_db()
    monkeypatch.setattr(main.qsm, "ensure_forward", lambda: {"ok": True, "enabled": False})
    monkeypatch.setattr(main.qsm, "adb_devices", lambda: {"ok": True, "connected": False, "output": ""})
    monkeypatch.setattr(main.qsm, "get", lambda path, **kwargs: {"ok": False, "error": "offline"})
    return True


def test_initializes_empty_23_slot_cabinet(clean_db):
    payload = main.medicines()
    assert payload["ok"] is True
    assert len(payload["medicines"]) == 23
    assert sum(1 for item in payload["medicines"] if item["stock"] > 0) == 0
    assert payload["medicines"][0]["box_size"] == "big"
    assert payload["medicines"][8]["box_size"] == "small"
    assert payload["medicines"][17]["box_size"] == "medium"
    assert payload["medicines"][0]["category"] == "其他应急"


def test_status_uses_qsm_main_naming(clean_db):
    payload = main.status()
    assert payload["ok"] is True
    assert "qsm_main" in payload
    assert "jetson" not in payload
    assert payload["qsm"]["online"] is False
    assert payload["site"]["station_name"] == "偏远社区康护站"
    assert payload["network"]["mode"] == "weak"
    assert payload["devices"]["dispense"] == "dry-run"


def test_site_can_be_saved(clean_db):
    payload = run(main.save_site(FakeRequest({
        "station_name": "村镇智慧用药服务点",
        "station_type": "village",
        "location_name": "西沟村",
        "network_mode": "offline",
        "ai_mode": "rules",
        "manager_name": "王管理员",
    })))
    assert payload["site"]["station_name"] == "村镇智慧用药服务点"
    assert payload["site"]["network_mode"] == "offline"


def test_profile_medicine_and_plan_write_to_qsm_db(clean_db):
    profile = run(main.save_profile(FakeRequest({"name": "张三", "age": "72", "conditions": "高血压"})))
    assert profile["profile"]["name"] == "张三"

    medicines = run(main.save_medicine(FakeRequest({"slot": "3", "name": "硝苯地平片", "dosage": "10mg", "stock": "28", "expire_date": "2027-12", "category": "慢病常用"})))
    slot3 = next(item for item in medicines["medicines"] if item["slot"] == 3)
    assert slot3["name"] == "硝苯地平片"
    assert slot3["stock"] == 28
    assert slot3["category"] == "慢病常用"

    plans = run(main.add_plan(FakeRequest({"slot": "3", "time": "08:00", "amount": "1片"})))
    assert plans["plans"][0]["slot"] == 3
    assert plans["plans"][0]["medicine_name"] == "硝苯地平片"


def test_vitals_write_to_qsm_db(clean_db):
    response = run(main.add_vitals(FakeRequest({"temperature": "36.5", "heart_rate": "76", "spo2": "98", "source": "manual"})))
    latest = response["vitals"][0]
    assert latest["temperature"] == 36.5
    assert latest["heart_rate"] == 76
    assert latest["spo2"] == 98


def test_dispense_defaults_to_dry_run_without_decrementing_stock(clean_db, monkeypatch):
    calls = []
    monkeypatch.setattr(main.qsm, "post", lambda path, data=None, **kwargs: calls.append((path, data)) or {"ok": True, "detail": f"opened {data['slot']}"})
    run(main.save_medicine(FakeRequest({"slot": "1", "name": "测试药", "stock": "2"})))

    payload = run(main.dispense(FakeRequest({"slot": "1"})))
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert calls == []
    slot1 = next(item for item in payload["medicines"] if item["slot"] == 1)
    assert slot1["stock"] == 2
    records = main.admin_logs()["dispense_records"]
    assert records[0]["dry_run"] == 1


def test_emergency_session_rules_allows_low_risk_candidate(clean_db):
    run(main.save_medicine(FakeRequest({
        "slot": "4",
        "name": "连花清瘟胶囊",
        "stock": "5",
        "category": "感冒发热",
        "indication_tags": "咽痛,流涕",
        "is_emergency": "1",
    })))
    payload = run(main.emergency_session(FakeRequest({
        "symptoms_text": "轻微咽痛流涕",
        "scene_type": "village",
        "network_mode": "offline",
        "allergy_or_contraindication": "",
    })))
    assert payload["ok"] is True
    assert payload["risk_level"] == "low"
    assert payload["allow_self_confirm"] is True
    assert payload["session_id"] >= 1


def test_settings_save_and_clear_ai_key(clean_db):
    save = run(main.save_ai_key(FakeRequest({"api_key": "test-key"})))
    assert save["settings"]["ai_key_configured"] is True
    assert Path(os.environ["AI_API_KEY_FILE"]).read_text(encoding="utf-8").strip() == "test-key"

    cleared = run(main.save_ai_key(FakeRequest({"api_key": ""})))
    assert cleared["settings"]["ai_key_configured"] is False
    assert not Path(os.environ["AI_API_KEY_FILE"]).exists()


def test_demo_seed_and_clear_endpoints(clean_db):
    seeded = main.seed_demo()
    assert seeded["ok"] is True
    assert seeded["profile"]["name"] == "张三"
    assert sum(1 for item in seeded["medicines"] if item["stock"] > 0) >= 8

    cleared = main.clear_demo(confirm="CLEAR")
    assert cleared["ok"] is True
    assert sum(1 for item in cleared["medicines"] if item["stock"] > 0) == 0
