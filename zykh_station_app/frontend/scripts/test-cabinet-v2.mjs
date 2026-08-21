import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  groupMedicinesByCabinet,
  projectMedicinesToCabinets,
  sortMedicinesByDispenseCount
} from "../src/utils/cabinetV2.js";
import { describeMedicineCabinet } from "../src/utils/cabinetLightPresentation.js";


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
    label: "慢病处方",
    description: "慢病固定用药、处方药与低频储备用药",
    medicine_ids: ["slot-09-bifid-triple"]
  }
];
const medicines = [
  { id: "slot-01-fufang-ganmaoling", name: "复方感冒灵颗粒", hardware_slot: 1, stock: 1, dispense_count: 2 },
  { id: "slot-13-ibuprofen", name: "布洛芬缓释胶囊", hardware_slot: 13, stock: 1, dispense_count: 8 },
  { id: "slot-18-budesonide-nasal", name: "布地奈德鼻喷雾剂", hardware_slot: 18, stock: 1, dispense_count: 8 },
  { id: "slot-22-cotton-swab", name: "医用棉签", hardware_slot: 22, stock: 1 },
  { id: "slot-09-bifid-triple", name: "双歧杆菌三联活菌肠溶胶囊", hardware_slot: 9, stock: 1, dispense_count: 3 }
];

const projected = projectMedicinesToCabinets(medicines, cabinets);
assert.deepEqual(
  projected.map(({ id, cabinet_id, cabinet_label }) => ({ id, cabinet_id, cabinet_label })),
  [
    { id: "slot-01-fufang-ganmaoling", cabinet_id: 1, cabinet_label: "日常用药" },
    { id: "slot-13-ibuprofen", cabinet_id: 1, cabinet_label: "日常用药" },
    { id: "slot-18-budesonide-nasal", cabinet_id: 2, cabinet_label: "外用护理" },
    { id: "slot-22-cotton-swab", cabinet_id: 2, cabinet_label: "外用护理" },
    { id: "slot-09-bifid-triple", cabinet_id: 3, cabinet_label: "慢病处方" }
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

const originalOrder = projected.map((medicine) => medicine.id);
assert.deepEqual(
  sortMedicinesByDispenseCount(projected).map((medicine) => medicine.id),
  [
    "slot-13-ibuprofen",
    "slot-18-budesonide-nasal",
    "slot-09-bifid-triple",
    "slot-01-fufang-ganmaoling",
    "slot-22-cotton-swab"
  ],
  "medicine usage sorting must be descending, deterministic on slot ties, and keep missing counts last"
);
assert.deepEqual(
  projected.map((medicine) => medicine.id),
  originalOrder,
  "usage sorting must not mutate the cabinet projection"
);
assert.equal(
  describeMedicineCabinet(projected[0]),
  "1号柜 · 日常用药",
  "numbered cabinet copy must use the short N号柜 form"
);

const medicinesPage = await readFile(
  new URL("../src/pages/Medicines.jsx", import.meta.url),
  "utf8"
);
const cabinetSlotMap = await readFile(
  new URL("../src/components/CabinetSlotMap.jsx", import.meta.url),
  "utf8"
);
const medicineCard = await readFile(
  new URL("../src/components/MedicineCard.jsx", import.meta.url),
  "utf8"
);
const numberedCabinetSources = await Promise.all([
  "../src/pages/Medicines.jsx",
  "../src/pages/Scan.jsx",
  "../src/components/MedicineCard.jsx",
  "../src/components/MedicineDetailPanel.jsx",
  "../src/components/CabinetSlotMap.jsx",
  "../src/components/admin/AdminCabinet.jsx",
  "../src/components/admin/AdminPlans.jsx"
].map((path) => readFile(new URL(path, import.meta.url), "utf8")));
const adminCabinet = await readFile(
  new URL("../src/components/admin/AdminCabinet.jsx", import.meta.url),
  "utf8"
);
assert.match(
  cabinetSlotMap,
  /<h3[^>]*>\{cabinet\.id\}号柜 · \{cabinet\.label\}<\/h3>/,
  "the default cabinet view must visibly identify every group as N号柜"
);
assert.ok(
  adminCabinet.includes("<small>号柜</small>"),
  "admin cabinet tabs must visibly use the same N号柜 wording"
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
assert.match(
  medicinesPage,
  /initialMedicineView\s*=\s*initialParams\.get\("medicineView"\)\s*===\s*"list"\s*\?\s*"list"\s*:\s*"cabinet"/,
  "the medicine page must default to the cabinet view unless list is explicitly requested"
);
assert.equal(
  /sortMode|medicine-list-view|medicine-sort-control|medicine-sort-select|药品排序|默认柜位顺序/.test(medicinesPage),
  false,
  "the medicine view must keep the v2.0.0 interface without a visible sorting control"
);
assert.equal(
  /const sortedMedicines\s*=\s*useMemo\(\(\)\s*=>\s*sortMedicinesByDispenseCount\(medicines\)/.test(medicinesPage),
  true,
  "the medicine view must derive its fixed descending usage order"
);
assert.equal(
  /viewMode === "list"\s*\?\s*\(\s*<VirtualMedicineGrid[\s\S]{0,300}?medicines=\{sortedMedicines\}/.test(medicinesPage),
  true,
  "the v2.0.0 medicine grid must receive the fixed descending usage order directly"
);
assert.equal(
  /function selectViewMode[\s\S]*nextViewMode === "list"[\s\S]*setSelectedMedicine\(sortedMedicines\[0\]/.test(medicinesPage),
  true,
  "switching to the medicine view must select from the same fixed descending order"
);
assert.equal(
  /medicines=\{sortedMedicines\}[\s\S]{0,180}?onSelect=\{setSelectedMedicine\}/.test(medicinesPage),
  true,
  "selecting a medicine must not replace or reorder the fixed descending list"
);
assert.equal(
  /medicine-use-count|历史取药|dispense_count/.test(medicineCard),
  false,
  "the v2.0.0 medicine card must not gain a visible usage-count row"
);
assert.doesNotMatch(
  cabinetSlotMap,
  /cabinet-light-label|号分类柜指示灯/,
  "the cabinet view must not render a numbered classification-light badge"
);
for (const source of numberedCabinetSources) {
  assert.doesNotMatch(source, /号分类柜/, "numbered cabinet copy must consistently use N号柜");
}

console.log("cabinet v2 projection contract: ok");
