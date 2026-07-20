import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const vitals = await readFile(`${root}src/pages/Vitals.jsx`, "utf8");

assert.doesNotMatch(
  vitals,
  /shouldAutomaticallyRetryNoFinger/,
  "a no-finger result must remain visible instead of rapidly restarting the sensor"
);
assert.doesNotMatch(
  vitals,
  /lastNoFingerRetrySessionRef/,
  "the removed continuous no-finger retry state must not return"
);
assert.match(
  vitals,
  /shouldAutomaticallyRetrySpo2\(data\) && !automaticRetryRef\.current/,
  "the existing one-shot retry for a real heart-rate reading with missing SpO2 must remain"
);

console.log("vitals retry policy contract: ok");
