from __future__ import annotations

import json

from .. import db
from ..schemas.medicine import Medicine


MEDICINE_SEED_VERSION = "home-v2"

DEFAULT_MEDICINES = [
    {
        "id": "aspirin-enteric",
        "slot": "A01",
        "hardware_slot": 1,
        "barcode": "",
        "name": "阿司匹林肠溶片",
        "category": "家庭常用",
        "tags": ["心脑血管", "长期管理"],
        "contraindications": ["胃肠道出血风险", "阿司匹林过敏禁用"],
        "stock": 8,
        "unit": "板",
        "expire_date": "2027-11-30",
        "image_hint": "蓝白药盒",
        "is_otc": False,
        "is_emergency": False,
        "safety_note": "开柜前核对既往过敏史、出血风险和家庭用药记录。",
    },
    {
        "id": "nifedipine-controlled",
        "slot": "A02",
        "hardware_slot": 2,
        "barcode": "",
        "name": "硝苯地平控释片",
        "category": "家庭常用",
        "tags": ["血压管理", "控释片"],
        "contraindications": ["低血压风险", "请勿掰开或嚼碎"],
        "stock": 6,
        "unit": "板",
        "expire_date": "2027-09-18",
        "image_hint": "红白药盒",
        "is_otc": False,
        "is_emergency": False,
        "safety_note": "开柜前确认血压监测情况和既往用药记录。",
    },
    {
        "id": "ibuprofen-sustained",
        "slot": "B01",
        "hardware_slot": 3,
        "barcode": "",
        "name": "布洛芬缓释胶囊",
        "category": "感冒发热",
        "tags": ["发热", "疼痛"],
        "contraindications": ["消化道溃疡慎用", "孕晚期禁用"],
        "stock": 6,
        "unit": "板",
        "expire_date": "2027-06-15",
        "image_hint": "橙白药盒",
        "is_otc": True,
        "is_emergency": True,
        "safety_note": "避免与同类退热镇痛药重复使用，注意用量间隔。",
    },
    {
        "id": "lianhua-qingwen",
        "slot": "B02",
        "hardware_slot": 4,
        "barcode": "6901070303888",
        "name": "连花清瘟胶囊",
        "category": "感冒发热",
        "tags": ["感冒", "咽痛"],
        "contraindications": ["过敏体质慎用", "儿童需监护确认"],
        "stock": 4,
        "unit": "盒",
        "expire_date": "2026-12-20",
        "image_hint": "绿色药盒",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "开柜前核对症状持续时间和合并用药情况。",
    },
    {
        "id": "montmorillonite-powder",
        "slot": "C01",
        "hardware_slot": 5,
        "barcode": "",
        "name": "蒙脱石散",
        "category": "肠胃",
        "tags": ["腹泻", "肠胃"],
        "contraindications": ["便秘慎用", "需与其他药物错开服用"],
        "stock": 10,
        "unit": "袋",
        "expire_date": "2027-04-10",
        "image_hint": "黄色药袋",
        "is_otc": True,
        "is_emergency": True,
        "safety_note": "注意补液观察，严重脱水或持续高热需及时转诊。",
    },
    {
        "id": "loratadine-tablet",
        "slot": "D01",
        "hardware_slot": 6,
        "barcode": "",
        "name": "氯雷他定片",
        "category": "过敏",
        "tags": ["过敏", "鼻炎"],
        "contraindications": ["严重肝功能异常慎用", "过敏禁用"],
        "stock": 6,
        "unit": "板",
        "expire_date": "2027-08-05",
        "image_hint": "浅蓝药盒",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "开柜前确认过敏表现，呼吸困难等严重情况需立即联系专业人员。",
    },
    {
        "id": "iodophor-swab",
        "slot": "E01",
        "hardware_slot": 7,
        "barcode": "",
        "name": "碘伏棉签",
        "category": "外伤消毒",
        "tags": ["外伤", "消毒"],
        "contraindications": ["碘过敏禁用", "深部伤口需专业处理"],
        "stock": 12,
        "unit": "包",
        "expire_date": "2028-01-12",
        "image_hint": "消毒棉签包",
        "is_otc": True,
        "is_emergency": True,
        "safety_note": "用于皮肤表面消毒，污染严重或出血不止需转诊。",
    },
    {
        "id": "adhesive-bandage",
        "slot": "E02",
        "hardware_slot": 8,
        "barcode": "",
        "name": "创可贴",
        "category": "外伤消毒",
        "tags": ["外伤", "包扎"],
        "contraindications": ["感染伤口慎用", "皮肤胶布过敏慎用"],
        "stock": 20,
        "unit": "片",
        "expire_date": "2028-03-01",
        "image_hint": "创可贴盒",
        "is_otc": True,
        "is_emergency": True,
        "safety_note": "仅用于浅表小伤口，红肿渗液或疼痛加重需进一步处理。",
    },
]


