import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { normalizeSpeakerGain, speakerGainToPercent, speakerPercentToGain } from "../src/utils/volume.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const settingsPage = await readFile(`${root}src/pages/Settings.jsx`, "utf8");
const systemCheck = await readFile(`${root}src/components/SystemCheckModal.jsx`, "utf8");
const relayScript = await readFile(`${root}../scripts/relay_host_audio_to_qsm.sh`, "utf8");
const qsmClient = await readFile(`${root}../backend/app/services/qsm_client.py`, "utf8");

assert.equal(speakerGainToPercent(0), 0);
assert.equal(speakerGainToPercent(255), 100);
assert.equal(speakerPercentToGain(0), 0);
assert.equal(speakerPercentToGain(100), 255);
assert.equal(speakerPercentToGain(1), 128, "the first audible step must start at the board's effective gain floor");
assert.equal(speakerGainToPercent(128), 1, "the board's effective gain floor must be shown as the first audible step");
assert.equal(normalizeSpeakerGain(0), 0);
assert.equal(normalizeSpeakerGain(1), 146, "legacy 20% intent must migrate onto the audible scale");
assert.equal(normalizeSpeakerGain(8), 180, "legacy 50% intent must migrate onto the audible scale");
assert.equal(normalizeSpeakerGain(45), 214, "legacy 75% intent must migrate onto the audible scale");
assert.equal(normalizeSpeakerGain(127), 238, "legacy 90% intent must migrate onto the audible scale");
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
assert.match(
  systemCheck,
  /nextAudio\?\.speaker_volume[\s\S]*setVolumePercent\(speakerGainToPercent\(nextAudio\.speaker_volume\)\)/,
  "device check does not hydrate its volume control from the saved setting"
);
assert.match(
  relayScript,
  /\/api\/audio\/host\/speaker-volume[\s\S]*pactl set-sink-volume "\$SINK_NAME" "\$\{saved_percent\}%"/,
  "audio relay startup does not restore the saved calibrated volume"
);
assert.match(
  qsmClient,
  /def audio_beep[\s\S]*volume is not None and int\(volume\) <= 0[\s\S]*"muted": True/,
  "a zero-volume beep can still fall through to the legacy board default"
);

console.log("speaker volume contract: ok");
