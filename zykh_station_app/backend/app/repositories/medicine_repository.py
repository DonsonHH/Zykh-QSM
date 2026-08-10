from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from uuid import uuid4

from .. import db
from ..schemas.medicine import (
    MEDICINE_COMBINATION_CLINICAL_POLICY_VERSION,
    ApprovedMedicineCombination,
    Medicine,
    MedicineCombinationApplicability,
    MedicineCombinationEvidenceRef,
    MedicineIngredientConflictRule,
)


MEDICINE_SEED_VERSION = "home-real-cabinet-v8-fixed-catalog"
MEDICINE_GUIDANCE_VERSION = "verified-label-reference-v6-slot-03-13-online"
PACKAGE_VERIFICATION_VERSION = "fixed-inventory-identity-v1"
MEDICINE_SAFETY_FACTS_VERSION = "database-safety-facts-v6-repaired-fixed-catalog"
BUNDLED_LABEL_SAFETY_REVIEWER = "bundled-cabinet-reference-v6"
BUNDLED_LABEL_SAFETY_REVIEWERS = frozenset(
    {
        "bundled-label-reference-v2",
        "bundled-cabinet-reference-v4",
        "bundled-cabinet-reference-v5",
        BUNDLED_LABEL_SAFETY_REVIEWER,
    }
)
BUNDLED_LABEL_SAFETY_IDS = frozenset(
    {
        "slot-01-fufang-ganmaoling",
        "slot-02-centrum",
        "slot-03-diosmectite",
        "slot-04-amoxicillin",
        "slot-05-nin-jiom-pei-pa-koa",
        "slot-06-lactulose",
        "slot-07-yinhuang",
        "slot-08-huoxiang-zhengqi",
        "slot-09-bifid-triple",
        "slot-10-gauze",
        "slot-11-guilin-xiguashuang",
        "slot-12-hydrotalcite",
        "slot-13-ibuprofen",
        "slot-14-oseltamivir",
        "slot-15-mupirocin",
        "slot-16-ketoconazole",
        "slot-17-iodophor",
        "slot-18-budesonide-nasal",
        "slot-19-ketoprofen-gel",
        "slot-20-bandage",
        "slot-21-amlodipine",
        "slot-22-cotton-swab",
        "slot-23-desloratadine",
    }
)


@dataclass(frozen=True)
class InventoryObservationToken:
    stock: int
    revision: int


NON_DRUG_COMBINATION_BASELINE_IDS = frozenset(
    {"slot-10-gauze", "slot-20-bandage", "slot-22-cotton-swab"}
)


# Compatibility seed only. Inquiry decisions read these facts from SQLite via
# Medicine entities; this mapping is never consulted by the runtime safety path.
LEGACY_V3_MEDICINE_SAFETY_FACTS: dict[str, dict[str, tuple[str, ...]]] = {
    "slot-01-fufang-ganmaoling": {
        "aliases": ("复方感冒灵", "999感冒灵"),
        "active_ingredients": ("对乙酰氨基酚",),
    },
    "slot-02-centrum": {"aliases": ("善存", "多维元素"), "active_ingredients": ()},
    "slot-03-diosmectite": {
        "aliases": ("思密达", "蒙脱石"),
        "active_ingredients": ("蒙脱石",),
    },
    "slot-04-amoxicillin": {"aliases": ("阿莫西林",), "active_ingredients": ("阿莫西林",)},
    "slot-05-nin-jiom-pei-pa-koa": {
        "aliases": ("京都念慈庵", "川贝枇杷膏", "枇杷膏"),
        "active_ingredients": (),
    },
    "slot-06-lactulose": {"aliases": ("乳果糖",), "active_ingredients": ("乳果糖",)},
    "slot-07-yinhuang": {"aliases": ("银黄", "银黄颗粒"), "active_ingredients": ()},
    "slot-08-huoxiang-zhengqi": {"aliases": ("藿香正气",), "active_ingredients": ()},
    "slot-09-bifid-triple": {"aliases": ("贝飞达", "双歧杆菌三联活菌"), "active_ingredients": ()},
    "slot-10-gauze": {"aliases": ("医用纱布", "纱布"), "active_ingredients": ()},
    "slot-11-guilin-xiguashuang": {"aliases": ("桂林西瓜霜", "西瓜霜"), "active_ingredients": ()},
    "slot-12-hydrotalcite": {"aliases": ("铝碳酸镁",), "active_ingredients": ("铝碳酸镁",)},
    "slot-13-ibuprofen": {"aliases": ("芬必得", "布洛芬"), "active_ingredients": ("布洛芬",)},
    "slot-14-oseltamivir": {"aliases": ("奥司他韦", "磷酸奥司他韦"), "active_ingredients": ("奥司他韦",)},
    "slot-15-mupirocin": {"aliases": ("莫匹罗星",), "active_ingredients": ("莫匹罗星",)},
    "slot-16-ketoconazole": {"aliases": ("酮康唑",), "active_ingredients": ("酮康唑",)},
    "slot-17-iodophor": {"aliases": ("碘伏", "聚维酮碘"), "active_ingredients": ("聚维酮碘",)},
    "slot-18-budesonide-nasal": {"aliases": ("雷诺考特", "布地奈德"), "active_ingredients": ("布地奈德",)},
    "slot-19-ketoprofen-gel": {"aliases": ("法斯通", "酮洛芬"), "active_ingredients": ("酮洛芬",)},
    "slot-20-bandage": {"aliases": ("创口贴",), "active_ingredients": ()},
    "slot-21-amlodipine": {"aliases": ("氨氯地平",), "active_ingredients": ("氨氯地平",)},
    "slot-22-cotton-swab": {"aliases": ("医用棉签", "棉签"), "active_ingredients": ()},
    "slot-23-desloratadine": {"aliases": ("枸地氯雷他定",), "active_ingredients": ("枸地氯雷他定",)},
}


DEFAULT_MEDICINE_SAFETY_FACTS: dict[str, dict[str, tuple[str, ...]]] = {
    **LEGACY_V3_MEDICINE_SAFETY_FACTS,
    "slot-01-fufang-ganmaoling": {
        "aliases": ("复方感冒灵", "999感冒灵"),
        "active_ingredients": (
            "山银花",
            "五指柑",
            "野菊花",
            "三叉苦",
            "南板蓝根",
            "岗梅",
            "对乙酰氨基酚",
            "马来酸氯苯那敏",
            "咖啡因",
        ),
    },
    "slot-02-centrum": {
        "aliases": ("善存", "多维元素", "复合维生素矿物质"),
        # The cabinet record does not distinguish (29) from (29-II). Keep the
        # union of label-listed micronutrients so duplicate-use checks fail
        # conservatively instead of treating one aggregate phrase as a fact.
        "active_ingredients": (
            "维生素A",
            "β-胡萝卜素",
            "维生素D",
            "维生素E",
            "维生素B1",
            "维生素B2",
            "维生素B6",
            "维生素C",
            "维生素B12",
            "维生素K1",
            "生物素",
            "叶酸",
            "烟酰胺",
            "泛酸",
            "钙",
            "磷",
            "钾",
            "氯",
            "镁",
            "铁",
            "铜",
            "锌",
            "锰",
            "碘",
            "铬",
            "钼",
            "硒",
            "镍",
            "硅",
            "锡",
            "钒",
        ),
    },
    "slot-05-nin-jiom-pei-pa-koa": {
        "aliases": ("京都念慈庵", "京都念慈菴", "川贝枇杷膏", "枇杷膏"),
        "active_ingredients": ("川贝母", "枇杷叶", "化橘红", "桔梗", "法半夏", "蜂蜜"),
    },
    "slot-07-yinhuang": {
        "aliases": ("银黄", "银黄颗粒", "希臣"),
        "active_ingredients": ("金银花提取物", "黄芩提取物"),
    },
    "slot-08-huoxiang-zhengqi": {
        "aliases": ("藿香正气", "恒心堂", "利君"),
        "active_ingredients": (
            "广藿香",
            "苍术（炒）",
            "白芷",
            "陈皮",
            "茯苓",
            "厚朴（姜制）",
            "紫苏叶",
            "大腹皮",
            "半夏（姜制）",
            "甘草",
        ),
    },
    "slot-09-bifid-triple": {
        "aliases": ("贝飞达", "双歧杆菌三联活菌"),
        "active_ingredients": ("长型双歧杆菌", "嗜酸乳杆菌", "粪肠球菌"),
    },
    "slot-11-guilin-xiguashuang": {
        "aliases": ("桂林西瓜霜", "西瓜霜", "三金桂林西瓜霜", "三金"),
        "active_ingredients": (
            "西瓜霜",
            "煅硼砂",
            "黄柏",
            "黄连",
            "山豆根",
            "射干",
            "浙贝母",
            "青黛",
            "冰片",
            "无患子果（炭）",
            "大黄",
            "黄芩",
            "甘草",
            "薄荷脑",
        ),
    },
}


LEGACY_V4_MEDICINE_SAFETY_FACTS: dict[str, dict[str, tuple[str, ...]]] = {
    "slot-02-centrum": {
        "aliases": ("善存", "多维元素", "复合维生素矿物质"),
        "active_ingredients": ("复合维生素和矿物质",),
    },
    "slot-08-huoxiang-zhengqi": {
        "aliases": ("藿香正气", "恒心堂"),
        "active_ingredients": DEFAULT_MEDICINE_SAFETY_FACTS[
            "slot-08-huoxiang-zhengqi"
        ]["active_ingredients"],
    },
    "slot-11-guilin-xiguashuang": {
        "aliases": ("桂林西瓜霜", "西瓜霜", "三金桂林西瓜霜"),
        "active_ingredients": DEFAULT_MEDICINE_SAFETY_FACTS[
            "slot-11-guilin-xiguashuang"
        ]["active_ingredients"],
    },
}


LEGACY_V4_MEDICINE_LABEL_SAFETY: dict[str, dict[str, object]] = {
    "slot-13-ibuprofen": {
        "contraindications": (
            "非甾体抗炎药过敏者禁用",
            "孕妇及哺乳期妇女禁用",
            "阿司匹林过敏的哮喘患者禁用",
        ),
        "safety_note": (
            "联网条码身份：芬必得，0.3g×24粒，国药准字H10900089；"
            "整粒吞服，避免与其他解热镇痛药重复使用。"
        ),
    }
}


LEGACY_V5_STRUCTURED_SAFETY_FACTS: dict[str, list[dict[str, str]]] = {
    "slot-19-ketoprofen-gel": [
        {
            "concept_code": "label_warning",
            "display_text": "非甾体抗炎药过敏禁用",
        },
        {
            "concept_code": "peptic_ulcer",
            "display_text": "活动性消化道溃疡禁用",
        },
    ]
}


CONTRAINDICATION_CONCEPT_TERMS: dict[str, tuple[str, ...]] = {
    "diabetes": ("糖尿病", "糖代谢异常"),
    "renal_impairment": ("肾功能", "肾损害", "肾衰", "肾病"),
    "liver_impairment": ("肝功能", "肝损害", "肝病"),
    "cardiac_disease": ("严重心脏疾病", "严重心脏病", "严重心力衰竭"),
    "hypercalcemia": ("高钙血症",),
    "hyperphosphatemia": ("高磷血症",),
    "hypophosphatemia": ("低磷血症",),
    "myasthenia_gravis": ("重症肌无力",),
    "galactose_intolerance": ("半乳糖不耐受",),
    "intestinal_obstruction": ("肠梗阻",),
    "peptic_ulcer": ("消化道溃疡", "消化性溃疡", "胃溃疡"),
    "gastrointestinal_bleeding": ("胃肠道出血", "消化道出血", "胃出血"),
    "gastrointestinal_perforation": ("胃肠道穿孔", "消化道穿孔", "穿孔"),
    "hypotension": ("低血压",),
    "pregnancy": ("孕妇", "怀孕", "妊娠"),
    "breastfeeding": ("哺乳",),
    "asthma": ("哮喘",),
    "nsaid_allergy": ("非甾体抗炎药过敏", "阿司匹林或其他非甾体抗炎药过敏"),
}

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
        "id": "slot-03-diosmectite",
        "slot": "S03",
        "hardware_slot": 3,
        "barcode": "6932833600109",
        "manufacturer": "博福-益普生（天津）制药有限公司",
        "name": "蒙脱石散",
        "category": "肠胃",
        "tags": ["思密达", "急性腹泻", "3g×10袋", "国药准字H20000690"],
        "contraindications": ["对本品过敏者禁用", "便血、持续高热或剧烈腹痛时不可自行用药"],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2030-02",
        "image_hint": "思密达 蒙脱石散 3g×10袋（草莓味）",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "联网条码身份：思密达，3g×10袋（草莓味），国药准字H20000690；急性腹泻需同时注意补液。",
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
        "contraindications": ["对成分过敏禁用", "糖尿病患者禁用"],
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
        "id": "slot-13-ibuprofen",
        "slot": "S13",
        "hardware_slot": 13,
        "barcode": "6913991301572",
        "manufacturer": "中美天津史克制药有限公司",
        "name": "布洛芬缓释胶囊",
        "category": "解热镇痛",
        "tags": ["芬必得", "退热", "头痛", "痛经", "0.3g×24粒", "国药准字H10900089"],
        "contraindications": [
            "对布洛芬、辅料、阿司匹林或其他非甾体抗炎药过敏者禁用",
            "孕妇及哺乳期妇女禁用",
            "阿司匹林或其他非甾体抗炎药诱发哮喘者禁用",
            "严重肝功能不全、肾功能不全或严重心脏疾病患者禁用",
            "活动性消化性溃疡、胃肠道出血或穿孔患者禁用",
            "既往使用非甾体抗炎药后发生胃肠道出血或穿孔者禁用",
            "除医嘱外不得同时使用其他布洛芬、非甾体抗炎药或解热镇痛药",
        ],
        "stock": 1,
        "unit": "盒",
        "expire_date": "2029-01",
        "image_hint": "芬必得 布洛芬缓释胶囊",
        "is_otc": True,
        "is_emergency": False,
        "safety_note": "联网条码身份：芬必得，0.3g×24粒，国药准字H10900089；整粒吞服，使用前核对消化道、肝肾、心脏风险及其他解热镇痛药。",
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

