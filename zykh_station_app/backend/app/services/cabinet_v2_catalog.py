from __future__ import annotations

from dataclasses import dataclass


class CabinetMappingError(ValueError):
    """Raised when a local medicine is not assigned to a physical v2 cabinet."""


@dataclass(frozen=True)
class CabinetGroup:
    id: int
    label: str
    description: str
    medicine_ids: frozenset[str]


_CABINET_GROUPS = (
    CabinetGroup(
        id=1,
        label="口服药品",
        description="口服常用药、慢病用药与营养补充",
        medicine_ids=frozenset(
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
                "slot-12-hydrotalcite",
                "slot-13-ibuprofen",
                "slot-14-oseltamivir",
                "slot-21-amlodipine",
                "slot-23-desloratadine",
            }
        ),
    ),
    CabinetGroup(
        id=2,
        label="外用药品",
        description="皮肤、鼻腔、咽喉消毒与局部护理药品",
        medicine_ids=frozenset(
            {
                "slot-11-guilin-xiguashuang",
                "slot-15-mupirocin",
                "slot-16-ketoconazole",
                "slot-17-iodophor",
                "slot-18-budesonide-nasal",
                "slot-19-ketoprofen-gel",
            }
        ),
    ),
    CabinetGroup(
        id=3,
        label="医疗护理用品",
        description="纱布、创口贴与医用棉签",
        medicine_ids=frozenset(
            {
                "slot-10-gauze",
                "slot-20-bandage",
                "slot-22-cotton-swab",
            }
        ),
    ),
)

_CABINET_BY_MEDICINE_ID = {
    medicine_id: cabinet
    for cabinet in _CABINET_GROUPS
    for medicine_id in cabinet.medicine_ids
}


def cabinet_groups() -> tuple[CabinetGroup, ...]:
    return _CABINET_GROUPS


def mapped_medicine_ids() -> frozenset[str]:
    return frozenset(_CABINET_BY_MEDICINE_ID)


def cabinet_for_medicine_id(medicine_id: str) -> CabinetGroup:
    normalized_id = str(medicine_id or "").strip()
    cabinet = _CABINET_BY_MEDICINE_ID.get(normalized_id)
    if cabinet is None:
        raise CabinetMappingError(f"药品 {normalized_id or '（空）'} 未配置分类柜，已停止取药。")
    return cabinet
