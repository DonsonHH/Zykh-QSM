import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  groupMedicinesByCabinet,
  projectMedicinesToCabinets
} from "../src/utils/cabinetV2.js";


const cabinets = [
  {
    id: 1,
    label: "日常用药",
    description: "感冒、发热、咳嗽、过敏、咽喉与胃肠常用药",
    medicine_ids: ["slot-01-fufang-ganmaoling", "slot-13-ibuprofen"]
  },
  {
    id: 2,
    label: "外用护理",
    description: "消毒、伤口、皮肤、鼻部与局部疼痛护理",
    medicine_ids: ["slot-18-budesonide-nasal", "slot-22-cotton-swab"]
  },
  {
    id: 3,
    label: "慢病处方储备",
    description: "慢病固定用药、处方药与低频储备用药",
    medicine_ids: ["slot-09-bifid-triple"]
  }
];
const medicines = [
  { id: "slot-01-fufang-ganmaoling", name: "复方感冒灵颗粒", hardware_slot: 1, stock: 1 },
  { id: "slot-13-ibuprofen", name: "布洛芬缓释胶囊", hardware_slot: 13, stock: 1 },
  { id: "slot-18-budesonide-nasal", name: "布地奈德鼻喷雾剂", hardware_slot: 18, stock: 1 },
  { id: "slot-22-cotton-swab", name: "医用棉签", hardware_slot: 22, stock: 1 },
  { id: "slot-09-bifid-triple", name: "双歧杆菌三联活菌肠溶胶囊", hardware_slot: 9, stock: 1 }
];

const projected = projectMedicinesToCabinets(medicines, cabinets);
assert.deepEqual(
  projected.map(({ id, cabinet_id, cabinet_label }) => ({ id, cabinet_id, cabinet_label })),
  [
    { id: "slot-01-fufang-ganmaoling", cabinet_id: 1, cabinet_label: "日常用药" },
    { id: "slot-13-ibuprofen", cabinet_id: 1, cabinet_label: "日常用药" },
    { id: "slot-18-budesonide-nasal", cabinet_id: 2, cabinet_label: "外用护理" },
    { id: "slot-22-cotton-swab", cabinet_id: 2, cabinet_label: "外用护理" },
    { id: "slot-09-bifid-triple", cabinet_id: 3, cabinet_label: "慢病处方储备" }
  ]
);

const grouped = groupMedicinesByCabinet(projected, cabinets);
assert.equal(grouped.length, 3);
assert.deepEqual(grouped.map((group) => group.medicines.length), [2, 2, 1]);
assert.equal(grouped[0].medicines[1].hardware_slot, 13, "logical slot identity remains unchanged");
assert.equal(grouped[1].medicines[1].hardware_slot, 22, "S22 is physically routed to cabinet 2");
const [unassigned] = projectMedicinesToCabinets(
  [{ id: "unmapped", name: "未知药", cabinet_id: 23, cabinet_label: "旧药柜" }],
  cabinets
);
assert.equal(unassigned.cabinet_id, null);
assert.equal(unassigned.cabinet_label, "分类柜待配置");
assert.equal(unassigned.cabinet_unassigned, true);
assert.deepEqual(
  groupMedicinesByCabinet([...projected, unassigned], cabinets).map((group) => group.medicines.length),
  [2, 2, 1],
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