class MedicineRepository:
    def list_all(self) -> list[Medicine]:
        self._ensure_seeded()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, slot, hardware_slot, barcode, name, category, tags_json,
                       contraindications_json, stock, unit, expire_date, image_hint,
                       is_otc, is_emergency, safety_note
                FROM medicines
                ORDER BY hardware_slot, slot
                """
            ).fetchall()
        return [self._row_to_medicine(row) for row in rows]

    def get_by_id(self, medicine_id: str) -> Medicine | None:
        self._ensure_seeded()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, slot, hardware_slot, barcode, name, category, tags_json,
                       contraindications_json, stock, unit, expire_date, image_hint,
                       is_otc, is_emergency, safety_note
                FROM medicines
                WHERE id=?
                """,
                (medicine_id,),
            ).fetchone()
        return self._row_to_medicine(row) if row else None

    def get_by_barcode(self, barcode: str) -> Medicine | None:
        self._ensure_seeded()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, slot, hardware_slot, barcode, name, category, tags_json,
                       contraindications_json, stock, unit, expire_date, image_hint,
                       is_otc, is_emergency, safety_note
                FROM medicines
                WHERE barcode=?
                """,
                (barcode,),
            ).fetchone()
        return self._row_to_medicine(row) if row else None

    def decrement_stock(self, medicine_id: str, quantity: int) -> None:
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET stock=MAX(stock - ?, 0), updated_at=?
                WHERE id=?
                """,
                (quantity, db.now_text(), medicine_id),
            )

    def _ensure_seeded(self) -> None:
        db.init_db()
        with db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM medicines").fetchone()["count"]
            if count:
                self._sync_default_inventory(conn)
                return
            conn.executemany(
                """
                INSERT INTO medicines(
                  id, slot, hardware_slot, barcode, name, category, tags_json,
                  contraindications_json, stock, unit, expire_date, image_hint,
                  is_otc, is_emergency, safety_note, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["id"],
                        item["slot"],
                        int(item["hardware_slot"]),
                        item["barcode"],
                        item["name"],
                        item["category"],
                        json.dumps(item["tags"], ensure_ascii=False),
                        json.dumps(item["contraindications"], ensure_ascii=False),
                        int(item["stock"]),
                        item["unit"],
                        item["expire_date"],
                        item["image_hint"],
                        1 if item["is_otc"] else 0,
                        1 if item["is_emergency"] else 0,
                        item["safety_note"],
                        db.now_text(),
                    )
                    for item in DEFAULT_MEDICINES
                ],
            )
            conn.execute(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES ('medicine_seed_version', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (MEDICINE_SEED_VERSION, db.now_text()),
            )

    @staticmethod
    def _sync_default_inventory(conn) -> None:
        row = conn.execute("SELECT value FROM app_settings WHERE key='medicine_seed_version'").fetchone()
        if row and row["value"] == MEDICINE_SEED_VERSION:
            return
        for item in DEFAULT_MEDICINES:
            conn.execute(
                """
                UPDATE medicines
                SET category=?,
                    tags_json=?,
                    contraindications_json=?,
                    stock=?,
                    unit=?,
                    image_hint=?,
                    safety_note=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    item["category"],
                    json.dumps(item["tags"], ensure_ascii=False),
                    json.dumps(item["contraindications"], ensure_ascii=False),
                    int(item["stock"]),
                    item["unit"],
                    item["image_hint"],
                    item["safety_note"],
                    db.now_text(),
                    item["id"],
                ),
            )
        conn.execute(
            """
            INSERT INTO app_settings(key, value, updated_at)
            VALUES ('medicine_seed_version', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (MEDICINE_SEED_VERSION, db.now_text()),
        )

    @staticmethod
    def _row_to_medicine(row: object) -> Medicine:
        return Medicine(
            id=row["id"],
            slot=row["slot"],
            hardware_slot=int(row["hardware_slot"]),
            barcode=row["barcode"] or "",
            name=row["name"],
            category=row["category"],
            tags=json.loads(row["tags_json"]),
            contraindications=json.loads(row["contraindications_json"]),
            stock=int(row["stock"]),
            unit=row["unit"],
            expire_date=row["expire_date"],
            image_hint=row["image_hint"],
            is_otc=bool(row["is_otc"]),
            is_emergency=bool(row["is_emergency"]),
            safety_note=row["safety_note"],
        )
