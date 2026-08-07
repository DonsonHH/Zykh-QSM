import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { normalizeSpeakerGain, speakerGainToPercent, speakerPercentToGain } from "../src/utils/volume.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const settingsPage = await readFile(`${root}src/pages/Settings.jsx`, "utf8");

assert.equal(speakerGainToPercent(0), 0);
assert.equal(speakerGainToPercent(255), 100);
assert.equal(speakerPercentToGain(0), 0);
assert.equal(speakerPercentToGain(100), 255);
assert.equal(speakerPercentToGain(1), 128, "the first audible step must start at the board's effective gain floor");
assert.equal(speakerGainToPercent(128), 1, "the board's effective gain floor must be shown as the first audible step");
assert.equal(normalizeSpeakerGain(0), 0);
assert.equal(normalizeSpeakerGain(1), 128, "legacy inaudible gains must migrate to the calibrated floor");
assert.equal(normalizeSpeakerGain(127), 128, "legacy inaudible gains must not survive settings hydration");
assert.equal(normalizeSpeakerGain(230), 230);
assert.ok(
  speakerPercentToGain(50) >= 178 && speakerPercentToGain(50) <= 183,
  "50% should sit near the logarithmic midpoint of the board's effective 128-255 gain range"
);
assert.equal(speakerGainToPercent(230), 85, "the persisted default gain should use the calibrated display scale");
let previousGain = 0;
const calibratedGains = [];
for (let percent = 1; percent <= 100; percent += 1) {
  const gain = speakerPercentToGain(percent);
  assert.ok(gain >= previousGain, `speaker gain decreases at ${percent}%`);
  calibratedGains.push(gain);
  previousGain = gain;
}
assert.ok(new Set(calibratedGains).size >= 98, "too much of the visible slider is collapsed onto duplicate gains");
for (const percent of [1, 10, 25, 50, 75, 90, 100]) {
  assert.ok(
    Math.abs(speakerGainToPercent(speakerPercentToGain(percent)) - percent) <= 1,
    `${percent}% does not survive a calibrated gain round trip`
  );
}
assert.match(settingsPage, /playBeep\(speakerPercentToGain\(speakerPercent\)\)/, "speaker test must use the calibrated hardware gain");
assert.match(
  settingsPage,
  /speaker_volume:\s*normalizeSpeakerGain\(initialServerValuesRef\.current\.speaker_volume\)/,
  "legacy persisted speaker gain is not normalized during settings hydration"
);
assert.match(settingsPage, /speakerPercent === 0[\s\S]*当前为静音/, "speaker test can still trigger the board while muted");
assert.doesNotMatch(settingsPage, /value=\{values\.speaker_volume\}/, "raw speaker gain is still shown to users");

console.log("speaker volume contract: ok");
