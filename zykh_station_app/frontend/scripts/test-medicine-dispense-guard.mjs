import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import {
  manualDispenseBlockHint,
  manualDispenseBlockReason,
  manualDispenseButtonLabel
} from "../src/utils/medicineSafety.js";

const modal = fs.readFileSync(
  path.join(process.cwd(), "src/components/DispenseConfirmModal.jsx"),
  "utf8"
);
const detailPanel = fs.readFileSync(
  path.join(process.cwd(), "src/components/MedicineDetailPanel.jsx"),
  "utf8"
);

const base = {
  is_otc: true,
  package_verified: true,
  guidance_source: "label_reference",
  expire_date: "2028-08"
};

assert.equal(manualDispenseBlockReason(base, new Date("2026-08-05")), "");
assert.equal(
  manualDispenseBlockReason({ ...base, package_verified: false }, new Date("2026-08-05")),
  "包装规格待人工核验，暂不可取药"
);
assert.equal(
  manualDispenseBlockReason({ ...base, guidance_source: "pending", expire_date: "待补录" }, new Date("2026-08-05")),
  "资料待补录，暂不可取药"
);
assert.equal(
  manualDispenseBlockReason({ ...base, expire_date: "2026-02" }, new Date("2026-08-05")),
  "药品已过有效期，暂不可取药"
);
assert.equal(
  manualDispenseBlockReason({ ...base, expire_date: "2026-08-01" }, new Date("2026-08-05")),
  "药品已过有效期，暂不可取药"
);
assert.equal(
  manualDispenseBlockReason({ ...base, expire_date: "2026-08-05" }, new Date("2026-08-05")),
  ""
);
assert.equal(
  manualDispenseBlockReason({ ...base, expire_date: "2026-02-30" }, new Date("2026-08-05")),
  "资料待补录，暂不可取药"
);
assert.equal(
  manualDispenseBlockReason({ ...base, is_otc: false }, new Date("2026-08-05")),
  ""
);
assert.equal(
  manualDispenseButtonLabel({ ...base, is_otc: false }, new Date("2026-08-05")),
  "确认身份并核查"
);
assert.equal(
  manualDispenseBlockHint({ ...base, is_otc: false }, new Date("2026-08-05")),
  ""
);
assert.equal(manualDispenseButtonLabel(base, new Date("2026-08-05")), "确认身份并核查");
assert.match(modal, /禁忌提醒/);
assert.match(modal, /慎用与指导提醒/);
assert.doesNotMatch(
  modal,
  /medicine\.contraindications[^\n]*\|\|\s*medicine\.safety_note/,
  "dispense confirmation must not hide the safety note when contraindications exist"
);
assert.ok(
  detailPanel.includes("medicine.safety_note")
    && detailPanel.includes("detail-safety")
    && detailPanel.includes("慎用与指导提醒"),
  "medicine details must show the safety note separately from contraindications"
);

console.log("medicine dispense guard contract: ok");
