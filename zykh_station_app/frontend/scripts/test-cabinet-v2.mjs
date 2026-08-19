import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  groupMedicinesByCabinet,
  projectMedicinesToCabinets
} from "../src/utils/cabinetV2.js";


const cabinets = [
  { id: 1, label: "口服药品", description: "口服常用药", medicine_ids: ["oral-a", "oral-b"] },
  { id: 2, label: "外用药品", description: "局部使用药品", medicine_ids: ["topical-a"] },
  { id: 3, label: "医疗护理用品", description: "护理耗材", medicine_ids: ["care-a"] }
];
const medicines = [
  { id: "oral-a", name: "口服药A", hardware_slot: 1, stock: 1 },
  { id: "oral-b", name: "口服药B", hardware_slot: 13, stock: 1 },
  { id: "topical-a", name: "外用药A", hardware_slot: 18, stock: 1 },
  { id: "care-a", name: "护理用品A", hardware_slot: 22, stock: 1 }
];

const projected = projectMedicinesToCabinets(medicines, cabinets);
assert.deepEqual(
  projected.map(({ id, cabinet_id, cabinet_label }) => ({ id, cabinet_id, cabinet_label })),
  [
    { id: "oral-a", cabinet_id: 1, cabinet_label: "口服药品" },
    { id: "oral-b", cabinet_id: 1, cabinet_label: "口服药品" },
    { id: "topical-a", cabinet_id: 2, cabinet_label: "外用药品" },
    { id: "care-a", cabinet_id: 3, cabinet_label: "医疗护理用品" }
  ]
);

const grouped = groupMedicinesByCabinet(projected, cabinets);
assert.equal(grouped.length, 3);
assert.deepEqual(grouped.map((group) => group.medicines.length), [2, 1, 1]);
assert.equal(grouped[0].medicines[1].hardware_slot, 13, "logical slot identity remains unchanged");
const [unassigned] = projectMedicinesToCabinets(
  [{ id: "unmapped", name: "未知药", cabinet_id: 23, cabinet_label: "旧药柜" }],
  cabinets
);
assert.equal(unassigned.cabinet_id, null);
assert.equal(unassigned.cabinet_label, "分类柜待配置");
assert.equal(unassigned.cabinet_unassigned, true);
assert.deepEqual(
  groupMedicinesByCabinet([...projected, unassigned], cabinets).map((group) => group.medicines.length),
  [2, 1, 1],
  "unassigned legacy medicines remain visible to list views but are not routed to physical cabinets"
);

const medicinesPage = await readFile(
  new URL("../src/pages/Medicines.jsx", import.meta.url),
  "utf8"
);
const adminCabinet = await readFile(
  new URL("../src/components/admin/AdminCabinet.jsx", import.meta.url),
  "utf8"
);
assert.ok(
  medicinesPage.includes("medicine-cabinet-warning")
    && medicinesPage.includes("种药品尚未配置分类柜，已禁止取药"),
  "the medicine page must visibly count and warn about unassigned medicines"
);
assert.ok(
  adminCabinet.includes("admin-unassigned-medicine-panel")
    && adminCabinet.includes("种药品待配置分类柜"),
  "admin maintenance must show unassigned medicines instead of silently dropping them"
);

console.log("cabinet v2 projection contract: ok");
