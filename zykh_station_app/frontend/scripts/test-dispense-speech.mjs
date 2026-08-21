import assert from "node:assert/strict";
import {
  buildDispenseFailureSpeech,
  buildDispenseGuidanceSpeech,
  buildDispenseSuccessSpeech,
  resolveDispenseUsage
} from "../src/utils/dispenseSpeech.js";

const medicine = {
  name: "藿香正气丸",
  cabinet_id: 1,
  cabinet_label: "日常用药",
  dosage: "口服，一次1丸，一日2次。",
  safety_note: "注意补液并观察。"
};

assert.equal(resolveDispenseUsage(medicine), medicine.dosage);
assert.equal(
  resolveDispenseUsage(medicine, { dose: "1丸", timing_label: "饭后" }),
  "1丸"
);
assert.match(buildDispenseGuidanceSpeech(medicine, null, "face"), /面向摄像头/);
assert.match(buildDispenseGuidanceSpeech(medicine, { dose: "1丸" }, "fingerprint"), /指纹传感器/);
assert.doesNotMatch(buildDispenseGuidanceSpeech(medicine, null, "face"), /本次用法|一次1丸/);
assert.equal(
  buildDispenseSuccessSpeech(medicine),
  "藿香正气丸所在的1号柜指示灯已亮，请自行打开亮灯的分类柜取药，并确认柜内是否还有药。确认页面结束后，指示灯会自动关闭。"
);
assert.match(buildDispenseFailureSpeech("未识别到指纹"), /未识别到指纹/);

console.log("dispense speech contract: ok");
