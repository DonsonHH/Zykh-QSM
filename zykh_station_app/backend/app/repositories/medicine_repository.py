from __future__ import annotations

import json
import re
from uuid import uuid4

from .. import db
from ..schemas.medicine import Medicine


MEDICINE_SEED_VERSION = "home-real-cabinet-v2"

DEFAULT_MEDICINES = [
    {
        "id": "slot-01-fufang-ganmaoling",
        "slot": "S01",
        "hardware_slot": 1,
        "barcode": "6900966688219",
        "manufacturer": "999",
        "name": "复方感冒灵颗粒",
        "category": "感冒发热",
        "tags": ["风热感冒", "发热咽痛"],
        "contraindications": ["严重肝肾功能不全禁用", "避免与同类解热镇痛药重复使用"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2026-12",
        "image_hint": "999 复方感冒灵颗粒",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "含对乙酰氨基酚成分，取药前核对肝肾功能风险和重复用药。",
    },
    {
        "id": "slot-02-centrum",
        "slot": "S02",
        "hardware_slot": 2,
        "barcode": "",
        "manufacturer": "善存",
        "name": "多维元素片",
        "category": "营养补充",
        "tags": ["维生素矿物质", "营养补充"],
        "contraindications": ["慢性肾功能衰竭禁用", "高钙血症或高磷血症禁用"],
        "stock": 1,
        "unit": "瓶",
        "expire_date": "2027-09-18",
        "image_hint": "善存多维元素片",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "按说明书剂量使用，避免与高剂量维矿补充剂重复。",
    },
    {
        "id": "slot-03-ganmao-qingre",
        "slot": "S03",
        "hardware_slot": 3,
        "barcode": "6928849913616",
        "manufacturer": "999",
        "name": "感冒清热颗粒",
        "category": "感冒发热",
        "tags": ["风寒感冒", "头痛发热"],
        "contraindications": ["对本品成分过敏禁用", "风热感冒表现者不适用"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2027-11",
        "image_hint": "999 感冒清热颗粒",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "用于风寒感冒相关症状，症状不匹配或持续加重需联系医生。",
    },
    {
        "id": "slot-04-amoxicillin",
        "slot": "S04",
        "hardware_slot": 4,
        "barcode": "6938588802331",
        "manufacturer": "华北制药",
        "name": "阿莫西林胶囊",
        "category": "抗菌药",
        "tags": ["青霉素类", "处方核验"],
        "contraindications": ["青霉素过敏禁用", "需按既往医嘱或处方使用"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2027-02",
        "image_hint": "华北制药阿莫西林胶囊",
        "is_otc": False,
        "is_emergency": False,
        "safety_note": "抗菌药需确认过敏史和医嘱，不作为自行新增用药。",
    },
    {
        "id": "slot-05-nin-jiom-pei-pa-koa",
        "slot": "S05",
        "hardware_slot": 5,
        "barcode": "081364361693",
        "manufacturer": "京都念慈庵",
        "name": "蜜炼川贝枇杷膏",
        "category": "咳嗽咽喉",
        "tags": ["咳嗽痰多", "咽喉不适"],
        "contraindications": ["对成分过敏禁用", "糖尿病患者慎用"],
        "stock": 1,
        "unit": "瓶",
        "expire_date": "2028-06",
        "image_hint": "京都念慈庵蜜炼川贝枇杷膏",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "含糖浆类辅料，糖代谢异常或症状持续者需谨慎核验。",
    },
    {
        "id": "slot-06-lactulose",
        "slot": "S06",
        "hardware_slot": 6,
        "barcode": "6943798800923",
        "manufacturer": "健能药业",
        "name": "乳果糖口服液",
        "category": "肠胃",
        "tags": ["便秘", "肠道调节"],
        "contraindications": ["肠梗阻或急腹痛禁用", "半乳糖不耐受者不宜使用"],
        "stock": 1,
        "unit": "瓶",
        "expire_date": "2027-02",
        "image_hint": "健能药业乳果糖口服液",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "便秘用药前需排除急腹痛、肠梗阻等风险。",
    },
    {
        "id": "slot-07-yinhuang",
        "slot": "S07",
        "hardware_slot": 7,
        "barcode": "6934199500017",
        "manufacturer": "神鹤药业",
        "name": "银黄颗粒",
        "category": "咽喉口腔",
        "tags": ["咽痛", "上呼吸道不适"],
        "contraindications": ["对本品过敏禁用", "脾胃虚寒或糖尿病患者慎用"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2028-08-29",
        "image_hint": "神鹤药业银黄颗粒",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "高热、化脓或症状 3 天无改善时需联系医生。",
    },
    {
        "id": "slot-08-huoxiang-zhengqi",
        "slot": "S08",
        "hardware_slot": 8,
        "barcode": "6921711516168",
        "manufacturer": "恒心堂",
        "name": "藿香正气丸",
        "category": "肠胃",
        "tags": ["暑湿不适", "腹胀呕吐"],
        "contraindications": ["风热感冒不适用", "孕妇及严重慢病患者需医师指导"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2028-03",
        "image_hint": "恒心堂藿香正气丸",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "适用暑湿相关不适，胸闷心悸或吐泻明显需就医。",
    },
    {
        "id": "slot-09-bifid-triple",
        "slot": "S09",
        "hardware_slot": 9,
        "barcode": "6922313021210",
        "manufacturer": "贝飞达",
        "name": "双歧杆菌三联活菌肠溶胶囊",
        "category": "肠胃",
        "tags": ["菌群调节", "腹泻便秘"],
        "contraindications": ["对本品过敏禁用", "避免与抗菌药同时服用"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2026-09",
        "image_hint": "贝飞达双歧杆菌三联活菌肠溶胶囊",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "活菌制剂注意储存条件，和抗菌药需错开。",
    },
    {
        "id": "slot-10-gauze",
        "slot": "S10",
        "hardware_slot": 10,
        "barcode": "6950715511633",
        "manufacturer": "可孚",
        "name": "医用纱布敷料",
        "category": "外伤护理",
        "tags": ["伤口覆盖", "包扎"],
        "contraindications": ["包装破损或污染禁用", "深大伤口需专业处理"],
        "stock": 1,
        "unit": "包",
        "expire_date": "2026-11-12",
        "image_hint": "可孚医用纱布敷料",
        "is_otc": True,
        "is_emergency": True,
        "safety_note": "使用前确认无菌包装完好，伤口感染或出血不止需就医。",
    },
    {
        "id": "slot-11-guilin-xiguashuang",
        "slot": "S11",
        "hardware_slot": 11,
        "barcode": "6939261900771",
        "manufacturer": "三金",
        "name": "桂林西瓜霜",
        "category": "咽喉口腔",
        "tags": ["咽喉肿痛", "口腔不适"],
        "contraindications": ["对本品过敏禁用", "喷敷时避免吸入气道"],
        "stock": 1,
        "unit": "瓶",
        "expire_date": "2028-01-08",
        "image_hint": "三金桂林西瓜霜",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "高热、化脓或口腔严重糜烂需联系医生。",
    },
    {
        "id": "slot-12-hydrotalcite",
        "slot": "S12",
        "hardware_slot": 12,
        "barcode": "6921041723526",
        "manufacturer": "华森制药",
        "name": "铝碳酸镁咀嚼片",
        "category": "肠胃",
        "tags": ["胃酸", "胃部不适"],
        "contraindications": ["重度肾损害禁用", "低磷血症或重症肌无力禁用"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2027-08",
        "image_hint": "华森制药铝碳酸镁咀嚼片",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "需嚼服，长期或反复胃痛应联系医生。",
    },
    {
        "id": "slot-13-sodium-hyaluronate-eye",
        "slot": "S13",
        "hardware_slot": 13,
        "barcode": "6955236613620",
        "manufacturer": "普润盈",
        "name": "玻璃酸钠滴眼液",
        "category": "眼部护理",
        "tags": ["干眼", "眼部润滑"],
        "contraindications": ["对成分过敏禁用", "瓶口勿接触眼部或皮肤"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2026-08-10",
        "image_hint": "普润盈玻璃酸钠滴眼液",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "眼部疼痛、红肿或视力变化时不要自行处理。",
    },
    {
        "id": "slot-14-oseltamivir",
        "slot": "S14",
        "hardware_slot": 14,
        "barcode": "6958439003076",
        "manufacturer": "华海药业",
        "name": "磷酸奥司他韦胶囊",
        "category": "感冒发热",
        "tags": ["流感用药", "处方核验"],
        "contraindications": ["对本品成分过敏禁用", "需按医嘱确认适用时机"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2028-11",
        "image_hint": "华海药业磷酸奥司他韦胶囊",
        "is_otc": False,
        "is_emergency": False,
        "safety_note": "流感相关用药需核验症状时间窗和医嘱。",
    },
    {
        "id": "slot-15-mupirocin",
        "slot": "S15",
        "hardware_slot": 15,
        "barcode": "62000000204025",
        "manufacturer": "中美史克",
        "name": "莫匹罗星软膏",
        "category": "外用皮肤",
        "tags": ["皮肤感染", "外用软膏"],
        "contraindications": ["莫匹罗星或聚乙二醇过敏禁用", "不用于眼内或鼻腔"],
        "stock": 1,
        "unit": "支",
        "expire_date": "2026-02",
        "image_hint": "中美史克莫匹罗星软膏",
        "is_otc": False,
        "is_emergency": False,
        "safety_note": "外用抗菌药需核验伤口状态和既往用药。",
    },
    {
        "id": "slot-16-ketoconazole",
        "slot": "S16",
        "hardware_slot": 16,
        "barcode": "",
        "manufacturer": "金日制药",
        "name": "酮康唑乳膏",
        "category": "外用皮肤",
        "tags": ["真菌感染", "外用乳膏"],
        "contraindications": ["对本品过敏禁用", "避免接触眼睛和黏膜"],
        "stock": 1,
        "unit": "支",
        "expire_date": "2028-09-30",
        "image_hint": "金日制药酮康唑乳膏",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "不得用于破溃皮肤，大面积或长期使用需咨询医生。",
    },
    {
        "id": "slot-17-iodophor",
        "slot": "S17",
        "hardware_slot": 17,
        "barcode": "6926378900350",
        "manufacturer": "利尔康",
        "name": "碘伏消毒液",
        "category": "外伤护理",
        "tags": ["皮肤消毒", "浅表伤口"],
        "contraindications": ["碘过敏者慎用", "外用消毒剂禁止口服"],
        "stock": 1,
        "unit": "瓶",
        "expire_date": "2026-12-10",
        "image_hint": "利尔康碘伏消毒液",
        "is_otc": True,
        "is_emergency": True,
        "safety_note": "仅限外用，深部伤口、严重烧伤或感染需就医。",
    },
    {
        "id": "slot-18-budesonide-nasal",
        "slot": "S18",
        "hardware_slot": 18,
        "barcode": "",
        "manufacturer": "雷诺考特",
        "name": "布地奈德鼻喷雾剂",
        "category": "鼻炎过敏",
        "tags": ["鼻炎", "鼻喷雾"],
        "contraindications": ["对布地奈德或辅料过敏禁用", "仅鼻腔使用，避免入眼"],
        "stock": 1,
        "unit": "瓶",
        "expire_date": "2027-01",
        "image_hint": "雷诺考特布地奈德鼻喷雾剂",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "连续使用后症状无改善或鼻出血需咨询医生。",
    },
    {
        "id": "slot-19-ketoprofen-gel",
        "slot": "S19",
        "hardware_slot": 19,
        "barcode": "",
        "manufacturer": "法斯通",
        "name": "酮洛芬凝胶",
        "category": "外用止痛",
        "tags": ["肌肉关节痛", "外用凝胶"],
        "contraindications": ["非甾体抗炎药过敏禁用", "活动性消化道溃疡禁用"],
        "stock": 1,
        "unit": "支",
        "expire_date": "2028-08",
        "image_hint": "法斯通酮洛芬凝胶",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "不得用于破损或感染伤口，孕哺期慎用。",
    },
    {
        "id": "slot-20-bandage",
        "slot": "S20",
        "hardware_slot": 20,
        "barcode": "",
        "manufacturer": "凡卡",
        "name": "创口贴",
        "category": "外伤护理",
        "tags": ["浅表小伤口", "保护包扎"],
        "contraindications": ["深部伤口或动物咬伤不适用", "感染化脓伤口不适用"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2026-11",
        "image_hint": "凡卡创口贴",
        "is_otc": True,
        "is_emergency": True,
        "safety_note": "只用于清洁浅表小伤口，需定期更换并观察感染迹象。",
    },
    {
        "id": "slot-21-amlodipine",
        "slot": "S21",
        "hardware_slot": 21,
        "barcode": "6910853810272",
        "manufacturer": "京新药业",
        "name": "苯磺酸氨氯地平片",
        "category": "慢病常用",
        "tags": ["血压管理", "长期用药"],
        "contraindications": ["对氨氯地平过敏禁用", "低血压或肝功能受损需医嘱"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2028-08",
        "image_hint": "京新药业苯磺酸氨氯地平片",
        "is_otc": False,
        "is_emergency": False,
        "safety_note": "慢病用药仅按既往计划或医嘱取用。",
    },
    {
        "id": "slot-22-cotton-swab",
        "slot": "S22",
        "hardware_slot": 22,
        "barcode": "6932593000577",
        "manufacturer": "稳健医疗",
        "name": "医用棉签",
        "category": "外伤护理",
        "tags": ["清洁处理", "一次性用品"],
        "contraindications": ["包装破损或污染禁用", "一次性用品禁止重复使用"],
        "stock": 1,
        "unit": "包",
        "expire_date": "2027-12",
        "image_hint": "稳健医疗医用棉签",
        "is_otc": True,
        "is_emergency": True,
        "safety_note": "使用前核对有效期和包装完整性，用后按废弃物处理。",
    },
    {
        "id": "slot-23-desloratadine",
        "slot": "S23",
        "hardware_slot": 23,
        "barcode": "6970847150012",
        "manufacturer": "恩瑞特医疗",
        "name": "枸地氯雷他定胶囊",
        "category": "鼻炎过敏",
        "tags": ["过敏性鼻炎", "荨麻疹"],
        "contraindications": ["对活性成分或辅料过敏禁用", "出现心悸或明显嗜睡需停止并咨询"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2026-10-16",
        "image_hint": "恩瑞特医疗枸地氯雷他定胶囊",
        "is_otc": False,
        "is_emergency": False,
        "safety_note": "过敏症状伴呼吸困难或面唇肿胀时应立即就医。",
    },
]


class MedicineRepository:
    def list_all(self) -> list[Medicine]:
        self._ensure_seeded()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, slot, hardware_slot, barcode, name, category, tags_json,
                       contraindications_json, stock, unit, expire_date, image_hint, manufacturer,
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
                       contraindications_json, stock, unit, expire_date, image_hint, manufacturer,
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
                       contraindications_json, stock, unit, expire_date, image_hint, manufacturer,
                       is_otc, is_emergency, safety_note
                FROM medicines
                WHERE barcode=?
                """,
                (barcode,),
            ).fetchone()
        return self._row_to_medicine(row) if row else None

    def create_from_scan(
        self,
        *,
        barcode: str,
        name: str,
        spec: str = "",
        expire_date: str = "",
        stock: int = 1,
        unit: str = "盒",
        category: str = "扫码录入",
        hardware_slot: int | None = None,
        safety_note: str = "",
    ) -> Medicine:
        self._ensure_seeded()
        normalized_barcode = barcode.strip()
        existing = self.get_by_barcode(normalized_barcode) if normalized_barcode else None
        if existing:
            return existing

        slot_number = hardware_slot or self.first_empty_hardware_slot()
        slot_label = f"S{slot_number:02d}"
        medicine_id = self._scan_id(name, normalized_barcode)
        stock = max(int(stock or 1), 1)
        safety = safety_note or "扫码录入药品，开柜前请核对药盒、有效期和家庭用药记录。"
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO medicines(
                  id, slot, hardware_slot, barcode, manufacturer, name, category, tags_json,
                  contraindications_json, stock, unit, expire_date, image_hint,
                  is_otc, is_emergency, safety_note, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  barcode=excluded.barcode,
                  manufacturer=excluded.manufacturer,
                  name=excluded.name,
                  category=excluded.category,
                  stock=excluded.stock,
                  unit=excluded.unit,
                  expire_date=excluded.expire_date,
                  image_hint=excluded.image_hint,
                  safety_note=excluded.safety_note,
                  updated_at=excluded.updated_at
                """,
                (
                    medicine_id,
                    slot_label,
                    slot_number,
                    normalized_barcode,
                    "",
                    name.strip() or "待核验药品",
                    category.strip() or "扫码录入",
                    json.dumps(["扫码录入", "待核验"], ensure_ascii=False),
                    json.dumps(["请人工核对药品说明"], ensure_ascii=False),
                    stock,
                    unit.strip() or "盒",
                    expire_date.strip(),
                    spec.strip() or "扫码录入",
                    1,
                    0,
                    safety,
                    db.now_text(),
                ),
            )
        created = self.get_by_id(medicine_id)
        if created is None:
            raise RuntimeError("扫码药品录入失败。")
        return created

    def first_empty_hardware_slot(self) -> int:
        self._ensure_seeded()
        with db.connect() as conn:
            rows = conn.execute("SELECT hardware_slot FROM medicines WHERE stock > 0").fetchall()
        used = {int(row["hardware_slot"]) for row in rows}
        for slot in range(1, 24):
            if slot not in used:
                return slot
        return 23

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
            self._insert_default_inventory(conn)

    @staticmethod
    def _sync_default_inventory(conn) -> None:
        row = conn.execute("SELECT value FROM app_settings WHERE key='medicine_seed_version'").fetchone()
        if row and row["value"] == MEDICINE_SEED_VERSION:
            return
        conn.execute("DELETE FROM medicines")
        MedicineRepository._insert_default_inventory(conn)

    @staticmethod
    def _insert_default_inventory(conn) -> None:
        conn.executemany(
            """
            INSERT INTO medicines(
              id, slot, hardware_slot, barcode, manufacturer, name, category, tags_json,
              contraindications_json, stock, unit, expire_date, image_hint,
              is_otc, is_emergency, safety_note, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["id"],
                    item["slot"],
                    int(item["hardware_slot"]),
                    item["barcode"],
                    item.get("manufacturer", ""),
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
    def _row_to_medicine(row: object) -> Medicine:
        return Medicine(
            id=row["id"],
            slot=row["slot"],
            hardware_slot=int(row["hardware_slot"]),
            barcode=row["barcode"] or "",
            manufacturer=row["manufacturer"] or "",
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

    @staticmethod
    def _scan_id(name: str, barcode: str) -> str:
        if barcode:
            safe_barcode = re.sub(r"[^A-Za-z0-9_-]+", "-", barcode)[:36].strip("-")
            return f"scan-{safe_barcode or uuid4().hex[:10]}"
        safe_name = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]+", "-", name.strip())[:24].strip("-")
        return f"scan-{safe_name or uuid4().hex[:10]}"
