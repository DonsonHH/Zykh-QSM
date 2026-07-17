from __future__ import annotations

import json
import re
from uuid import uuid4

from .. import db
from ..schemas.medicine import Medicine


MEDICINE_SEED_VERSION = "home-real-cabinet-v4-no-decrement"

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

DEFAULT_MEDICINE_GUIDANCE = {
    "slot-01-fufang-ganmaoling": {
        "indications": "辛凉解表、清热解毒，用于风热感冒引起的发热、头痛、咽痛、鼻塞流浊涕及咳嗽。",
        "dosage": "开水冲服；成人每次用量和每日次数按当前包装说明书，避免与其他含对乙酰氨基酚药品同用。",
    },
    "slot-02-centrum": {
        "indications": "用于成人因维生素和矿物质摄入不足所致的营养补充。",
        "dosage": "成人通常每日1片，饭后服用；儿童、孕期或慢病患者按说明书或医嘱。",
    },
    "slot-03-ganmao-qingre": {
        "indications": "疏风散寒、解表清热，用于风寒感冒引起的头痛发热、恶寒身痛、鼻流清涕和咳嗽咽干。",
        "dosage": "开水冲服，通常每日2次；每袋规格可能不同，单次用量以当前包装说明书为准。",
    },
    "slot-04-amoxicillin": {
        "indications": "用于对阿莫西林敏感细菌所致的感染，仅在医生判断并已有处方或医嘱时使用。",
        "dosage": "处方药；按感染类型、年龄、体重及肾功能由医生确定剂量和疗程，不自行加量或停药。",
    },
    "slot-05-nin-jiom-pei-pa-koa": {
        "indications": "润肺化痰、止咳平喘、护喉利咽，用于咳嗽、痰多、咽喉干痒及声音嘶哑等不适。",
        "dosage": "口服，按瓶身量杯和当前包装说明书取用；儿童、糖尿病患者及孕期人员先咨询医生。",
    },
    "slot-06-lactulose": {
        "indications": "用于慢性或功能性便秘，通过调节结肠生理节律帮助排便。",
        "dosage": "口服，可随餐服用并根据排便情况调整；起始量和维持量按包装说明书或医嘱。",
    },
    "slot-07-yinhuang": {
        "indications": "清热疏风、利咽解毒，用于外感风热或上呼吸道不适引起的咽干、咽痛。",
        "dosage": "开水冲服；单次剂量和每日次数按当前包装说明书，连续使用后无改善应联系医生。",
    },
    "slot-08-huoxiang-zhengqi": {
        "indications": "解表化湿、理气和中，用于暑湿感冒、头痛身重胸闷、脘腹胀痛、呕吐泄泻。",
        "dosage": "口服，当前大蜜丸规格通常每次1丸、每日2次；取用前仍需核对实物包装说明书。",
    },
    "slot-09-bifid-triple": {
        "indications": "用于肠道菌群失调引起的腹泻、便秘、腹胀等消化道不适。",
        "dosage": "饭后口服，用量按年龄和当前包装说明书；与抗菌药至少错开2小时并按要求冷藏。",
    },
    "slot-10-gauze": {
        "indications": "用于清洁后的浅表伤口覆盖、吸收渗液和辅助包扎。",
        "dosage": "一次性外用；按伤口范围选择合适尺寸，污染、浸湿或松脱后及时更换。",
    },
    "slot-11-guilin-xiguashuang": {
        "indications": "清热解毒、消肿止痛，用于咽喉肿痛、口舌生疮及牙龈肿痛等口咽不适。",
        "dosage": "外用喷敷患处，次数按当前包装说明书；操作时屏住呼吸，避免粉末吸入气道。",
    },
    "slot-12-hydrotalcite": {
        "indications": "用于胃酸相关的胃痛、胃灼热、酸性嗳气、饱胀等症状，以及相关胃黏膜保护。",
        "dosage": "咀嚼后服用，通常在餐后1至2小时、睡前或症状出现时使用；剂量以包装说明书为准。",
    },
    "slot-13-sodium-hyaluronate-eye": {
        "indications": "用于干眼、眼表刺激或角结膜上皮损伤相关的干涩、异物感等不适。",
        "dosage": "滴入结膜囊，每次1滴；每日次数按说明书或医嘱，瓶口不要接触眼睛和皮肤。",
    },
    "slot-14-oseltamivir": {
        "indications": "用于甲型和乙型流感的治疗或预防，适用时机需结合发病时间并由医生核验。",
        "dosage": "处方药；按年龄、体重、肾功能和用途由医生确定剂量及疗程，不用于普通感冒自行服用。",
    },
    "slot-15-mupirocin": {
        "indications": "用于脓疱病、毛囊炎、疖肿等原发性皮肤感染，以及小面积继发性细菌感染。",
        "dosage": "局部外用，薄涂患处；每日次数和疗程按说明书或医嘱，连续使用无改善需复诊。",
    },
    "slot-16-ketoconazole": {
        "indications": "用于手足癣、体股癣、花斑癣及皮肤念珠菌病等浅表真菌感染。",
        "dosage": "清洁并擦干患处后薄涂，通常每日1至2次；疗程按感染部位和包装说明书执行。",
    },
    "slot-17-iodophor": {
        "indications": "用于完整皮肤消毒及清洁浅表小伤口周围皮肤。",
        "dosage": "仅限外用，用无菌棉签或纱布蘸取后涂擦；使用浓度、作用时间以瓶身说明为准。",
    },
    "slot-18-budesonide-nasal": {
        "indications": "用于季节性或常年性过敏性鼻炎引起的鼻塞、流涕、喷嚏和鼻痒。",
        "dosage": "仅鼻腔喷用，先清洁鼻腔并按说明书完成预喷；使用最低有效剂量，具体喷数按医嘱。",
    },
    "slot-19-ketoprofen-gel": {
        "indications": "用于扭伤、挫伤、肌腱或关节周围软组织损伤引起的局部疼痛和炎症。",
        "dosage": "仅完整皮肤外用，取适量轻揉患处；每日次数按说明书，使用部位避免日晒和紫外线。",
    },
    "slot-20-bandage": {
        "indications": "用于清洁、干燥的浅表小伤口止血后覆盖和日常保护。",
        "dosage": "一次性外用；伤口清洁干燥后贴敷，受潮、污染或每日检查时及时更换。",
    },
    "slot-21-amlodipine": {
        "indications": "用于高血压及部分心绞痛患者的长期管理，仅供已有治疗计划的家庭成员按医嘱取用。",
        "dosage": "处方药，通常每日固定时间服用；具体剂量只按既往处方，不因单次血压变化自行调整。",
    },
    "slot-22-cotton-swab": {
        "indications": "用于皮肤或浅表伤口清洁、消毒时辅助蘸取外用液体。",
        "dosage": "一次性外用；每根仅使用一次，避免深入耳道、鼻腔或接触深部伤口。",
    },
    "slot-23-desloratadine": {
        "indications": "用于缓解过敏性鼻炎相关鼻痒、喷嚏、流涕，以及慢性荨麻疹相关瘙痒和风团。",
        "dosage": "处方药，通常每日服用一次；具体规格和剂量按既往医嘱及当前包装说明书。",
    },
}

