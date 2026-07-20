import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const vitals = await readFile(`${root}src/pages/Vitals.jsx`, "utf8");

assert.match(
  vitals,
  /function shouldAutomaticallyRetryNoFinger\(result\)/,
  "Vitals must distinguish a completed no-finger attempt from other hardware failures"
);
assert.match(
  vitals,
  /result\?\.finger_detected === false/,
  "no-finger retry must require an explicit missing-finger signal"
);
assert.match(
  vitals,
  /result\?\.hardware_started !== false/,
  "no-finger retry must not loop when the sensor did not start"
);
assert.match(
  vitals,
  /lastNoFingerRetrySessionRef/,
  "the same terminal session must not schedule duplicate retries"
);
assert.match(
  vitals,
  /shouldAutomaticallyRetryNoFinger\(data\)[\s\S]{0,500}handleMeasure\(\{ automatic: true \}\)/,
  "a failed no-finger attempt must automatically begin the next measurement"
);
assert.match(
  vitals,
  /shouldAutomaticallyRetrySpo2\(data\)/,
  "the existing missing-SpO2 fallback retry must remain intact"
);

console.log("vitals no-finger retry contract: ok");
