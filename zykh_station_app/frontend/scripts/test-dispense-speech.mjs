import assert from "node:assert/strict";
import {
  buildDispenseFailureSpeech,
  buildDispenseGuidanceSpeech,
  buildDispenseSuccessSpeech,
  resolveDispenseUsage
} from "../src/utils/dispenseSpeech.js";

const medicine = {
  name: "藿香正气丸",
  dosage: "口服，一次1丸，一日2次。",
  safety_note: "注意补液并观察。"
};

assert.equal(resolveDispenseUsage(medicine), medicine.dosage);
assert.equal(
  resolveDispenseUsage(medicine, { dose: "1丸", timing_label: "饭后" }),
  "1丸"
);
assert.match(buildDispenseGuidanceSpeech(medicine, null, "face"), /一次1丸/);
assert.match(buildDispenseGuidanceSpeech(medicine, null, "face"), /面向摄像头/);
assert.match(buildDispenseGuidanceSpeech(medicine, { dose: "1丸" }, "fingerprint"), /指纹传感器/);
assert.equal(buildDispenseSuccessSpeech(medicine), "藿香正气丸已弹出，请取出药品并关闭柜门。");
assert.match(buildDispenseFailureSpeech("未识别到指纹"), /未识别到指纹/);

console.log("dispense speech contract: ok");
