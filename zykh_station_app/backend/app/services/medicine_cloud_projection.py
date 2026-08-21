from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


class MedicineCloudProjectionError(ValueError):
    """Raised when a cloud medicine identity cannot be mapped without guessing."""


@dataclass(frozen=True)
class MedicineCloudProjection:
    """Translate one local medicine identity into the caregiver catalog identity.

    ``local_legacy_slot`` belongs to the Station database. ``cloud_legacy_slot``
    is only a compatibility identity in the caregiver catalog; neither field is
    a physical cabinet number. Physical ``cabinet_id`` remains owned by
    :mod:`cabinet_v2_catalog`.
    """

    local_medicine_id: str
    local_legacy_slot: int
    cloud_medicine_id: str
    cloud_legacy_slot: int
    storage_box: str


def _projection(
    local_medicine_id: str,
    local_legacy_slot: int,
    storage_box: str,
    *,
    cloud_medicine_id: str | None = None,
    cloud_legacy_slot: int | None = None,
) -> MedicineCloudProjection:
    return MedicineCloudProjection(
        local_medicine_id=local_medicine_id,
        local_legacy_slot=local_legacy_slot,
        cloud_medicine_id=cloud_medicine_id or local_medicine_id,
        cloud_legacy_slot=cloud_legacy_slot or local_legacy_slot,
        storage_box=storage_box,
    )


_MEDICINE_CLOUD_PROJECTIONS = (
    _projection("slot-01-fufang-ganmaoling", 1, "DAILY"),
    _projection("slot-02-centrum", 2, "PRESCRIPTION"),
    _projection(
        "slot-03-diosmectite",
        3,
        "DAILY",
        cloud_medicine_id="slot-13-montmorillonite",
        cloud_legacy_slot=13,
    ),
    _projection("slot-04-amoxicillin", 4, "PRESCRIPTION"),
    _projection("slot-05-nin-jiom-pei-pa-koa", 5, "DAILY"),
    _projection("slot-06-lactulose", 6, "PRESCRIPTION"),
    _projection("slot-07-yinhuang", 7, "DAILY"),
    _projection("slot-08-huoxiang-zhengqi", 8, "DAILY"),
    _projection("slot-09-bifid-triple", 9, "PRESCRIPTION"),
    _projection("slot-10-gauze", 10, "CARE"),
    _projection("slot-11-guilin-xiguashuang", 11, "DAILY"),
    _projection("slot-12-hydrotalcite", 12, "DAILY"),
    _projection(
        "slot-13-ibuprofen",
        13,
        "DAILY",
        cloud_medicine_id="slot-03-ibuprofen",
        cloud_legacy_slot=3,
    ),
    _projection("slot-14-oseltamivir", 14, "PRESCRIPTION"),
    _projection("slot-15-mupirocin", 15, "CARE"),
    _projection("slot-16-ketoconazole", 16, "CARE"),
    _projection("slot-17-iodophor", 17, "CARE"),
    _projection("slot-18-budesonide-nasal", 18, "CARE"),
    _projection("slot-19-ketoprofen-gel", 19, "CARE"),
    _projection("slot-20-bandage", 20, "CARE"),
    _projection("slot-21-amlodipine", 21, "PRESCRIPTION"),
    _projection("slot-22-cotton-swab", 22, "CARE"),
    _projection("slot-23-desloratadine", 23, "DAILY"),
)

_BY_LOCAL_MEDICINE_ID = {
    item.local_medicine_id: item for item in _MEDICINE_CLOUD_PROJECTIONS
}
_BY_CLOUD_MEDICINE_ID = {
    item.cloud_medicine_id: item for item in _MEDICINE_CLOUD_PROJECTIONS
}
_BY_CLOUD_LEGACY_SLOT = {
    item.cloud_legacy_slot: item for item in _MEDICINE_CLOUD_PROJECTIONS
}


def medicine_cloud_projections() -> tuple[MedicineCloudProjection, ...]:
    return _MEDICINE_CLOUD_PROJECTIONS


def validate_local_medicine_catalog(
    entries: Iterable[tuple[str, int]],
) -> None:
    """Require the Station's fixed catalog to match every transport identity exactly."""
    normalized = [
        (str(medicine_id or "").strip(), int(legacy_slot))
        for medicine_id, legacy_slot in entries
    ]
    expected = {
        (item.local_medicine_id, item.local_legacy_slot)
        for item in _MEDICINE_CLOUD_PROJECTIONS
    }
    expected_ids = {medicine_id for medicine_id, _ in expected}
    actual_ids = {medicine_id for medicine_id, _ in normalized}
    unexpected_ids = sorted(actual_ids - expected_ids)
    if unexpected_ids:
        raise MedicineCloudProjectionError(
            f"药品 {unexpected_ids[0]} 未配置小程序同步投影；"
            "本地固定药品目录不完整。"
        )
    if len(normalized) != len(expected) or actual_ids != expected_ids:
        raise MedicineCloudProjectionError(
            "本地固定药品目录不完整，必须恰好包含 23 种稳定药品身份。"
        )
    if set(normalized) != expected:
        raise MedicineCloudProjectionError(
            "本地固定药品目录的身份或兼容仓位错位。"
        )


def cloud_projection_for_local_medicine_id(
    medicine_id: str,
) -> MedicineCloudProjection:
    normalized_id = str(medicine_id or "").strip()
    projection = _BY_LOCAL_MEDICINE_ID.get(normalized_id)
    if projection is None:
        raise MedicineCloudProjectionError(
            f"药品 {normalized_id or '（空）'} 未配置小程序同步投影。"
        )
    return projection


def resolve_cloud_medicine(
    *,
    medicine_id: str = "",
    legacy_slot: int | None = None,
) -> MedicineCloudProjection:
    normalized_id = str(medicine_id or "").strip()
    by_id = _BY_CLOUD_MEDICINE_ID.get(normalized_id) if normalized_id else None
    by_slot = _BY_CLOUD_LEGACY_SLOT.get(legacy_slot) if legacy_slot is not None else None

    if normalized_id and by_id is None:
        raise MedicineCloudProjectionError(
            f"无法识别云端药品身份 {normalized_id}。"
        )
    if legacy_slot is not None and by_slot is None:
        raise MedicineCloudProjectionError(
            f"无法识别云端兼容仓位 {legacy_slot}。"
        )
    if by_id is not None and by_slot is not None and by_id != by_slot:
        raise MedicineCloudProjectionError("云端药品身份与兼容仓位不一致。")

    projection = by_id or by_slot
    if projection is None:
        raise MedicineCloudProjectionError("无法识别云端药品身份。")
    return projection


if not (
    len(_MEDICINE_CLOUD_PROJECTIONS)
    == len(_BY_LOCAL_MEDICINE_ID)
    == len(_BY_CLOUD_MEDICINE_ID)
    == len(_BY_CLOUD_LEGACY_SLOT)
    == 23
):
    raise RuntimeError("小程序药品同步投影必须完整且一一对应 23 种固定药品。")
