import assert from "node:assert/strict";
import { medicationPlanTimeLabel, orderMedicationPlans } from "../src/utils/medicationPlans.js";

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

console.log("home medication plan ordering: ok");
