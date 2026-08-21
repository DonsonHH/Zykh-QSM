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
        label="日常用药",
        description="感冒、发热、咳嗽、过敏、咽喉与胃肠常用药",
        medicine_ids=frozenset(
            {
                "slot-01-fufang-ganmaoling",
                "slot-03-diosmectite",
                "slot-05-nin-jiom-pei-pa-koa",
                "slot-07-yinhuang",
                "slot-08-huoxiang-zhengqi",
                "slot-11-guilin-xiguashuang",
                "slot-12-hydrotalcite",
                "slot-13-ibuprofen",
                "slot-23-desloratadine",
            }
        ),
    ),
    CabinetGroup(
        id=2,
        label="外用护理",
        description="消毒、伤口、皮肤、鼻部与局部疼痛护理",
        medicine_ids=frozenset(
            {
                "slot-10-gauze",
                "slot-15-mupirocin",
                "slot-16-ketoconazole",
                "slot-17-iodophor",
                "slot-18-budesonide-nasal",
                "slot-19-ketoprofen-gel",
                "slot-20-bandage",
                "slot-22-cotton-swab",
            }
        ),
    ),
    CabinetGroup(
        id=3,
        label="慢病处方",
        description="慢病固定用药、处方药与低频储备用药",
        medicine_ids=frozenset(
            {
                "slot-02-centrum",
                "slot-04-amoxicillin",
                "slot-06-lactulose",
                "slot-09-bifid-triple",
                "slot-14-oseltamivir",
                "slot-21-amlodipine",
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