DEFAULT_MEDICINE_GUIDANCE = {
    "slot-01-fufang-ganmaoling": {
        "indications": "辛凉解表，清热解毒。用于风热感冒之发热，微恶风寒，头身痛，口干而渴，鼻塞涕浊，咽喉红肿疼痛，咳嗽，痰黄粘稠。",
        "dosage": "开水冲服，一次14克，一日3次；2天为一疗程。",
    },
    "slot-02-centrum": {
        "indications": "用于预防和治疗因维生素与矿物质缺乏所引起的各种疾病。",
        "dosage": "口服，成人一日1片。",
    },
    "slot-03-diosmectite": {
        "indications": "用于成人及儿童急、慢性腹泻。治疗急性腹泻时应注意纠正脱水。",
        "dosage": "口服，成人一次1袋（3克），一日3次；1岁以下每日1袋，1至2岁每日1至2袋，2岁以上每日2至3袋，儿童均分3次服用。治疗急性腹泻时首次剂量加倍；倒入约50毫升温开水中混匀后服用。",
    },
    "slot-04-amoxicillin": {
        "indications": "用于敏感菌所致的上、下呼吸道感染，泌尿生殖道感染，皮肤软组织感染等。仅在医生判断为细菌感染并已有处方或医嘱时使用。",
        "dosage": "口服，成人一次0.5克，每6至8小时1次，一日剂量不超过4克。本品为0.5克规格时每次1粒；具体疗程遵医嘱。",
    },
    "slot-05-nin-jiom-pei-pa-koa": {
        "indications": "润肺化痰、止咳平喘、护喉利咽、生津补气、调心降火。用于伤风咳嗽、痰稠、痰多气喘、咽喉干痒及声音嘶哑。",
        "dosage": "口服，成人每日3次，每次1汤匙（15毫升）；儿童酌减。",
    },
    "slot-06-lactulose": {
        "indications": "用于慢性或习惯性便秘，调节结肠的生理节律；也可在医生指导下用于肝性脑病。",
        "dosage": "治疗成人便秘时，起始剂量每日30毫升，维持剂量每日10至25毫升，宜在早餐时一次服用并按排便情况调整。",
    },
    "slot-07-yinhuang": {
        "indications": "清热疏风，利咽解毒。用于外感风热、肺胃热盛所致的咽干、咽痛、喉核肿大、口渴、发热；急慢性扁桃体炎、急慢性咽炎、上呼吸道感染见上述证候者。",
        "dosage": "开水冲服，一次1至2袋，一日2次。",
    },
    "slot-08-huoxiang-zhengqi": {
        "indications": "解表化湿，理气和中。用于暑湿感冒，头痛身重胸闷，或恶寒发热，脘腹胀痛，呕吐泄泻。",
        "dosage": "口服，一次1丸，一日2次。",
    },
    "slot-09-bifid-triple": {
        "indications": "用于肠道菌群失调引起的急慢性腹泻、便秘，也可用于轻中型急性腹泻、慢性腹泻及消化不良。",
        "dosage": "口服，成人一次2至4粒，一日2次。",
    },
    "slot-10-gauze": {
        "indications": "供医疗机构或家庭护理中清洁后的浅表伤口覆盖、吸收渗液、隔离保护和辅助包扎使用。",
        "dosage": "一次性外用。清洁伤口后按创面选择合适尺寸覆盖；敷料受潮、污染或松脱时立即更换。",
    },
    "slot-11-guilin-xiguashuang": {
        "indications": "清热解毒，消肿止痛。用于风热上攻、肺胃热盛所致的咽喉肿痛、喉核肿大、口舌生疮、牙龈肿痛或出血，以及相应的咽炎、扁桃体炎、口腔炎和口腔溃疡。",
        "dosage": "外用，喷、吹或敷于患处，一次适量，一日数次。",
    },
    "slot-12-hydrotalcite": {
        "indications": "用于慢性胃炎，以及与胃酸有关的胃部不适症状，如胃痛、胃灼热感（烧心）、酸性嗳气、饱胀等。",
        "dosage": "口服，咀嚼后吞服。一次1至2片，一日3次，通常在餐后1至2小时、睡前或胃部不适时服用。",
    },
    "slot-13-ibuprofen": {
        "indications": "用于缓解轻至中度疼痛，如头痛、关节痛、偏头痛、牙痛、肌肉痛、神经痛、痛经；也用于普通感冒或流行性感冒引起的发热。",
        "dosage": "口服，成人一次1粒（0.3克），一日2次，早晚各一次；整粒吞服，不得打开或溶解。儿童用量请咨询医师或药师。",
    },
    "slot-14-oseltamivir": {
        "indications": "用于成人和1岁及1岁以上儿童的甲型和乙型流感治疗，也可在医生指导下用于流感预防。",
        "dosage": "治疗成人及13岁以上青少年流感时，口服一次75毫克，一日2次，共5天。",
    },
    "slot-15-mupirocin": {
        "indications": "局部外用抗生素，用于革兰阳性球菌引起的脓疱病、疖肿、毛囊炎等原发性皮肤感染，以及湿疹或小面积浅表创伤合并的继发性皮肤感染。",
        "dosage": "局部外用，涂于患处，一日3次，5天为一疗程；必要时可用敷料包扎或敷盖。",
    },
    "slot-16-ketoconazole": {
        "indications": "用于手癣、足癣、体癣、股癣、花斑癣及皮肤念珠菌病等浅表真菌感染。",
        "dosage": "局部外用，取适量均匀涂于患处，一日2至3次。症状消失后按说明书继续使用，避免过早停药。",
    },
    "slot-17-iodophor": {
        "indications": "用于完整皮肤、浅表创面及伤口周围皮肤的清洁与消毒。",
        "dosage": "仅限外用。用无菌棉签或纱布蘸取原液涂擦消毒部位；具体作用时间和使用范围以瓶身标签为准。",
    },
    "slot-18-budesonide-nasal": {
        "indications": "治疗季节性和常年性过敏性鼻炎，以及常年性非过敏性鼻炎。",
        "dosage": "成人及6岁以上儿童推荐起始剂量一日256微克：早晨每个鼻孔2喷；或早晚各1次、每次每个鼻孔1喷。症状控制后减至最低有效剂量。",
    },
    "slot-19-ketoprofen-gel": {
        "indications": "用于各种骨骼肌损伤、急性软组织损伤，以及由外伤、扭伤、挫伤、劳损等引起的局部疼痛和炎症。",
        "dosage": "外用，按疼痛部位大小取适量轻轻揉搓，一日1至2次。",
    },
    "slot-20-bandage": {
        "indications": "用于浅表性小创口、擦伤等清洁止血后的覆盖、隔离和日常保护。",
        "dosage": "一次性外用。清洁并擦干伤口后选择合适尺寸贴敷；受潮、污染、松脱或至少每日检查时更换。",
    },
    "slot-21-amlodipine": {
        "indications": "用于高血压，可单独使用或与其他降压药合用；也用于慢性稳定性心绞痛及血管痉挛性心绞痛。",
        "dosage": "成人治疗高血压通常起始剂量为5毫克，一日1次，最大剂量10毫克，一日1次。",
    },
    "slot-22-cotton-swab": {
        "indications": "用于皮肤、浅表创面清洁或消毒时蘸取和涂抹外用液体。",
        "dosage": "一次性外用，每根仅使用一次。",
    },
    "slot-23-desloratadine": {
        "indications": "用于快速缓解过敏性鼻炎相关的喷嚏、流涕、鼻痒、鼻塞、眼痒流泪等症状，也用于缓解慢性特发性荨麻疹的瘙痒并减少风团。",
        "dosage": "成人及12岁以上青少年口服，每日1次，每次1粒。",
    },
}

for _medicine in DEFAULT_MEDICINES:
    _guidance = DEFAULT_MEDICINE_GUIDANCE[_medicine["id"]]
    _medicine.update(
        indications=_guidance["indications"],
        dosage=_guidance["dosage"],
        guidance_source=_guidance.get("guidance_source", "label_reference"),
        guidance_review_required=True,
        package_verified=True,
    )


