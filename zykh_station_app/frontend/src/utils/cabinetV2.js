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

export function groupMedicinesByCabinet(medicines, cabinets) {
  return (cabinets || []).map((cabinet) => ({
    ...cabinet,
    medicines: (medicines || []).filter((medicine) => medicine.cabinet_id === cabinet.id)
  }));
}