for _medicine in DEFAULT_MEDICINES:
    _guidance = DEFAULT_MEDICINE_GUIDANCE[_medicine["id"]]
    _medicine.update(
        indications=_guidance["indications"],
        dosage=_guidance["dosage"],
        guidance_source="seed_reference",
        guidance_review_required=True,
    )


class MedicineRepository:
    def list_all(self) -> list[Medicine]:
        self._ensure_seeded()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, slot, hardware_slot, barcode, name, category, tags_json,
                       indications, dosage, contraindications_json, stock, unit, expire_date,
                       image_hint, manufacturer, is_otc, is_emergency, safety_note,
                       guidance_source, guidance_review_required, guidance_updated_at
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
                       indications, dosage, contraindications_json, stock, unit, expire_date,
                       image_hint, manufacturer, is_otc, is_emergency, safety_note,
                       guidance_source, guidance_review_required, guidance_updated_at
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
                       indications, dosage, contraindications_json, stock, unit, expire_date,
                       image_hint, manufacturer, is_otc, is_emergency, safety_note,
                       guidance_source, guidance_review_required, guidance_updated_at
                FROM medicines
                WHERE barcode=?
                """,
                (barcode,),
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
            "tags": medicine.tags,
            "indications": medicine.indications,
            "dosage": medicine.dosage,
            "contraindications": medicine.contraindications,
            "stock": medicine.stock,
            "unit": medicine.unit,
            "expire_date": medicine.expire_date,
            "is_otc": medicine.is_otc,
            "is_emergency": medicine.is_emergency,
            "safety_note": medicine.safety_note,
            "image_hint": medicine.image_hint,
            "guidance_source": medicine.guidance_source,
            "guidance_review_required": medicine.guidance_review_required,
            "guidance_updated_at": medicine.guidance_updated_at,
        }
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
                "expire_date",
                "safety_note",
                "indications",
                "dosage",
                "guidance_source",
                "guidance_updated_at",
            }:
                next_values[key] = str(value).strip()
                continue
            if key in {"tags", "contraindications"} and isinstance(value, list):
                next_values[key] = [str(item).strip() for item in value if str(item).strip()]
                continue
            if key == "stock":
                next_values[key] = max(int(value), 0)
                continue
            if key in {"is_otc", "is_emergency", "guidance_review_required"}:
                next_values[key] = bool(value)

        next_values["image_hint"] = f"{next_values['manufacturer']} {next_values['name']}".strip() or medicine.image_hint
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET barcode=?, manufacturer=?, name=?, category=?, tags_json=?,
                    indications=?, dosage=?, contraindications_json=?, stock=?, unit=?, expire_date=?,
                    image_hint=?, is_otc=?, is_emergency=?, safety_note=?, guidance_source=?,
                    guidance_review_required=?, guidance_updated_at=?, updated_at=?
                WHERE id=?
                """,
                (
                    next_values["barcode"],
                    next_values["manufacturer"],
                    next_values["name"],
                    next_values["category"],
                    json.dumps(next_values["tags"], ensure_ascii=False),
                    next_values["indications"],
                    next_values["dosage"],
                    json.dumps(next_values["contraindications"], ensure_ascii=False),
                    int(next_values["stock"]),
                    next_values["unit"],
                    next_values["expire_date"],
                    next_values["image_hint"],
                    1 if next_values["is_otc"] else 0,
                    1 if next_values["is_emergency"] else 0,
                    next_values["safety_note"],
                    next_values["guidance_source"],
                    1 if next_values["guidance_review_required"] else 0,
                    next_values["guidance_updated_at"],
                    db.now_text(),
                    medicine_id,
                ),
            )
        return self.get_by_id(medicine_id)

    def create_from_scan(
        self,
        *,
        barcode: str,
        manufacturer: str = "",
        name: str,
        spec: str = "",
        expire_date: str = "",
        stock: int = 1,
        unit: str = "盒",
        category: str = "扫码录入",
        indications: str = "",
        dosage: str = "",
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
                  indications, dosage, contraindications_json, stock, unit, expire_date, image_hint,
                  is_otc, is_emergency, safety_note, guidance_source,
                  guidance_review_required, guidance_updated_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  barcode=excluded.barcode,
                  manufacturer=excluded.manufacturer,
                  name=excluded.name,
                  category=excluded.category,
                  indications=excluded.indications,
                  dosage=excluded.dosage,
                  stock=excluded.stock,
                  unit=excluded.unit,
                  expire_date=excluded.expire_date,
                  image_hint=excluded.image_hint,
                  safety_note=excluded.safety_note,
                  guidance_source=excluded.guidance_source,
                  guidance_review_required=excluded.guidance_review_required,
                  guidance_updated_at=excluded.guidance_updated_at,
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
                    json.dumps(["扫码录入", "待核验"], ensure_ascii=False),
                    indications.strip(),
                    dosage.strip(),
                    json.dumps(["请人工核对药品说明"], ensure_ascii=False),
                    stock,
                    unit.strip() or "盒",
                    expire_date.strip(),
                    spec.strip() or "扫码录入",
                    1,
                    0,
                    safety,
                    "pending",
                    1,
                    db.now_text(),
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
                self._sync_default_guidance(conn)
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
              indications, dosage, contraindications_json, stock, unit, expire_date, image_hint,
              is_otc, is_emergency, safety_note, guidance_source,
              guidance_review_required, guidance_updated_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    db.now_text(),
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
            indications=row["indications"] or "",
            dosage=row["dosage"] or "",
            contraindications=json.loads(row["contraindications_json"]),
            stock=int(row["stock"]),
            unit=row["unit"],
            expire_date=row["expire_date"],
            image_hint=row["image_hint"],
            is_otc=bool(row["is_otc"]),
            is_emergency=bool(row["is_emergency"]),
            safety_note=row["safety_note"],
            guidance_source=row["guidance_source"] or "pending",
            guidance_review_required=bool(row["guidance_review_required"]),
            guidance_updated_at=row["guidance_updated_at"] or "",
        )

    @staticmethod
    def _sync_default_guidance(conn) -> None:
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
                WHERE id=?
                """,
                (
                    item["indications"],
                    item["dosage"],
                    item["guidance_source"],
                    db.now_text(),
                    item["id"],
                ),
            )

    @staticmethod
    def _scan_id(name: str, barcode: str) -> str:
        if barcode:
            safe_barcode = re.sub(r"[^A-Za-z0-9_-]+", "-", barcode)[:36].strip("-")
            return f"scan-{safe_barcode or uuid4().hex[:10]}"
        safe_name = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]+", "-", name.strip())[:24].strip("-")
        return f"scan-{safe_name or uuid4().hex[:10]}"
