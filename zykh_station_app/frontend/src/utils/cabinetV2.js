export function projectMedicinesToCabinets(medicines, cabinets) {
  const cabinetByMedicineId = new Map();
  for (const cabinet of cabinets || []) {
    for (const medicineId of cabinet.medicine_ids || []) {
      cabinetByMedicineId.set(medicineId, cabinet);
    }
  }

  return (medicines || []).map((medicine) => {
    const cabinet = cabinetByMedicineId.get(medicine.id);
    if (!cabinet) {
      return {
        ...medicine,
        cabinet_id: null,
        cabinet_label: "分类柜待配置",
        cabinet_description: "该药品尚未配置分类柜，暂不能取药。",
        cabinet_unassigned: true
      };
    }
    return {
      ...medicine,
      cabinet_id: cabinet.id,
      cabinet_label: cabinet.label,
      cabinet_description: cabinet.description,
      cabinet_unassigned: false
    };
  });
}

export function sortMedicinesByDispenseCount(medicines) {
  return (medicines || [])
    .map((medicine, index) => ({ medicine, index }))
    .sort((left, right) => {
      const leftCount = Number(left.medicine.dispense_count) || 0;
      const rightCount = Number(right.medicine.dispense_count) || 0;
      if (leftCount !== rightCount) return rightCount - leftCount;

      const leftSlot = Number(left.medicine.hardware_slot);
      const rightSlot = Number(right.medicine.hardware_slot);
      const leftHasSlot = Number.isFinite(leftSlot);
      const rightHasSlot = Number.isFinite(rightSlot);
      if (leftHasSlot && rightHasSlot && leftSlot !== rightSlot) return leftSlot - rightSlot;
      if (leftHasSlot !== rightHasSlot) return leftHasSlot ? -1 : 1;
      return left.index - right.index;
    })
    .map(({ medicine }) => medicine);
}

export function groupMedicinesByCabinet(medicines, cabinets) {
  return (cabinets || []).map((cabinet) => ({
    ...cabinet,
    medicines: (medicines || []).filter((medicine) => medicine.cabinet_id === cabinet.id)
  }));
}