MEDICINE_COMBINATION_POLICY_VERSION = "official-evidence-enabled-v1"
MEDICINE_COMBINATION_POLICY_PROVENANCE = "official-health-guidance-bundled-v1"
MEDICINE_COMBINATION_POLICY_REVIEWER = "bundled-clinical-policy-v1"
DEFAULT_MEDICINE_COMBINATIONS: tuple[dict[str, object], ...] = (
    {
        "combination_id": "candidate-superficial-wound-bandage-v1",
        "label": "浅表小伤口消毒与创口贴覆盖",
        "medicine_ids": (
            "slot-17-iodophor",
            "slot-22-cotton-swab",
            "slot-20-bandage",
        ),
        "applicability": {
            "required_all_facts": (
                "superficial_wound",
                "bleeding_controlled",
                "small_dry_wound",
            ),
            "must_be_absent_facts": (
                "deep_wound",
                "animal_bite",
                "continued_bleeding",
                "wound_infection",
                "embedded_foreign_body",
            ),
            "member_required_any_facts": {
                "slot-17-iodophor": ("superficial_wound",),
                "slot-22-cotton-swab": ("superficial_wound",),
                "slot-20-bandage": ("small_dry_wound",),
            },
            "allowed_risk_levels": ("low",),
        },
        "reviewed_usage_by_medicine": {
            "slot-17-iodophor": "伤口清洁后，按瓶身说明对浅表创面或周围皮肤消毒。",
            "slot-22-cotton-swab": "一次性蘸取消毒液并涂抹，接触伤口后不得重复蘸取。",
            "slot-20-bandage": "待伤口干燥后，按产品说明覆盖小而浅的伤口。",
        },
        "evidence_refs": (
            {
                "source_title": "北京市卫生健康委员会伤口护理常识",
                "source_url": (
                    "https://wjw.beijing.gov.cn/bmfw_20143/jkzs/jksh/"
                    "202602/t20260210_4505416.html"
                ),
                "supports": "浅表伤口清洁消毒后可按伤口情况使用创可贴覆盖。",
            },
            {
                "source_title": "国家药监局一次性使用棉签产品使用说明书",
                "source_url": "https://qxzc.nmpa.gov.cn/upload/ba/1478673311662.pdf",
                "supports": "医用棉签可用于机械创伤部位的局部涂抹消毒。",
            },
        ),
        "review_note": "受控内置方案；仅限出血已控制、无感染或深部损伤信号的小而浅伤口。",
    },
    {
        "combination_id": "candidate-superficial-wound-gauze-v1",
        "label": "浅表伤口消毒与无菌纱布覆盖",
        "medicine_ids": (
            "slot-17-iodophor",
            "slot-22-cotton-swab",
            "slot-10-gauze",
        ),
        "applicability": {
            "required_all_facts": (
                "superficial_wound",
                "bleeding_controlled",
                "needs_gauze_cover",
            ),
            "must_be_absent_facts": (
                "deep_wound",
                "animal_bite",
                "continued_bleeding",
                "wound_infection",
                "embedded_foreign_body",
            ),
            "member_required_any_facts": {
                "slot-17-iodophor": ("superficial_wound",),
                "slot-22-cotton-swab": ("superficial_wound",),
                "slot-10-gauze": ("needs_gauze_cover",),
            },
            "allowed_risk_levels": ("low",),
        },
        "reviewed_usage_by_medicine": {
            "slot-17-iodophor": "伤口清洁后，按瓶身说明对浅表创面或周围皮肤消毒。",
            "slot-22-cotton-swab": "一次性蘸取消毒液并涂抹，接触伤口后不得重复蘸取。",
            "slot-10-gauze": "按产品说明覆盖清洁后的浅表伤口，受潮或污染后更换。",
        },
        "evidence_refs": (
            {
                "source_title": "北京市卫生健康委员会伤口护理常识",
                "source_url": (
                    "https://wjw.beijing.gov.cn/bmfw_20143/jkzs/jksh/"
                    "202602/t20260210_4505416.html"
                ),
                "supports": "浅表伤口清洁消毒后可按伤口情况使用无菌纱布覆盖。",
            },
            {
                "source_title": "国家药监局一次性使用棉签产品使用说明书",
                "source_url": "https://qxzc.nmpa.gov.cn/upload/ba/1478673311662.pdf",
                "supports": "医用棉签可用于机械创伤部位的局部涂抹消毒。",
            },
        ),
        "review_note": "受控内置方案；仅限出血已控制、无感染或深部损伤信号且需敷料覆盖的浅表伤口。",
    },
    {
        "combination_id": "candidate-adult-watery-diarrhea-separated-v1",
        "label": "成人无危险信号水样腹泻分时用药",
        "medicine_ids": (
            "slot-03-diosmectite",
            "slot-09-bifid-triple",
        ),
        "applicability": {
            "required_all_facts": (
                "acute_watery_diarrhea",
                "oral_intake_tolerated",
            ),
            "must_be_absent_facts": (
                "bloody_stool",
                "black_stool",
                "persistent_high_fever",
                "severe_abdominal_pain",
                "significant_dehydration",
                "persistent_vomiting",
            ),
            "member_required_any_facts": {
                "slot-03-diosmectite": ("acute_watery_diarrhea",),
                "slot-09-bifid-triple": ("acute_watery_diarrhea",),
            },
            "allowed_risk_levels": ("low",),
            "min_age_years": 18,
        },
        "reviewed_usage_by_medicine": {
            "slot-03-diosmectite": "补液优先；如需使用，先按药品说明书单独服用蒙脱石散。",
            "slot-09-bifid-triple": "与蒙脱石散间隔至少 2 小时后，再按药品说明书服用。",
        },
        "evidence_refs": (
            {
                "source_title": "湖北省卫生健康委员会腹泻用药科普",
                "source_url": (
                    "https://wjw.hubei.gov.cn/bmdt/mtjj/mtgz/"
                    "202301/t20230109_4481080.shtml"
                ),
                "supports": "蒙脱石散应与其他药物错开，益生菌可用于支持肠道菌群恢复。",
            },
            {
                "source_title": "海南省药物警戒中心蒙脱石散用药提醒",
                "source_url": (
                    "https://amr.hainan.gov.cn/himpa/adr/kpxc/"
                    "202408/t20240813_3714421.html"
                ),
                "supports": "蒙脱石散与其他药物应间隔，并需排除高热、剧烈腹痛和脱水等就医信号。",
            },
        ),
        "review_note": "受控内置方案；仅限成人低风险急性水样腹泻，先补液并排除全部危险信号。",
    },
)


