import assert from "node:assert/strict";
import { getMedicationReminder, getMedicationReminders } from "../src/utils/medicationReminder.js";

const medication = {
  plans: [
    { id: "p1", time: "08:00", status: "待执行", target_user: "张三", medicine: "苯磺酸氨氯地平片" },
    { id: "p2", time: "09:00", status: "已执行", target_user: "李四", medicine: "多维元素片" }
  ]
};

assert.equal(getMedicationReminder(medication, new Date("2026-07-16T06:59:00")), null);
assert.equal(getMedicationReminder(medication, new Date("2026-07-16T07:00:00")).state, "soon");
assert.equal(getMedicationReminder(medication, new Date("2026-07-16T07:50:00")).state, "soon");
assert.equal(getMedicationReminder(medication, new Date("2026-07-16T08:00:00")).state, "now");
assert.equal(getMedicationReminder(medication, new Date("2026-07-16T08:30:00")).state, "overdue");
assert.equal(getMedicationReminder(medication, new Date("2026-07-16T09:00:00")).state, "overdue");
assert.equal(getMedicationReminder(medication, new Date("2026-07-16T09:01:00")), null);

const nearbyMedication = {
  plans: [
    { id: "a", time: "08:00", status: "待执行", target_user: "张三", medicine: "药品A" },
    { id: "b", time: "08:20", status: "待执行", target_user: "李四", medicine: "药品B" },
    { id: "c", time: "10:00", status: "待执行", target_user: "王五", medicine: "药品C" }
  ]
};
assert.deepEqual(
  getMedicationReminders(nearbyMedication, new Date("2026-07-16T08:10:00")).map(({ plan }) => plan.id),
  ["a", "b"]
);
assert.deepEqual(
  getMedicationReminders(nearbyMedication, new Date("2026-07-16T09:20:00")).map(({ plan }) => plan.id),
  ["c"]
);

console.log("medication reminder contract: ok");
