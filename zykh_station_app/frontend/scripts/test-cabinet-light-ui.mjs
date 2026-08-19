import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const qsmApi = await readFile(`${frontendRoot}src/api/qsm.js`, "utf8");
const modal = await readFile(`${frontendRoot}src/components/DispenseConfirmModal.jsx`, "utf8");
const inquiryPage = await readFile(`${frontendRoot}src/pages/Inquiry.jsx`, "utf8");
const inquiryResult = await readFile(`${frontendRoot}src/components/InquiryResultStep.jsx`, "utf8");
const inventoryPrompt = await readFile(`${frontendRoot}src/components/MedicineRemainingPrompt.jsx`, "utf8");
const adminCabinet = await readFile(`${frontendRoot}src/components/admin/AdminCabinet.jsx`, "utf8");
const systemCheck = await readFile(`${frontendRoot}src/components/SystemCheckModal.jsx`, "utf8");
const presentation = await import(
  pathToFileURL(`${frontendRoot}src/utils/cabinetLightPresentation.js`).href
);

assert.match(
  qsmApi,
  /apiPost\("\/api\/qsm\/cabinet-light\/off", \{\}\)/,
  "the frontend must use the local cabinet-light OFF endpoint"
);
assert.ok(
  modal.includes("turnOffCabinetLight") && modal.includes("我已取药，关闭指示灯"),
  "dispense completion must require an explicit taken-and-lights-off action"
);
assert.ok(
  !modal.includes("DISPENSE_COMPLETE_HOLD_MS"),
  "dispense completion must not automatically skip past the lit-cabinet state"
);
assert.match(
  modal,
  /result_unknown[\s\S]*cabinetLightMayBeOnRef\.current = true|cabinetLightMayBeOnRef\.current = true[\s\S]*result_unknown/,
  "an uncertain dispense result must be treated as a cabinet light that may still be on"
);
assert.ok(
  modal.includes("closeUncertainCabinetLight")
    && modal.includes("关闭分类柜指示灯")
    && modal.includes('phase === "result_unknown"'),
  "an uncertain dispense result must expose only a retryable cabinet-light OFF action"
);
assert.ok(
  inquiryPage.includes("await turnOffCabinetLight()"),
  "inquiry inventory confirmation must turn the cabinet light off before advancing"
);
assert.ok(
  inquiryPage.includes('confirmation_mode: completedItem.result_unknown ? "result_unknown"')
    && inquiryPage.includes('completedItem.inventory_confirmation_required ? "inventory" : "pickup"')
    && inquiryPage.includes("cabinetLightMayBeOnRef.current = true"),
  "every real inquiry light attempt, including an unknown result, must stop for explicit OFF"
);
assert.ok(
  inquiryResult.includes("分类柜指示灯") && !inquiryResult.includes("打开柜门"),
  "inquiry treatment UI must describe cabinet lighting, not automatic door opening"
);
assert.ok(
  inquiryResult.includes("onCabinetLightOff")
    && inventoryPrompt.includes('mode = "inventory"')
    && inventoryPrompt.includes("我已取药，关闭指示灯")
    && inventoryPrompt.includes("亮灯结果待确认，请勿重复操作"),
  "inquiry pickup and unknown-result prompts must both require an explicit OFF action"
);
assert.ok(
  inventoryPrompt.includes("分类柜内还有药吗"),
  "inventory confirmation must refer to the physical category cabinet"
);
assert.ok(
  adminCabinet.includes("三个分类柜")
    && adminCabinet.includes("loadMedicines")
    && !adminCabinet.includes("Array.from({ length: 23")
    && !adminCabinet.includes("打开柜门"),
  "local cabinet maintenance must project medicine records into three category cabinets"
);
assert.ok(
  systemCheck.includes("cabinet_light_status")
    && systemCheck.includes("已连接，三柜熄灭")
    && systemCheck.includes("状态不可用"),
  "system check must report the controller's verified STATUS instead of configuration alone"
);

assert.equal(
  presentation.describeMedicineCabinet({ cabinet_id: 2, cabinet_label: "外用药品" }),
  "2号分类柜 · 外用药品"
);
assert.equal(
  presentation.describeMedicineCabinet({ hardware_slot: 13, slot: "13" }),
  "对应分类柜",
  "legacy logical slots must not leak into the cabinet-light UI"
);
assert.equal(
  presentation.normalizeCabinetLightMessage("柜门已打开，请取出药品并关闭柜门。"),
  "分类柜指示灯已亮，请自行打开亮灯的分类柜取药。"
);
assert.equal(
  presentation.normalizeCabinetLightMessage("开柜未完成，请现场确认柜门状态"),
  "分类柜亮灯未完成，请现场确认指示灯状态"
);

console.log("cabinet light UI contract: ok");
