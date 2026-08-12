import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = fileURLToPath(new URL("../", import.meta.url));
const vitals = await readFile(`${root}src/pages/Vitals.jsx`, "utf8");
const vite = await createServer({
  root,
  logLevel: "silent",
  server: { middlewareMode: true },
  appType: "custom"
});

try {
  const sessionModule = await vite.ssrLoadModule("/src/modules/vitalsSession.js");
  assert.deepEqual(
    sessionModule.vitalsTemperaturePresentation({
      temperature: 36.42,
      body_temperature: 36.42,
      temperature_source: "uart8_fingertip_reference"
    }),
    { label: "指温参考", showSeparateFingerTemperature: false },
    "a fingertip fallback must not be presented as a forehead-temperature reading"
  );
  assert.equal(
    typeof sessionModule.shouldAutomaticallyRetrySpo2,
    "undefined",
    "terminal sensor results must not trigger a second measurement"
  );
} finally {
  await vite.close();
}

assert.doesNotMatch(
  vitals,
  /shouldAutomaticallyRetryNoFinger/,
  "a no-finger result must remain visible instead of rapidly restarting the sensor"
);
const sessionSource = await readFile(`${root}src/modules/vitalsSession.js`, "utf8");
assert.doesNotMatch(
  sessionSource,
  /automaticRetry/,
  "the removed automatic remeasurement state must not return"
);
assert.doesNotMatch(
  vitals,
  /lastNoFingerRetrySessionRef/,
  "the removed continuous no-finger retry state must not return"
);
assert.doesNotMatch(vitals, /上次测量结果/, "the kiosk must present demo fallback through the normal result UI");
assert.doesNotMatch(
  vitals,
  /已调取最近一次完整记录/,
  "the kiosk must not expose the internal historical fallback message"
);

console.log("vitals retry policy contract: ok");
