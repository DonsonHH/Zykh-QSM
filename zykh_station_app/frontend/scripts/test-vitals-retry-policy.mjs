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
    sessionModule.shouldAutomaticallyRetrySpo2({
      status: "failed",
      heart_rate: 74,
      temperature: 36.6,
      spo2: null
    }),
    true,
    "a real heart-rate and temperature result may retry missing SpO2 once"
  );
  assert.equal(
    sessionModule.shouldAutomaticallyRetrySpo2({
      status: "failed",
      heart_rate: null,
      temperature: 36.6,
      spo2: null,
      failure_reason: "no_finger"
    }),
    false,
    "a no-finger result must remain visible instead of restarting the sensor"
  );
} finally {
  await vite.close();
}

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
assert.doesNotMatch(vitals, /上次测量结果/, "the kiosk must present demo fallback through the normal result UI");
assert.doesNotMatch(
  vitals,
  /已调取最近一次完整记录/,
  "the kiosk must not expose the internal historical fallback message"
);

console.log("vitals retry policy contract: ok");
