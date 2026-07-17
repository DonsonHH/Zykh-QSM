import assert from "node:assert/strict";
import {
  isMedicationPlanCompleted,
  medicationPlanDayLabel,
  medicationPlanTimeLabel,
  orderMedicationPlans,
  orderMedicationTaskPickerPlans
} from "../src/utils/medicationPlans.js";

const plans = [
  { id: "later", time: "16:00" },
  { id: "meal", timing_label: "饭后", time: "12:30" },
  { id: "past-near", time: "09:50" },
  { id: "future-near", time: "10:20" },
  { id: "unrestricted", schedule_label: "不限时", time: "" }
];

const ordered = orderMedicationPlans(plans, new Date("2026-07-17T10:00:00"));
assert.deepEqual(ordered.map((plan) => plan.id), ["past-near", "future-near", "meal", "later", "unrestricted"]);
assert.equal(medicationPlanTimeLabel(plans[1]), "12:30");
assert.equal(medicationPlanTimeLabel({ timing_label: "饭后", time: "" }), "饭后");
assert.equal(medicationPlanTimeLabel(plans[4]), "不限时");
assert.equal(medicationPlanTimeLabel({}), "不限时");

const taskRows = [
  { id: "tomorrow", time: "08:30", next_due_date: "2026-07-18", status: "待执行" },
  { id: "completed", time: "07:00", next_due_date: "2026-07-17", status: "已执行" },
  { id: "today-late", time: "21:00", next_due_date: "2026-07-17", status: "待执行" },
  { id: "today-early", time: "09:00", next_due_date: "2026-07-17", status: "待执行" }
];
const orderedTasks = orderMedicationTaskPickerPlans(taskRows, new Date("2026-07-17T18:00:00"));
assert.deepEqual(orderedTasks.map((plan) => plan.id), ["today-early", "today-late", "tomorrow", "completed"]);
assert.equal(medicationPlanDayLabel(taskRows[0], new Date("2026-07-17T18:00:00")), "次日");
assert.equal(medicationPlanTimeLabel(taskRows[0], new Date("2026-07-17T18:00:00")), "次日 08:30");
assert.equal(isMedicationPlanCompleted(taskRows[1]), true);
assert.equal(isMedicationPlanCompleted(taskRows[2]), false);

console.log("home medication plan ordering: ok");