class MedicineRepository:
    COMBINATION_SENSITIVE_FIELDS = frozenset(
        {
            "name",
            "manufacturer",
            "barcode",
            "category",
            "spec",
            "tags",
            "aliases",
            "active_ingredients",
            "indications",
            "dosage",
            "contraindications",
            "structured_contraindications",
            "expire_date",
            "is_otc",
            "is_emergency",
            "safety_note",
            "guidance_source",
            "guidance_review_required",
            "package_verified",
            "guidance_updated_at",
            "safety_review_status",
            "safety_reviewed_by",
            "safety_reviewed_at",
        }
    )

    def save_approved_combination(
        self,
        *,
        combination_id: str,
        label: str,
        medicine_ids: list[str],
        clinical_policy_version: str = "",
        applicability: MedicineCombinationApplicability | dict[str, object] | None = None,
        reviewed_usage_by_medicine: dict[str, str] | None = None,
        evidence_refs: list[MedicineCombinationEvidenceRef | dict[str, str]] | None = None,
        provenance: str = "",
        review_note: str = "",
        review_status: str = "draft",
        reviewed_by: str = "",
        reviewed_at: str = "",
    ) -> ApprovedMedicineCombination:
        self._ensure_seeded()
        normalized_combination_id = combination_id.strip()
        normalized_label = label.strip()
        if not normalized_combination_id or not normalized_label:
            raise ValueError("药师核验组合必须填写稳定 ID 和展示名称。")
        normalized_status = review_status.strip().lower() or "draft"
        if normalized_status not in {"draft", "reviewed"}:
            raise ValueError("组合审核状态只能是 draft 或 reviewed。")
        normalized_reviewer = reviewed_by.strip()
        normalized_reviewed_at = reviewed_at.strip()
        if normalized_status == "reviewed" and (
            not normalized_reviewer or not normalized_reviewed_at
        ):
            raise ValueError("已审核组合必须填写审核人和审核时间。")
        normalized_ids = [str(item).strip() for item in medicine_ids if str(item).strip()]
        if not 2 <= len(normalized_ids) <= 4 or len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError("药师核验组合必须包含 2 至 4 种互不重复的药品。")
        normalized_policy_version = clinical_policy_version.strip()
        normalized_applicability = self._normalize_combination_applicability(
            applicability,
        )
        normalized_usage = {
            str(medicine_id).strip(): str(usage).strip()
            for medicine_id, usage in (reviewed_usage_by_medicine or {}).items()
            if str(medicine_id).strip()
        }
        normalized_evidence = [
            MedicineCombinationEvidenceRef.model_validate(item)
            for item in (evidence_refs or [])
        ]
        normalized_provenance = provenance.strip()
        normalized_review_note = review_note.strip()
        has_case_contract = any(
            (
                normalized_policy_version,
                normalized_applicability.required_all_facts,
                normalized_applicability.required_any_facts,
                normalized_applicability.must_be_absent_facts,
                normalized_applicability.member_required_any_facts,
                normalized_applicability.allowed_risk_levels,
                normalized_usage,
                normalized_evidence,
                normalized_provenance,
                normalized_review_note,
            )
        )
        if has_case_contract:
            self._validate_case_review_contract(
                medicine_ids=normalized_ids,
                clinical_policy_version=normalized_policy_version,
                applicability=normalized_applicability,
                reviewed_usage_by_medicine=normalized_usage,
                evidence_refs=normalized_evidence,
                provenance=normalized_provenance,
                review_note=normalized_review_note,
            )
        updated_at = db.now_text()
        with db.connect() as conn:
            # Acquire the SQLite writer lock before reading member rows. The
            # reviewed snapshot and combination upsert therefore cannot be
            # interleaved with a medicine identity or safety update.
            conn.execute("BEGIN IMMEDIATE")
            member_identity_fingerprints: dict[str, str] = {}
            member_review_fingerprints: dict[str, str] = {}
            if normalized_status == "reviewed" or has_case_contract:
                placeholders = ",".join("?" for _ in normalized_ids)
                rows = conn.execute(
                    f"SELECT * FROM medicines WHERE id IN ({placeholders})",
                    tuple(normalized_ids),
                ).fetchall()
                by_id = {
                    str(row["id"]): self._row_to_medicine(row)
                    for row in rows
                }
                members = [by_id.get(medicine_id) for medicine_id in normalized_ids]
                if any(member is None for member in members):
                    raise ValueError("已审核组合中的每种药品都必须具有当前可核验身份。")
                if any(
                    member.safety_review_status != "reviewed"
                    or not member.safety_reviewed_by.strip()
                    or not member.safety_reviewed_at.strip()
                    for member in members
                    if member is not None
                ):
                    raise ValueError("组合成员必须先完成可追溯的安全资料审核。")
                if any(
                    not member.active_ingredients
                    and not self._is_controlled_non_drug_supply(member)
                    for member in members
                    if member is not None
                ):
                    raise ValueError("药品组合成员必须具有非空的已审核有效成分。")
                member_identity_fingerprints = {
                    member.id: self._identity_fingerprint(
                        name=member.name,
                        manufacturer=member.manufacturer,
                        barcode=member.barcode,
                        spec=member.spec,
                        category=member.category,
                    )
                    for member in members
                    if member is not None
                }
                member_review_fingerprints = {
                    member.id: self.review_fingerprint(member)
                    for member in members
                    if member is not None
                }
            conn.execute(
                """
                INSERT INTO approved_medicine_combinations(
                  combination_id, label, medicine_ids_json,
                  member_identity_fingerprints_json, clinical_policy_version,
                  applicability_json, member_review_fingerprints_json,
                  reviewed_usage_json, evidence_refs_json, provenance, review_note,
                  review_status, reviewed_by, reviewed_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(combination_id) DO UPDATE SET
                  label=excluded.label,
                  medicine_ids_json=excluded.medicine_ids_json,
                  member_identity_fingerprints_json=excluded.member_identity_fingerprints_json,
                  clinical_policy_version=excluded.clinical_policy_version,
                  applicability_json=excluded.applicability_json,
                  member_review_fingerprints_json=excluded.member_review_fingerprints_json,
                  reviewed_usage_json=excluded.reviewed_usage_json,
                  evidence_refs_json=excluded.evidence_refs_json,
                  provenance=excluded.provenance,
                  review_note=excluded.review_note,
                  review_status=excluded.review_status,
                  reviewed_by=excluded.reviewed_by,
                  reviewed_at=excluded.reviewed_at,
                  updated_at=excluded.updated_at
                """,
                (
                    normalized_combination_id,
                    normalized_label,
                    json.dumps(normalized_ids, ensure_ascii=False),
                    json.dumps(member_identity_fingerprints, ensure_ascii=False, sort_keys=True),
                    normalized_policy_version,
                    json.dumps(
                        normalized_applicability.model_dump(),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        member_review_fingerprints,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(normalized_usage, ensure_ascii=False, sort_keys=True),
                    json.dumps(
                        [item.model_dump() for item in normalized_evidence],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    normalized_provenance,
                    normalized_review_note,
                    normalized_status,
                    normalized_reviewer,
                    normalized_reviewed_at,
                    updated_at,
                ),
            )
        return ApprovedMedicineCombination(
            combination_id=normalized_combination_id,
            label=normalized_label,
            medicine_ids=normalized_ids,
            member_identity_fingerprints=member_identity_fingerprints,
            clinical_policy_version=normalized_policy_version,
            applicability=normalized_applicability,
            member_review_fingerprints=member_review_fingerprints,
            reviewed_usage_by_medicine=normalized_usage,
            evidence_refs=normalized_evidence,
            provenance=normalized_provenance,
            review_note=normalized_review_note,
            review_status=normalized_status,
            reviewed_by=normalized_reviewer,
            reviewed_at=normalized_reviewed_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _normalize_combination_applicability(
        applicability: MedicineCombinationApplicability | dict[str, object] | None,
    ) -> MedicineCombinationApplicability:
        parsed = MedicineCombinationApplicability.model_validate(applicability or {})

        def normalized_codes(values: list[str]) -> list[str]:
            return list(
                dict.fromkeys(
                    str(value).strip().lower()
                    for value in values
                    if str(value).strip()
                )
            )

        return MedicineCombinationApplicability(
            required_all_facts=normalized_codes(parsed.required_all_facts),
            required_any_facts=normalized_codes(parsed.required_any_facts),
            must_be_absent_facts=normalized_codes(parsed.must_be_absent_facts),
            member_required_any_facts={
                str(medicine_id).strip(): normalized_codes(facts)
                for medicine_id, facts in parsed.member_required_any_facts.items()
                if str(medicine_id).strip()
            },
            allowed_risk_levels=normalized_codes(parsed.allowed_risk_levels),
            min_age_years=parsed.min_age_years,
            max_age_years=parsed.max_age_years,
        )

    @staticmethod
    def _validate_case_review_contract(
        *,
        medicine_ids: list[str],
        clinical_policy_version: str,
        applicability: MedicineCombinationApplicability,
        reviewed_usage_by_medicine: dict[str, str],
        evidence_refs: list[MedicineCombinationEvidenceRef],
        provenance: str,
        review_note: str,
    ) -> None:
        member_ids = set(medicine_ids)
        member_required = applicability.member_required_any_facts
        allowed_risk_levels = set(applicability.allowed_risk_levels)
        if clinical_policy_version != MEDICINE_COMBINATION_CLINICAL_POLICY_VERSION:
            raise ValueError("病例适用规则版本不受支持。")
        if not applicability.required_all_facts and not applicability.required_any_facts:
            raise ValueError("病例适用规则必须包含明确的阳性适用条件。")
        if set(member_required) != member_ids or any(
            not member_required[medicine_id] for medicine_id in medicine_ids
        ):
            raise ValueError("病例适用规则必须逐一说明每个组合成员的适用症状。")
        if not allowed_risk_levels or not allowed_risk_levels <= {"low", "medium"}:
            raise ValueError("组合仅能配置明确的低或中风险病例等级。")
        if (
            applicability.min_age_years is not None
            and applicability.max_age_years is not None
            and applicability.min_age_years > applicability.max_age_years
        ):
            raise ValueError("组合适用年龄范围无效。")
        if set(reviewed_usage_by_medicine) != member_ids or any(
            not reviewed_usage_by_medicine[medicine_id]
            for medicine_id in medicine_ids
        ):
            raise ValueError("审核用法必须完整覆盖每个组合成员。")
        if not evidence_refs or any(
            not evidence.source_title.strip()
            or not evidence.source_url.strip()
            or not evidence.supports.strip()
            for evidence in evidence_refs
        ):
            raise ValueError("病例组合必须记录完整的审核证据。")
        if not provenance or not review_note:
            raise ValueError("病例组合必须记录来源和审核说明。")

    @classmethod
    def _is_controlled_non_drug_supply(cls, medicine: Medicine) -> bool:
        current_fingerprint = cls._identity_fingerprint(
            name=medicine.name,
            manufacturer=medicine.manufacturer,
            barcode=medicine.barcode,
            spec=medicine.spec,
            category=medicine.category,
        )
        baseline_fingerprints = {
            cls._identity_fingerprint(
                name=item.get("name"),
                manufacturer=item.get("manufacturer"),
                barcode=item.get("barcode"),
                spec=item.get("spec"),
                category=item.get("category"),
            )
            for item in DEFAULT_MEDICINES
            if str(item.get("id")) in NON_DRUG_COMBINATION_BASELINE_IDS
        }
        return current_fingerprint in baseline_fingerprints

    def is_controlled_non_drug_supply(self, medicine_id: str) -> bool:
        medicine = self.get_by_id(medicine_id)
        return medicine is not None and self._is_controlled_non_drug_supply(medicine)

    def list_reviewed_combinations(self) -> list[ApprovedMedicineCombination]:
        self._ensure_seeded()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT combination_id, label, medicine_ids_json,
                       member_identity_fingerprints_json, review_status,
                       reviewed_by, reviewed_at, updated_at
                FROM approved_medicine_combinations
                WHERE review_status='reviewed'
                  AND TRIM(reviewed_by) <> ''
                  AND TRIM(reviewed_at) <> ''
                  AND TRIM(clinical_policy_version) = ''
                ORDER BY updated_at, combination_id
                """
            ).fetchall()
        combinations: list[ApprovedMedicineCombination] = []
        for row in rows:
            medicine_ids = json.loads(row["medicine_ids_json"] or "[]")
            member_identity_fingerprints = json.loads(
                row["member_identity_fingerprints_json"] or "{}"
            )
            if (
                not isinstance(medicine_ids, list)
                or not 2 <= len(medicine_ids) <= 4
                or len(set(medicine_ids)) != len(medicine_ids)
                or not isinstance(member_identity_fingerprints, dict)
                or set(member_identity_fingerprints) != set(medicine_ids)
                or any(
                    not str(member_identity_fingerprints[medicine_id]).strip()
                    for medicine_id in medicine_ids
                )
            ):
                continue
            combinations.append(
                ApprovedMedicineCombination(
                    combination_id=row["combination_id"],
                    label=row["label"],
                    medicine_ids=medicine_ids,
                    member_identity_fingerprints=member_identity_fingerprints,
                    review_status=row["review_status"],
                    reviewed_by=row["reviewed_by"],
                    reviewed_at=row["reviewed_at"],
                    updated_at=row["updated_at"],
                )
            )
        return combinations

    def list_case_reviewed_combinations(self) -> list[ApprovedMedicineCombination]:
        """Return only complete, case-scoped combination review records."""
        self._ensure_seeded()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT combination_id, label, medicine_ids_json,
                       member_identity_fingerprints_json,
                       clinical_policy_version, applicability_json,
                       member_review_fingerprints_json, reviewed_usage_json,
                       evidence_refs_json, provenance, review_note,
                       review_status, reviewed_by, reviewed_at, updated_at
                FROM approved_medicine_combinations
                WHERE review_status='reviewed'
                  AND TRIM(reviewed_by) <> ''
                  AND TRIM(reviewed_at) <> ''
                  AND clinical_policy_version=?
                ORDER BY updated_at, combination_id
                """,
                (MEDICINE_COMBINATION_CLINICAL_POLICY_VERSION,),
            ).fetchall()
        combinations: list[ApprovedMedicineCombination] = []
        for row in rows:
            try:
                combination = ApprovedMedicineCombination(
                    combination_id=row["combination_id"],
                    label=row["label"],
                    medicine_ids=json.loads(row["medicine_ids_json"] or "[]"),
                    member_identity_fingerprints=json.loads(
                        row["member_identity_fingerprints_json"] or "{}"
                    ),
                    clinical_policy_version=row["clinical_policy_version"] or "",
                    applicability=json.loads(row["applicability_json"] or "{}"),
                    member_review_fingerprints=json.loads(
                        row["member_review_fingerprints_json"] or "{}"
                    ),
                    reviewed_usage_by_medicine=json.loads(
                        row["reviewed_usage_json"] or "{}"
                    ),
                    evidence_refs=json.loads(row["evidence_refs_json"] or "[]"),
                    provenance=row["provenance"] or "",
                    review_note=row["review_note"] or "",
                    review_status=row["review_status"],
                    reviewed_by=row["reviewed_by"],
                    reviewed_at=row["reviewed_at"],
                    updated_at=row["updated_at"],
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            combinations.append(combination)
        return combinations

    def get_identity_fingerprints(self, medicine_ids: list[str]) -> dict[str, str]:
        self._ensure_seeded()
        normalized_ids = list(
            dict.fromkeys(str(medicine_id).strip() for medicine_id in medicine_ids if str(medicine_id).strip())
        )
        if not normalized_ids:
            return {}
        placeholders = ", ".join("?" for _ in normalized_ids)
        with db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, name, manufacturer, barcode, spec, category
                FROM medicines
                WHERE id IN ({placeholders})
                """,
                tuple(normalized_ids),
            ).fetchall()
        return {
            row["id"]: self._identity_fingerprint(
                name=row["name"],
                manufacturer=row["manufacturer"],
                barcode=row["barcode"],
                spec=row["spec"],
                category=row["category"],
            )
            for row in rows
        }

    @staticmethod
    def _identity_fingerprint(
        *,
        name: object,
        manufacturer: object,
        barcode: object,
        spec: object,
        category: object,
    ) -> str:
        identity = {
            "name": str(name or "").strip().lower(),
            "manufacturer": str(manufacturer or "").strip().lower(),
            "barcode": str(barcode or "").strip().lower(),
            "spec": str(spec or "").strip().lower(),
            "category": str(category or "").strip().lower(),
        }
        encoded = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def review_fingerprint(medicine: Medicine) -> str:
        """Bind combination review to the exact package and safety revision."""
        snapshot = {
            field: getattr(medicine, field)
            for field in (
                "name",
                "manufacturer",
                "barcode",
                "spec",
                "category",
                "expire_date",
                "package_verified",
                "guidance_source",
                "tags",
                "aliases",
                "active_ingredients",
                "indications",
                "dosage",
                "contraindications",
                "structured_contraindications",
                "safety_note",
                "is_otc",
                "safety_review_status",
                "safety_reviewed_by",
                "safety_reviewed_at",
            )
        }
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def save_ingredient_conflict(
        self,
        *,
        left_ingredient: str,
        right_ingredient: str,
        disposition: str = "block",
        message: str = "",
        review_status: str = "draft",
        reviewed_by: str = "",
        reviewed_at: str = "",
    ) -> MedicineIngredientConflictRule:
        self._ensure_seeded()
        left = self._normalize_ingredient(left_ingredient)
        right = self._normalize_ingredient(right_ingredient)
        if not left or not right or left == right:
            raise ValueError("成分冲突矩阵必须包含两种不同的有效成分。")
        left, right = sorted((left, right))
        normalized_status = review_status.strip().lower() or "draft"
        if normalized_status not in {"draft", "reviewed"}:
            raise ValueError("成分冲突审核状态只能是 draft 或 reviewed。")
        normalized_reviewer = reviewed_by.strip()
        normalized_reviewed_at = reviewed_at.strip()
        if normalized_status == "reviewed" and (
            not normalized_reviewer or not normalized_reviewed_at
        ):
            raise ValueError("已审核成分冲突必须填写审核人和审核时间。")
        normalized_disposition = disposition.strip().lower() or "block"
        if normalized_disposition != "block":
            raise ValueError("成分冲突处置目前只允许 block。")
        updated_at = db.now_text()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO medicine_ingredient_conflicts(
                  left_ingredient, right_ingredient, disposition, message,
                  review_status, reviewed_by, reviewed_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(left_ingredient, right_ingredient) DO UPDATE SET
                  disposition=excluded.disposition,
                  message=excluded.message,
                  review_status=excluded.review_status,
                  reviewed_by=excluded.reviewed_by,
                  reviewed_at=excluded.reviewed_at,
                  updated_at=excluded.updated_at
                """,
                (
                    left,
                    right,
                    normalized_disposition,
                    message.strip(),
                    normalized_status,
                    normalized_reviewer,
                    normalized_reviewed_at,
                    updated_at,
                ),
            )
        return MedicineIngredientConflictRule(
            left_ingredient=left,
            right_ingredient=right,
            disposition=normalized_disposition,
            message=message.strip(),
            review_status=normalized_status,
            reviewed_by=normalized_reviewer,
            reviewed_at=normalized_reviewed_at,
            updated_at=updated_at,
        )

    def list_reviewed_ingredient_conflicts(self) -> list[MedicineIngredientConflictRule]:
        self._ensure_seeded()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT left_ingredient, right_ingredient, disposition, message,
                       review_status, reviewed_by, reviewed_at, updated_at
                FROM medicine_ingredient_conflicts
                WHERE review_status='reviewed'
                  AND disposition='block'
                  AND TRIM(reviewed_by) <> ''
                  AND TRIM(reviewed_at) <> ''
                ORDER BY left_ingredient, right_ingredient
                """
            ).fetchall()
        return [
            MedicineIngredientConflictRule(
                left_ingredient=row["left_ingredient"],
                right_ingredient=row["right_ingredient"],
                disposition=row["disposition"],
                message=row["message"],
                review_status=row["review_status"],
                reviewed_by=row["reviewed_by"],
                reviewed_at=row["reviewed_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    @staticmethod
    def _normalize_ingredient(value: object) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())

    def list_all(self) -> list[Medicine]:
        self._ensure_seeded()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, slot, hardware_slot, barcode, name, category, spec, trace_code,
                       low_stock_line, tags_json, aliases_json, active_ingredients_json,
                       structured_contraindications_json,
                       indications, dosage, contraindications_json, stock, unit, expire_date,
                       image_hint, manufacturer, is_otc, is_emergency, safety_note,
                       guidance_source, guidance_review_required, package_verified, guidance_updated_at,
                       safety_review_status, safety_reviewed_by, safety_reviewed_at,
                       inventory_state, inventory_confirmed_at, last_inventory_request_id,
                       last_inventory_dispense_record_id
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
                SELECT id, slot, hardware_slot, barcode, name, category, spec, trace_code,
                       low_stock_line, tags_json, aliases_json, active_ingredients_json,
                       structured_contraindications_json,
                       indications, dosage, contraindications_json, stock, unit, expire_date,
                       image_hint, manufacturer, is_otc, is_emergency, safety_note,
                       guidance_source, guidance_review_required, package_verified, guidance_updated_at,
                       safety_review_status, safety_reviewed_by, safety_reviewed_at,
                       inventory_state, inventory_confirmed_at, last_inventory_request_id,
                       last_inventory_dispense_record_id
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
                SELECT id, slot, hardware_slot, barcode, name, category, spec, trace_code,
                       low_stock_line, tags_json, aliases_json, active_ingredients_json,
                       structured_contraindications_json,
                       indications, dosage, contraindications_json, stock, unit, expire_date,
                       image_hint, manufacturer, is_otc, is_emergency, safety_note,
                       guidance_source, guidance_review_required, package_verified, guidance_updated_at,
                       safety_review_status, safety_reviewed_by, safety_reviewed_at,
                       inventory_state, inventory_confirmed_at, last_inventory_request_id,
                       last_inventory_dispense_record_id
                FROM medicines
                WHERE barcode=?
                """,
                (barcode,),
            ).fetchone()
        return self._row_to_medicine(row) if row else None

    def get_by_hardware_slot(self, hardware_slot: int) -> Medicine | None:
        self._ensure_seeded()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, slot, hardware_slot, barcode, name, category, spec, trace_code,
                       low_stock_line, tags_json, aliases_json, active_ingredients_json,
                       structured_contraindications_json,
                       indications, dosage, contraindications_json, stock, unit, expire_date,
                       image_hint, manufacturer, is_otc, is_emergency, safety_note,
                       guidance_source, guidance_review_required, package_verified, guidance_updated_at,
                       safety_review_status, safety_reviewed_by, safety_reviewed_at,
                       inventory_state, inventory_confirmed_at, last_inventory_request_id,
                       last_inventory_dispense_record_id
                FROM medicines
                WHERE hardware_slot=?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (hardware_slot,),
            ).fetchone()
        return self._row_to_medicine(row) if row else None

    def update(self, medicine_id: str, updates: dict[str, object]) -> Medicine | None:
        self._ensure_seeded()
        medicine = self.get_by_id(medicine_id)
        if medicine is None:
            return None

        next_values = {
            "barcode": medicine.barcode,
            "manufacturer": medicine.manufacturer,
            "name": medicine.name,
            "category": medicine.category,
            "spec": medicine.spec,
            "trace_code": medicine.trace_code,
            "tags": medicine.tags,
            "aliases": medicine.aliases,
            "active_ingredients": medicine.active_ingredients,
            "indications": medicine.indications,
            "dosage": medicine.dosage,
            "contraindications": medicine.contraindications,
            "structured_contraindications": medicine.structured_contraindications,
            "stock": medicine.stock,
            "low_stock_line": medicine.low_stock_line,
            "unit": medicine.unit,
            "expire_date": medicine.expire_date,
            "is_otc": medicine.is_otc,
            "is_emergency": medicine.is_emergency,
            "safety_note": medicine.safety_note,
            "image_hint": medicine.image_hint,
            "guidance_source": medicine.guidance_source,
            "guidance_review_required": medicine.guidance_review_required,
            "package_verified": medicine.package_verified,
            "guidance_updated_at": medicine.guidance_updated_at,
            "safety_review_status": medicine.safety_review_status,
            "safety_reviewed_by": medicine.safety_reviewed_by,
            "safety_reviewed_at": medicine.safety_reviewed_at,
            "inventory_state": medicine.inventory_state,
            "inventory_confirmed_at": medicine.inventory_confirmed_at,
            "last_inventory_request_id": medicine.last_inventory_request_id,
            "last_inventory_dispense_record_id": medicine.last_inventory_dispense_record_id,
        }
        stock_explicitly_updated = False
        for key, value in updates.items():
            if value is None or key not in next_values:
                continue
            if key in {"name", "category", "unit"}:
                text = str(value).strip()
                if text:
                    next_values[key] = text
                continue
            if key in {
                "barcode",
                "manufacturer",
                "spec",
                "trace_code",
                "expire_date",
                "safety_note",
                "indications",
                "dosage",
                "guidance_source",
                "guidance_updated_at",
                "safety_review_status",
                "safety_reviewed_by",
                "safety_reviewed_at",
            }:
                next_values[key] = str(value).strip()
                continue
            if key in {"tags", "aliases", "active_ingredients", "contraindications"} and isinstance(value, list):
                next_values[key] = [str(item).strip() for item in value if str(item).strip()]
                continue
            if key == "structured_contraindications" and isinstance(value, list):
                next_values[key] = [
                    {
                        "concept_code": str(item.get("concept_code") or "").strip(),
                        "display_text": str(item.get("display_text") or "").strip(),
                    }
                    for item in value
                    if isinstance(item, dict)
                    and str(item.get("concept_code") or "").strip()
                    and str(item.get("display_text") or "").strip()
                ]
                continue
            if key == "stock":
                requested_stock = max(int(value), 0)
                next_values[key] = (
                    1
                    if medicine_id in BUNDLED_LABEL_SAFETY_IDS and requested_stock > 0
                    else requested_stock
                )
                stock_explicitly_updated = True
                next_values["inventory_state"] = (
                    "AVAILABLE" if next_values[key] > 0 else "DEPLETED"
                )
                next_values["inventory_confirmed_at"] = db.now_text()
                next_values["last_inventory_request_id"] = ""
                next_values["last_inventory_dispense_record_id"] = ""
                continue
            if key == "low_stock_line":
                next_values[key] = max(int(value), 0)
                continue
            if key in {"is_otc", "is_emergency", "guidance_review_required", "package_verified"}:
                next_values[key] = bool(value)

        identity_changed = any(
            next_values[field] != getattr(medicine, field)
            for field in ("name", "manufacturer", "barcode", "category", "spec")
        )
        if identity_changed:
            next_values["inventory_state"] = (
                "AVAILABLE" if int(next_values["stock"]) > 0 else "DEPLETED"
            )
            next_values["inventory_confirmed_at"] = db.now_text()
            next_values["last_inventory_request_id"] = ""
            next_values["last_inventory_dispense_record_id"] = ""
        safety_content_changed = any(
            next_values[field] != getattr(medicine, field)
            for field in (
                "tags",
                "aliases",
                "active_ingredients",
                "indications",
                "dosage",
                "contraindications",
                "structured_contraindications",
                "is_otc",
                "is_emergency",
                "safety_note",
            )
        )
        explicitly_reviewed = (
            str(updates.get("safety_review_status") or "").strip().lower() == "reviewed"
            and bool(str(updates.get("safety_reviewed_by") or "").strip())
            and bool(str(updates.get("safety_reviewed_at") or "").strip())
        )
        if identity_changed:
            explicit_draft_facts = {
                field: next_values[field]
                for field in (
                    "aliases",
                    "active_ingredients",
                    "structured_contraindications",
                )
                if field in updates and isinstance(updates[field], list)
            }
            # Identity-bearing edits may describe a different product even when
            # they arrive as an ordinary slot patch. Never let the new package
            # inherit reviewed facts, label guidance, or OTC eligibility from
            # the previous medicine occupying that cabinet.
            next_values.update(
                tags=[],
                aliases=[],
                active_ingredients=[],
                indications="",
                dosage="",
                contraindications=[],
                structured_contraindications=[],
                is_otc=False,
                is_emergency=False,
                safety_note="药品身份已变化，说明与安全资料待人工核验。",
                guidance_source="pending",
                guidance_review_required=True,
                package_verified=False,
                guidance_updated_at="",
                safety_review_status="draft",
                safety_reviewed_by="",
                safety_reviewed_at="",
            )
            next_values.update(explicit_draft_facts)
        elif safety_content_changed and not explicitly_reviewed:
            # Editing reviewed safety or label content creates a new draft
            # revision. Public/admin/cloud update paths cannot silently carry
            # the prior pharmacist/label review onto changed facts.
            next_values.update(
                safety_review_status="draft",
                safety_reviewed_by="",
                safety_reviewed_at="",
            )

        next_values["image_hint"] = f"{next_values['manufacturer']} {next_values['name']}".strip() or medicine.image_hint
        combination_sensitive_changed = any(
            next_values[field] != getattr(medicine, field)
            for field in self.COMBINATION_SENSITIVE_FIELDS
        )
        with db.connect() as conn:
            if identity_changed:
                conn.execute("DELETE FROM today_plans WHERE medicine_id=?", (medicine_id,))
            if combination_sensitive_changed:
                self._invalidate_combinations_for_medicine(conn, medicine_id)
            conn.execute(
                """
                UPDATE medicines
                SET barcode=?, manufacturer=?, name=?, category=?, spec=?, trace_code=?, tags_json=?,
                    aliases_json=?, active_ingredients_json=?, indications=?, dosage=?,
                    contraindications_json=?, structured_contraindications_json=?, stock=?, unit=?, expire_date=?,
                    low_stock_line=?, image_hint=?, is_otc=?, is_emergency=?, safety_note=?, guidance_source=?,
                    guidance_review_required=?, package_verified=?, guidance_updated_at=?, safety_review_status=?,
                    safety_reviewed_by=?, safety_reviewed_at=?, updated_at=?
                    , inventory_state=?, inventory_confirmed_at=?, last_inventory_request_id=?,
                    last_inventory_dispense_record_id=?,
                    inventory_revision=inventory_revision+?
                WHERE id=?
                """,
                (
                    next_values["barcode"],
                    next_values["manufacturer"],
                    next_values["name"],
                    next_values["category"],
                    next_values["spec"],
                    next_values["trace_code"],
                    json.dumps(next_values["tags"], ensure_ascii=False),
                    json.dumps(next_values["aliases"], ensure_ascii=False),
                    json.dumps(next_values["active_ingredients"], ensure_ascii=False),
                    next_values["indications"],
                    next_values["dosage"],
                    json.dumps(next_values["contraindications"], ensure_ascii=False),
                    json.dumps(next_values["structured_contraindications"], ensure_ascii=False),
                    int(next_values["stock"]),
                    next_values["unit"],
                    next_values["expire_date"],
                    int(next_values["low_stock_line"]),
                    next_values["image_hint"],
                    1 if next_values["is_otc"] else 0,
                    1 if next_values["is_emergency"] else 0,
                    next_values["safety_note"],
                    next_values["guidance_source"],
                    1 if next_values["guidance_review_required"] else 0,
                    1 if next_values["package_verified"] else 0,
                    next_values["guidance_updated_at"],
                    next_values["safety_review_status"],
                    next_values["safety_reviewed_by"],
                    next_values["safety_reviewed_at"],
                    db.now_text(),
                    next_values["inventory_state"],
                    next_values["inventory_confirmed_at"],
                    next_values["last_inventory_request_id"],
                    next_values["last_inventory_dispense_record_id"],
                    1 if stock_explicitly_updated or identity_changed else 0,
                    medicine_id,
                ),
            )
        return self.get_by_id(medicine_id)

    @staticmethod
    def _invalidate_combinations_for_medicine(conn, medicine_id: str) -> None:
        rows = conn.execute(
            """
            SELECT combination_id, medicine_ids_json
            FROM approved_medicine_combinations
            WHERE review_status='reviewed'
            """
        ).fetchall()
        affected_ids: list[str] = []
        for row in rows:
            try:
                medicine_ids = json.loads(row["medicine_ids_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                medicine_ids = []
            if isinstance(medicine_ids, list) and medicine_id in medicine_ids:
                affected_ids.append(row["combination_id"])
        if not affected_ids:
            return
        conn.executemany(
            """
            UPDATE approved_medicine_combinations
            SET review_status='invalidated', reviewed_by='', reviewed_at='', updated_at=?
            WHERE combination_id=? AND review_status='reviewed'
            """,
            [(db.now_text(), combination_id) for combination_id in affected_ids],
        )

    def create_from_scan(
        self,
        *,
        barcode: str,
        manufacturer: str = "",
        name: str,
        spec: str = "",
        trace_code: str = "",
        expire_date: str = "",
        stock: int = 1,
        low_stock_line: int = 1,
        unit: str = "盒",
        category: str = "扫码录入",
        indications: str = "",
        dosage: str = "",
        hardware_slot: int | None = None,
        safety_note: str = "",
        deduplicate_barcode: bool = True,
    ) -> Medicine:
        self._ensure_seeded()
        normalized_barcode = barcode.strip()
        existing = self.get_by_barcode(normalized_barcode) if normalized_barcode and deduplicate_barcode else None
        if existing:
            return existing

        slot_number = hardware_slot if hardware_slot is not None else self.first_empty_hardware_slot()
        slot_label = f"S{slot_number:02d}"
        identity_name = f"{name}-{slot_label}" if not deduplicate_barcode else name
        identity_barcode = "" if not deduplicate_barcode else normalized_barcode
        medicine_id = self._scan_id(identity_name, identity_barcode)
        stock = max(int(stock if stock is not None else 1), 0)
        low_stock_line = max(int(low_stock_line if low_stock_line is not None else 1), 0)
        safety = safety_note or "扫码录入药品，开柜前请核对药盒、有效期和家庭用药记录。"
        inventory_state = "AVAILABLE" if stock > 0 else "DEPLETED"
        changed_at = db.now_text()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO medicines(
                  id, slot, hardware_slot, barcode, manufacturer, name, category, spec, trace_code, tags_json,
                  indications, dosage, contraindications_json, stock, low_stock_line, unit, expire_date, image_hint,
                  is_otc, is_emergency, safety_note, guidance_source,
                  guidance_review_required, package_verified, guidance_updated_at, updated_at,
                  inventory_state, inventory_confirmed_at, inventory_revision
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  slot=excluded.slot,
                  hardware_slot=excluded.hardware_slot,
                  barcode=excluded.barcode,
                  manufacturer=excluded.manufacturer,
                  name=excluded.name,
                  category=excluded.category,
                  spec=excluded.spec,
                  trace_code=excluded.trace_code,
                  indications=excluded.indications,
                  dosage=excluded.dosage,
                  stock=excluded.stock,
                  low_stock_line=excluded.low_stock_line,
                  unit=excluded.unit,
                  expire_date=excluded.expire_date,
                  image_hint=excluded.image_hint,
                  safety_note=excluded.safety_note,
                  guidance_source=excluded.guidance_source,
                  guidance_review_required=excluded.guidance_review_required,
                  package_verified=excluded.package_verified,
                  guidance_updated_at=excluded.guidance_updated_at,
                  inventory_state=excluded.inventory_state,
                  inventory_confirmed_at=excluded.inventory_confirmed_at,
                  last_inventory_request_id='',
                  last_inventory_dispense_record_id='',
                  inventory_revision=medicines.inventory_revision+1,
                  updated_at=excluded.updated_at
                """,
                (
                    medicine_id,
                    slot_label,
                    slot_number,
                    normalized_barcode,
                    manufacturer.strip(),
                    name.strip() or "待核验药品",
                    category.strip() or "扫码录入",
                    spec.strip(),
                    trace_code.strip(),
                    json.dumps(["扫码录入", "待核验"], ensure_ascii=False),
                    indications.strip(),
                    dosage.strip(),
                    json.dumps(["请人工核对药品说明"], ensure_ascii=False),
                    stock,
                    low_stock_line,
                    unit.strip() or "盒",
                    expire_date.strip(),
                    f"{manufacturer.strip()} {name.strip()}".strip() or "扫码录入药品",
                    1,
                    0,
                    safety,
                    "pending",
                    1,
                    0,
                    changed_at,
                    changed_at,
                    inventory_state,
                    changed_at,
                    0,
                ),
            )
        created = self.get_by_id(medicine_id)
        if created is None:
            raise RuntimeError("扫码药品录入失败。")
        return created

    def create_at_hardware_slot(
        self,
        *,
        hardware_slot: int,
        barcode: str,
        manufacturer: str = "",
        name: str,
        spec: str = "",
        trace_code: str = "",
        expire_date: str = "",
        stock: int = 1,
        low_stock_line: int = 1,
        unit: str = "盒",
        category: str = "家庭常用",
        safety_note: str = "",
    ) -> Medicine:
        if self.get_by_hardware_slot(hardware_slot) is not None:
            raise ValueError(f"{hardware_slot} 号仓已有药品。")
        return self.create_from_scan(
            barcode=barcode,
            manufacturer=manufacturer,
            name=name,
            spec=spec,
            trace_code=trace_code,
            expire_date=expire_date,
            stock=stock,
            low_stock_line=low_stock_line,
            unit=unit,
            category=category,
            hardware_slot=hardware_slot,
            safety_note=safety_note,
            deduplicate_barcode=False,
        )

    def first_empty_hardware_slot(self) -> int:
        self._ensure_seeded()
        with db.connect() as conn:
            rows = conn.execute("SELECT hardware_slot FROM medicines WHERE stock > 0").fetchall()
        used = {int(row["hardware_slot"]) for row in rows}
        for slot in range(1, 24):
            if slot not in used:
                return slot
        return 23

    def get_inventory_observation_token(
        self,
        medicine_id: str,
    ) -> InventoryObservationToken | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                "SELECT stock, inventory_revision FROM medicines WHERE id=?",
                (str(medicine_id or "").strip(),),
            ).fetchone()
        if row is None:
            return None
        return InventoryObservationToken(
            stock=int(row["stock"]),
            revision=int(row["inventory_revision"]),
        )

    def inventory_confirmation_required(self, dispense_record_id: str) -> bool:
        normalized_record_id = str(dispense_record_id or "").strip()
        if not normalized_record_id:
            return False
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM medicines
                WHERE last_inventory_dispense_record_id=?
                  AND COALESCE(last_inventory_request_id, '')=''
                LIMIT 1
                """,
                (normalized_record_id,),
            ).fetchone()
        return row is not None

    def mark_inventory_observation_pending(
        self,
        medicine_id: str,
        dispense_record_id: str,
        *,
        expected_stock: int,
        expected_inventory_revision: int,
    ) -> bool:
        """Bind a successful dispense to its optional depleted observation.

        Stock is an availability flag for the station's fixed cabinet catalog. A
        successful cabinet action therefore keeps the normal truth at one and
        AVAILABLE; only an explicit DEPLETED observation may clear it.
        """
        normalized_medicine_id = str(medicine_id or "").strip()
        normalized_record_id = str(dispense_record_id or "").strip()
        normalized_stock = int(expected_stock)
        normalized_revision = int(expected_inventory_revision)
        if (
            not normalized_medicine_id
            or not normalized_record_id
            or normalized_stock < 0
            or normalized_revision < 0
        ):
            return False
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._mark_inventory_observation_pending_in_connection(
                conn,
                normalized_medicine_id,
                normalized_record_id,
                expected_stock=normalized_stock,
                expected_inventory_revision=normalized_revision,
            )

    @staticmethod
    def _mark_inventory_observation_pending_in_connection(
        conn,
        medicine_id: str,
        dispense_record_id: str,
        *,
        expected_stock: int,
        expected_inventory_revision: int,
    ) -> bool:
        cursor = conn.execute(
            """
            UPDATE medicines
            SET stock=1, inventory_state='AVAILABLE', inventory_confirmed_at='',
                last_inventory_request_id='', last_inventory_dispense_record_id=?,
                updated_at=?
            WHERE id=? AND stock=? AND inventory_revision=?
              AND ? = (
                SELECT id FROM dispense_records
                WHERE medicine_id=? AND dry_run=0 AND qsm_ok=1
                ORDER BY created_at DESC, rowid DESC LIMIT 1
              )
            """,
            (
                dispense_record_id,
                db.now_text(),
                medicine_id,
                int(expected_stock),
                int(expected_inventory_revision),
                dispense_record_id,
                medicine_id,
            ),
        )
        return cursor.rowcount == 1

    def _ensure_seeded(self) -> None:
        db.init_db()
        with db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM medicines").fetchone()["count"]
            if count:
                self._sync_default_inventory(conn)
                self._sync_default_guidance(conn)
                self._sync_default_package_verification(conn)
                self._sync_default_safety_facts(conn)
                self._sync_default_combinations(conn)
                return
            self._insert_default_inventory(conn)
            self._sync_default_safety_facts(conn)
            self._sync_default_combinations(conn)

    @staticmethod
    def _sync_default_inventory(conn) -> None:
        row = conn.execute("SELECT value FROM app_settings WHERE key='medicine_seed_version'").fetchone()
        if row and row["value"] == MEDICINE_SEED_VERSION:
            return
        replacements = (
            (
                {
                    "id": "slot-03-ganmao-qingre", "slot": "S03", "hardware_slot": 3,
                    "name": "感冒清热颗粒", "barcode": "6928849913616", "manufacturer": "999",
                    "category": "感冒发热", "tags_json": ["风寒感冒", "头痛发热"],
                    "indications": "疏风散寒，解表清热。用于风寒感冒，头痛发热，恶寒身痛，鼻流清涕，咳嗽咽干。",
                    "dosage": "开水冲服，一次1袋（12克），一日2次。",
                    "contraindications_json": ["对本品成分过敏禁用", "风热感冒表现者不适用"],
                    "stock": 1, "unit": "盒", "expire_date": "2027-11",
                    "image_hint": "999 感冒清热颗粒", "is_otc": 1, "is_emergency": 0,
                    "safety_note": "用于风寒感冒相关症状，症状不匹配或持续加重需联系医生。",
                },
                (
                    {"id": "slot-03-diosmectite", "name": "蒙脱石散", "barcode": "", "manufacturer": "待补录", "expire_date": "待补录"},
                    {"id": "slot-03-diosmectite", "name": "蒙脱石散", "barcode": "6932833600109", "manufacturer": "迈优力制药", "expire_date": "2030-02"},
                ),
            ),
            (
                {
                    "id": "slot-13-sodium-hyaluronate-eye", "slot": "S13", "hardware_slot": 13,
                    "name": "玻璃酸钠滴眼液", "barcode": "6955236613620", "manufacturer": "普润盈",
                    "category": "眼部护理", "tags_json": ["干眼", "眼部润滑"],
                    "indications": "用于伴随干燥综合征、斯约二氏综合征等内因性疾患，或手术、药物、外伤、佩戴隐形眼镜等外因性疾患所致的角结膜上皮损伤。",
                    "dosage": "滴眼，一次1滴，一日3次；可根据症状适当增减。",
                    "contraindications_json": ["对成分过敏禁用", "瓶口勿接触眼部或皮肤"],
                    "stock": 1, "unit": "盒", "expire_date": "2026-08-10",
                    "image_hint": "普润盈玻璃酸钠滴眼液", "is_otc": 1, "is_emergency": 0,
                    "safety_note": "眼部疼痛、红肿或视力变化时不要自行处理。",
                },
                (
                    {"id": "slot-13-ibuprofen", "name": "布洛芬", "barcode": "", "manufacturer": "待补录", "expire_date": "待补录"},
                    {"id": "slot-13-ibuprofen", "name": "布洛芬缓释胶囊", "barcode": "6913991301572", "manufacturer": "芬必得", "expire_date": "2029-01"},
                ),
            ),
        )
        defaults = {item["id"]: item for item in DEFAULT_MEDICINES}
        for old_default, replacement_defaults in replacements:
            replacement_id = replacement_defaults[0]["id"]
            old_row = conn.execute("SELECT * FROM medicines WHERE id=?", (old_default["id"],)).fetchone()
            new_row = conn.execute("SELECT * FROM medicines WHERE id=?", (replacement_id,)).fetchone()
            item = defaults[replacement_id]
            if old_row and MedicineRepository._row_matches(old_row, old_default):
                # A plan for the old product must never silently become a plan for a
                # different medicine. Stop those plans and require a fresh review.
                conn.execute("DELETE FROM today_plans WHERE medicine_id=?", (old_default["id"],))
                conn.execute("DELETE FROM medicines WHERE id=?", (old_default["id"],))
                if not new_row:
                    MedicineRepository._upsert_replacement(conn, item, preserve_stock=False)
            elif new_row and any(
                MedicineRepository._row_matches(new_row, expected)
                for expected in replacement_defaults
            ):
                MedicineRepository._migrate_verified_replacement_identity(
                    conn,
                    new_row,
                    item,
                )
        MedicineRepository._write_seed_version(conn, "medicine_seed_version", MEDICINE_SEED_VERSION)

    @staticmethod
    def _row_matches(row: object, expected: dict[str, object]) -> bool:
        for key, value in expected.items():
            actual = row[key]
            if key in {"tags_json", "contraindications_json"}:
                actual = json.loads(actual or "[]")
            if actual != value:
                return False
        return True

    @staticmethod
    def _upsert_replacement(conn, item: dict[str, object], *, preserve_stock: bool) -> None:
        conn.execute(
            """
            INSERT INTO medicines(
              id, slot, hardware_slot, barcode, manufacturer, name, category, tags_json,
              indications, dosage, contraindications_json, stock, unit, expire_date, image_hint,
              is_otc, is_emergency, safety_note, guidance_source,
              guidance_review_required, package_verified, guidance_updated_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              slot=excluded.slot,
              hardware_slot=excluded.hardware_slot,
              barcode=excluded.barcode,
              manufacturer=excluded.manufacturer,
              name=excluded.name,
              category=excluded.category,
              tags_json=excluded.tags_json,
              indications=excluded.indications,
              dosage=excluded.dosage,
              contraindications_json=excluded.contraindications_json,
              stock=CASE WHEN ? THEN medicines.stock ELSE excluded.stock END,
              unit=excluded.unit,
              expire_date=excluded.expire_date,
              image_hint=excluded.image_hint,
              is_otc=excluded.is_otc,
              is_emergency=excluded.is_emergency,
              safety_note=excluded.safety_note,
              guidance_source=excluded.guidance_source,
              guidance_review_required=excluded.guidance_review_required,
              package_verified=excluded.package_verified,
              guidance_updated_at=excluded.guidance_updated_at,
              updated_at=excluded.updated_at
            """,
            (
                item["id"],
                item["slot"],
                int(item["hardware_slot"]),
                item["barcode"],
                item.get("manufacturer", ""),
                item["name"],
                item["category"],
                json.dumps(item["tags"], ensure_ascii=False),
                item["indications"],
                item["dosage"],
                json.dumps(item["contraindications"], ensure_ascii=False),
                int(item["stock"]),
                item["unit"],
                item["expire_date"],
                item["image_hint"],
                1 if item["is_otc"] else 0,
                1 if item["is_emergency"] else 0,
                item["safety_note"],
                item["guidance_source"],
                1 if item["guidance_review_required"] else 0,
                1 if item["package_verified"] else 0,
                db.now_text(),
                db.now_text(),
                1 if preserve_stock else 0,
            ),
        )

    @staticmethod
    def _migrate_verified_replacement_identity(
        conn,
        row: object,
        item: dict[str, object],
    ) -> None:
        """Correct a known barcode identity without overwriting edited label facts."""
        medicine_id = str(item["id"])
        MedicineRepository._invalidate_combinations_for_medicine(conn, medicine_id)
        conn.execute("DELETE FROM today_plans WHERE medicine_id=?", (medicine_id,))
        conn.execute(
            """
            UPDATE medicines
            SET slot=?, hardware_slot=?, barcode=?, manufacturer=?, name=?, category=?,
                spec=?, expire_date=?, image_hint=?, unit=?, package_verified=1,
                safety_review_status='draft', safety_reviewed_by='',
                safety_reviewed_at='', updated_at=?
            WHERE id=?
            """,
            (
                item["slot"],
                int(item["hardware_slot"]),
                item["barcode"],
                item.get("manufacturer", ""),
                item["name"],
                item["category"],
                item.get("spec", ""),
                item["expire_date"],
                item["image_hint"],
                item["unit"],
                db.now_text(),
                medicine_id,
            ),
        )

    @staticmethod
    def _write_seed_version(conn, key: str, value: str) -> None:
        conn.execute(
            """
            INSERT INTO app_settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, db.now_text()),
        )

    @staticmethod
    def _insert_default_inventory(conn) -> None:
        conn.executemany(
            """
            INSERT INTO medicines(
              id, slot, hardware_slot, barcode, manufacturer, name, category, tags_json,
              indications, dosage, contraindications_json, stock, unit, expire_date, image_hint,
              is_otc, is_emergency, safety_note, guidance_source,
              guidance_review_required, package_verified, guidance_updated_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    item["indications"],
                    item["dosage"],
                    json.dumps(item["contraindications"], ensure_ascii=False),
                    int(item["stock"]),
                    item["unit"],
                    item["expire_date"],
                    item["image_hint"],
                    1 if item["is_otc"] else 0,
                    1 if item["is_emergency"] else 0,
                    item["safety_note"],
                    item["guidance_source"],
                    1 if item["guidance_review_required"] else 0,
                    1 if item["package_verified"] else 0,
                    db.now_text(),
                    db.now_text(),
                )
                for item in DEFAULT_MEDICINES
            ],
        )
        MedicineRepository._write_seed_version(conn, "medicine_seed_version", MEDICINE_SEED_VERSION)
        MedicineRepository._write_seed_version(conn, "medicine_guidance_version", MEDICINE_GUIDANCE_VERSION)
        MedicineRepository._write_seed_version(conn, "package_verification_version", PACKAGE_VERIFICATION_VERSION)

    @staticmethod
    def _sync_default_package_verification(conn) -> None:
        version = conn.execute(
            "SELECT value FROM app_settings WHERE key='package_verification_version'"
        ).fetchone()
        if version and version["value"] == PACKAGE_VERIFICATION_VERSION:
            return
        for item in DEFAULT_MEDICINES:
            conn.execute(
                """
                UPDATE medicines SET package_verified=1
                WHERE id=? AND name=? AND barcode=? AND manufacturer=? AND spec=?
                """,
                (
                    item["id"],
                    item["name"],
                    item["barcode"],
                    item.get("manufacturer", ""),
                    item.get("spec", ""),
                ),
            )
        MedicineRepository._write_seed_version(
            conn,
            "package_verification_version",
            PACKAGE_VERIFICATION_VERSION,
        )

    @staticmethod
    def _sync_default_safety_facts(conn) -> None:
        version = conn.execute(
            "SELECT value FROM app_settings WHERE key='medicine_safety_facts_version'"
        ).fetchone()
        if version and version["value"] == MEDICINE_SAFETY_FACTS_VERSION:
            return
        reviewed_at = db.now_text()
        for item in DEFAULT_MEDICINES:
            facts = DEFAULT_MEDICINE_SAFETY_FACTS.get(str(item["id"]), {})
            row = conn.execute(
                """
                SELECT id, name, barcode, manufacturer, spec, category, tags_json,
                       indications, dosage, contraindications_json, is_otc,
                       is_emergency, safety_note, guidance_source,
                       aliases_json, active_ingredients_json,
                       structured_contraindications_json, safety_review_status,
                       safety_reviewed_by, safety_reviewed_at
                FROM medicines
                WHERE id=?
                """,
                (item["id"],),
            ).fetchone()
            if row is None:
                continue
            reviewer = str(row["safety_reviewed_by"] or "").strip()
            reviewed_status = str(row["safety_review_status"] or "") == "reviewed"
            legacy_machine_review = reviewed_status and reviewer == "fixed-inventory-safety-migration"
            existing_bundled_review = (
                reviewed_status and reviewer in BUNDLED_LABEL_SAFETY_REVIEWERS
            )
            controlled_local_review = (
                reviewed_status
                and bool(reviewer)
                and bool(str(row["safety_reviewed_at"] or "").strip())
                and not legacy_machine_review
                and not existing_bundled_review
            )
            if controlled_local_review:
                continue

            try:
                current_tags = json.loads(row["tags_json"] or "[]")
                current_contraindications = json.loads(row["contraindications_json"] or "[]")
                current_aliases = json.loads(row["aliases_json"] or "[]")
                current_ingredients = json.loads(row["active_ingredients_json"] or "[]")
                current_structured = json.loads(row["structured_contraindications_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                current_tags = current_contraindications = None
                current_aliases = current_ingredients = current_structured = None

            identity_matches = not any(
                str(row[field] or "") != str(item.get(field, "") or "")
                for field in ("name", "barcode", "manufacturer", "spec", "category")
            )
            current_safety_note = str(row["safety_note"] or "")
            legacy_label = LEGACY_V4_MEDICINE_LABEL_SAFETY.get(str(item["id"]))
            legacy_contraindications = list(
                (legacy_label or {}).get("contraindications", ())
            )
            legacy_structured = MedicineRepository._default_structured_contraindications(
                legacy_contraindications
            )
            legacy_label_warning_structured = [
                {
                    "concept_code": "label_warning",
                    "display_text": "非甾体抗炎药过敏者禁用",
                },
                *legacy_structured[1:],
            ]
            known_legacy_ibuprofen_structured_snapshots = (
                legacy_structured,
                legacy_label_warning_structured,
            )
            legacy_label_content_matches = bool(
                legacy_label
                and identity_matches
                and current_tags == list(item.get("tags", []))
                and str(row["indications"] or "") == str(item.get("indications", "") or "")
                and str(row["dosage"] or "") == str(item.get("dosage", "") or "")
                and current_contraindications == legacy_contraindications
                and current_structured in ([], legacy_structured)
                and bool(row["is_otc"]) == bool(item.get("is_otc"))
                and bool(row["is_emergency"]) == bool(item.get("is_emergency"))
                and current_safety_note == str(legacy_label.get("safety_note") or "")
                and str(row["guidance_source"] or "")
                == str(item.get("guidance_source", "") or "")
            )
            # A deployed v5 database could already carry the v5 marker and
            # reviewer while S13 still retained the exact three-warning v4
            # contraindication baseline.  Match only that controlled snapshot;
            # local reviews and edited contraindications remain untouched.
            v5_marker_with_legacy_ibuprofen_facts = bool(
                str(item["id"]) == "slot-13-ibuprofen"
                and reviewed_status
                and reviewer == "bundled-cabinet-reference-v5"
                and identity_matches
                and current_contraindications == legacy_contraindications
                and current_structured
                in known_legacy_ibuprofen_structured_snapshots
            )
            controlled_legacy_label_content_matches = (
                legacy_label_content_matches
                or v5_marker_with_legacy_ibuprofen_facts
            )
            if controlled_legacy_label_content_matches:
                current_contraindications = list(item.get("contraindications", []))
                current_safety_note = str(item.get("safety_note", "") or "")
                conn.execute(
                    """
                    UPDATE medicines
                    SET contraindications_json=?, safety_note=?,
                        guidance_updated_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        json.dumps(current_contraindications, ensure_ascii=False),
                        current_safety_note,
                        reviewed_at,
                        reviewed_at,
                        item["id"],
                    ),
                )
            label_content_matches = (
                identity_matches
                and current_tags == list(item.get("tags", []))
                and str(row["indications"] or "") == str(item.get("indications", "") or "")
                and str(row["dosage"] or "") == str(item.get("dosage", "") or "")
                and current_contraindications == list(item.get("contraindications", []))
                and bool(row["is_otc"]) == bool(item.get("is_otc"))
                and bool(row["is_emergency"]) == bool(item.get("is_emergency"))
                and current_safety_note == str(item.get("safety_note", "") or "")
                and str(row["guidance_source"] or "")
                == str(item.get("guidance_source", "") or "")
            )
            aliases = list(
                dict.fromkeys(
                    value.strip()
                    for value in (str(item["name"]), *facts.get("aliases", ()))
                    if value and value.strip()
                )
            )
            ingredients = list(facts.get("active_ingredients", ()))
            structured = MedicineRepository._default_structured_contraindications(
                list(item.get("contraindications", []))
            )
            facts_are_empty = (
                current_aliases == []
                and current_ingredients == []
                and current_structured == []
            )
            facts_match_bundled_baseline = (
                current_aliases == aliases
                and current_ingredients == ingredients
                and current_structured == structured
            )
            facts_match_v5_structured_baseline = (
                existing_bundled_review
                and reviewer == "bundled-cabinet-reference-v5"
                and current_aliases == aliases
                and current_ingredients == ingredients
                and current_structured
                == LEGACY_V5_STRUCTURED_SAFETY_FACTS.get(str(item["id"]))
            )
            legacy_facts = LEGACY_V4_MEDICINE_SAFETY_FACTS.get(
                str(item["id"]),
                LEGACY_V3_MEDICINE_SAFETY_FACTS.get(str(item["id"]), {}),
            )
            legacy_aliases = list(
                dict.fromkeys(
                    value.strip()
                    for value in (str(item["name"]), *legacy_facts.get("aliases", ()))
                    if value and value.strip()
                )
            )
            facts_match_legacy_baseline = (
                current_aliases == legacy_aliases
                and current_ingredients
                == list(legacy_facts.get("active_ingredients", ()))
                and (
                    current_structured == structured
                    or (
                        controlled_legacy_label_content_matches
                        and current_structured
                        in ([], *known_legacy_ibuprofen_structured_snapshots)
                    )
                )
                or facts_match_v5_structured_baseline
            )
            facts_can_migrate = (
                facts_are_empty
                or facts_match_bundled_baseline
                or facts_match_legacy_baseline
            )
            bundled_baseline_eligible = (
                str(item["id"]) in BUNDLED_LABEL_SAFETY_IDS
                and label_content_matches
                and facts_can_migrate
            )

            next_status = "reviewed" if bundled_baseline_eligible else "draft"
            preserve_existing_bundled_review = (
                bundled_baseline_eligible
                and existing_bundled_review
                and facts_match_bundled_baseline
                and not controlled_legacy_label_content_matches
                and not facts_match_v5_structured_baseline
            )
            next_reviewer = (
                reviewer
                if preserve_existing_bundled_review
                else BUNDLED_LABEL_SAFETY_REVIEWER
                if bundled_baseline_eligible
                else ""
            )
            next_reviewed_at = (
                str(row["safety_reviewed_at"] or "")
                if preserve_existing_bundled_review
                else reviewed_at
                if bundled_baseline_eligible
                else ""
            )
            status_changed = (
                str(row["safety_review_status"] or "") != next_status
                or reviewer != next_reviewer
                or str(row["safety_reviewed_at"] or "") != next_reviewed_at
            )
            if status_changed or facts_are_empty:
                MedicineRepository._invalidate_combinations_for_medicine(
                    conn,
                    str(item["id"]),
                )
            if bundled_baseline_eligible and not facts_match_bundled_baseline:
                conn.execute(
                    """
                    UPDATE medicines
                    SET aliases_json=?, active_ingredients_json=?,
                        structured_contraindications_json=?
                    WHERE id=?
                    """,
                    (
                        json.dumps(aliases, ensure_ascii=False),
                        json.dumps(ingredients, ensure_ascii=False),
                        json.dumps(structured, ensure_ascii=False),
                        item["id"],
                    ),
                )
            if status_changed:
                conn.execute(
                    """
                    UPDATE medicines
                    SET safety_review_status=?, safety_reviewed_by=?, safety_reviewed_at=?
                    WHERE id=?
                    """,
                    (next_status, next_reviewer, next_reviewed_at, item["id"]),
                )
        MedicineRepository._write_seed_version(
            conn,
            "medicine_safety_facts_version",
            MEDICINE_SAFETY_FACTS_VERSION,
        )

    @staticmethod
    def _sync_default_combinations(conn) -> None:
        version = conn.execute(
            "SELECT value FROM app_settings WHERE key='medicine_combination_policy_version'"
        ).fetchone()
        if version and version["value"] == MEDICINE_COMBINATION_POLICY_VERSION:
            return

        reviewed_at = db.now_text()
        for definition in DEFAULT_MEDICINE_COMBINATIONS:
            combination_id = str(definition["combination_id"])
            existing = conn.execute(
                """
                SELECT provenance, review_status, reviewed_by
                FROM approved_medicine_combinations
                WHERE combination_id=?
                """,
                (combination_id,),
            ).fetchone()
            if (
                existing is not None
                and str(existing["review_status"] or "").strip().lower() == "invalidated"
            ):
                # An inventory or safety change permanently revokes the previous
                # snapshot. A later bundled-policy migration must not silently
                # turn that revoked evidence back into an active cabinet plan.
                continue
            if existing is not None and (
                str(existing["provenance"] or "")
                not in {
                    "official-health-guidance-candidate-v1",
                    MEDICINE_COMBINATION_POLICY_PROVENANCE,
                }
                or str(existing["reviewed_by"] or "")
                not in {"", MEDICINE_COMBINATION_POLICY_REVIEWER}
            ):
                continue

            medicine_ids = [str(value) for value in definition["medicine_ids"]]
            placeholders = ",".join("?" for _ in medicine_ids)
            rows = conn.execute(
                f"SELECT * FROM medicines WHERE id IN ({placeholders})",
                tuple(medicine_ids),
            ).fetchall()
            by_id = {
                str(row["id"]): MedicineRepository._row_to_medicine(row)
                for row in rows
            }
            if set(by_id) != set(medicine_ids):
                continue
            members = [by_id[medicine_id] for medicine_id in medicine_ids]
            if any(
                member.safety_review_status != "reviewed"
                or not member.safety_reviewed_by.strip()
                or not member.safety_reviewed_at.strip()
                or not member.package_verified
                or (
                    not member.active_ingredients
                    and not MedicineRepository._is_controlled_non_drug_supply(member)
                )
                for member in members
            ):
                continue

            applicability = MedicineRepository._normalize_combination_applicability(
                definition.get("applicability")
            )
            usages = {
                str(medicine_id): str(usage)
                for medicine_id, usage in dict(
                    definition.get("reviewed_usage_by_medicine") or {}
                ).items()
            }
            evidence = [
                MedicineCombinationEvidenceRef.model_validate(item)
                for item in definition.get("evidence_refs", ())
            ]
            review_note = str(definition.get("review_note") or "").strip()
            MedicineRepository._validate_case_review_contract(
                medicine_ids=medicine_ids,
                clinical_policy_version=MEDICINE_COMBINATION_CLINICAL_POLICY_VERSION,
                applicability=applicability,
                reviewed_usage_by_medicine=usages,
                evidence_refs=evidence,
                provenance=MEDICINE_COMBINATION_POLICY_PROVENANCE,
                review_note=review_note,
            )
            identity_fingerprints = {
                member.id: MedicineRepository._identity_fingerprint(
                    name=member.name,
                    manufacturer=member.manufacturer,
                    barcode=member.barcode,
                    spec=member.spec,
                    category=member.category,
                )
                for member in members
            }
            review_fingerprints = {
                member.id: MedicineRepository.review_fingerprint(member)
                for member in members
            }
            conn.execute(
                """
                INSERT INTO approved_medicine_combinations(
                  combination_id, label, medicine_ids_json,
                  member_identity_fingerprints_json, clinical_policy_version,
                  applicability_json, member_review_fingerprints_json,
                  reviewed_usage_json, evidence_refs_json, provenance, review_note,
                  review_status, reviewed_by, reviewed_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewed', ?, ?, ?)
                ON CONFLICT(combination_id) DO UPDATE SET
                  label=excluded.label,
                  medicine_ids_json=excluded.medicine_ids_json,
                  member_identity_fingerprints_json=excluded.member_identity_fingerprints_json,
                  clinical_policy_version=excluded.clinical_policy_version,
                  applicability_json=excluded.applicability_json,
                  member_review_fingerprints_json=excluded.member_review_fingerprints_json,
                  reviewed_usage_json=excluded.reviewed_usage_json,
                  evidence_refs_json=excluded.evidence_refs_json,
                  provenance=excluded.provenance,
                  review_note=excluded.review_note,
                  review_status='reviewed',
                  reviewed_by=excluded.reviewed_by,
                  reviewed_at=excluded.reviewed_at,
                  updated_at=excluded.updated_at
                """,
                (
                    combination_id,
                    str(definition["label"]),
                    json.dumps(medicine_ids, ensure_ascii=False),
                    json.dumps(identity_fingerprints, ensure_ascii=False, sort_keys=True),
                    MEDICINE_COMBINATION_CLINICAL_POLICY_VERSION,
                    json.dumps(applicability.model_dump(), ensure_ascii=False, sort_keys=True),
                    json.dumps(review_fingerprints, ensure_ascii=False, sort_keys=True),
                    json.dumps(usages, ensure_ascii=False, sort_keys=True),
                    json.dumps(
                        [item.model_dump() for item in evidence],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    MEDICINE_COMBINATION_POLICY_PROVENANCE,
                    review_note,
                    MEDICINE_COMBINATION_POLICY_REVIEWER,
                    reviewed_at,
                    reviewed_at,
                ),
            )
        MedicineRepository._write_seed_version(
            conn,
            "medicine_combination_policy_version",
            MEDICINE_COMBINATION_POLICY_VERSION,
        )

    @staticmethod
    def _default_structured_contraindications(
        warnings: list[str],
    ) -> list[dict[str, str]]:
        structured: list[dict[str, str]] = []
        for warning in warnings:
            matched_codes = [
                concept_code
                for concept_code, terms in CONTRAINDICATION_CONCEPT_TERMS.items()
                if any(term in warning for term in terms)
            ]
            for concept_code in matched_codes or ["label_warning"]:
                structured.append(
                    {"concept_code": concept_code, "display_text": warning}
                )
        return structured

    @staticmethod
    def _row_to_medicine(row: object) -> Medicine:
        medicine = Medicine(
            id=row["id"],
            slot=row["slot"],
            hardware_slot=int(row["hardware_slot"]),
            barcode=row["barcode"] or "",
            manufacturer=row["manufacturer"] or "",
            name=row["name"],
            category=row["category"],
            spec=row["spec"] or "",
            trace_code=row["trace_code"] or "",
            tags=json.loads(row["tags_json"]),
            aliases=json.loads(row["aliases_json"] or "[]"),
            active_ingredients=json.loads(row["active_ingredients_json"] or "[]"),
            indications=row["indications"] or "",
            dosage=row["dosage"] or "",
            contraindications=json.loads(row["contraindications_json"]),
            structured_contraindications=json.loads(row["structured_contraindications_json"] or "[]"),
            stock=int(row["stock"]),
            low_stock_line=max(int(row["low_stock_line"]), 0),
            unit=row["unit"],
            expire_date=row["expire_date"],
            image_hint=row["image_hint"],
            is_otc=bool(row["is_otc"]),
            is_emergency=bool(row["is_emergency"]),
            safety_note=row["safety_note"],
            guidance_source=row["guidance_source"] or "pending",
            guidance_review_required=bool(row["guidance_review_required"]),
            package_verified=bool(row["package_verified"]),
            guidance_updated_at=row["guidance_updated_at"] or "",
            safety_review_status=row["safety_review_status"] or "draft",
            safety_reviewed_by=row["safety_reviewed_by"] or "",
            safety_reviewed_at=row["safety_reviewed_at"] or "",
            inventory_state=(row["inventory_state"] or "UNKNOWN"),
            inventory_confirmed_at=row["inventory_confirmed_at"] or "",
            last_inventory_request_id=row["last_inventory_request_id"] or "",
            last_inventory_dispense_record_id=row["last_inventory_dispense_record_id"] or "",
        )
        return medicine.model_copy(
            update={"review_fingerprint": MedicineRepository.review_fingerprint(medicine)}
        )

    @staticmethod
    def _sync_default_guidance(conn) -> None:
        version_row = conn.execute(
            "SELECT value FROM app_settings WHERE key='medicine_guidance_version'"
        ).fetchone()
        if not version_row or version_row["value"] != MEDICINE_GUIDANCE_VERSION:
            for item in DEFAULT_MEDICINES:
                conn.execute(
                    """
                    UPDATE medicines
                    SET indications=?,
                        dosage=?,
                        contraindications_json=?,
                        safety_note=?,
                        guidance_source=?,
                        guidance_review_required=?,
                        guidance_updated_at=?
                    WHERE id=? AND name=? AND barcode=? AND manufacturer=? AND spec=?
                    """,
                    (
                        item["indications"],
                        item["dosage"],
                        json.dumps(item["contraindications"], ensure_ascii=False),
                        item["safety_note"],
                        item["guidance_source"],
                        1 if item["guidance_review_required"] else 0,
                        db.now_text(),
                        item["id"],
                        item["name"],
                        item["barcode"],
                        item.get("manufacturer", ""),
                        item.get("spec", ""),
                    ),
                )
            conn.execute(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES ('medicine_guidance_version', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (MEDICINE_GUIDANCE_VERSION, db.now_text()),
            )
            return

        for item in DEFAULT_MEDICINES:
            conn.execute(
                """
                UPDATE medicines
                SET indications=CASE WHEN TRIM(COALESCE(indications, ''))='' THEN ? ELSE indications END,
                    dosage=CASE WHEN TRIM(COALESCE(dosage, ''))='' THEN ? ELSE dosage END,
                    guidance_source=CASE
                      WHEN TRIM(COALESCE(guidance_source, '')) IN ('', 'pending') THEN ?
                      ELSE guidance_source
                    END,
                    guidance_review_required=CASE
                      WHEN TRIM(COALESCE(indications, ''))='' OR TRIM(COALESCE(dosage, ''))='' THEN 1
                      ELSE guidance_review_required
                    END,
                    guidance_updated_at=CASE
                      WHEN TRIM(COALESCE(guidance_updated_at, ''))='' THEN ?
                      ELSE guidance_updated_at
                    END
                WHERE id=? AND name=? AND barcode=? AND manufacturer=? AND spec=?
                """,
                (
                    item["indications"],
                    item["dosage"],
                    item["guidance_source"],
                    db.now_text(),
                    item["id"],
                    item["name"],
                    item["barcode"],
                    item.get("manufacturer", ""),
                    item.get("spec", ""),
                ),
            )

    @staticmethod
    def _scan_id(name: str, barcode: str) -> str:
        if barcode:
            safe_barcode = re.sub(r"[^A-Za-z0-9_-]+", "-", barcode)[:36].strip("-")
            return f"scan-{safe_barcode or uuid4().hex[:10]}"
        safe_name = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]+", "-", name.strip())[:24].strip("-")
        return f"scan-{safe_name or uuid4().hex[:10]}"
