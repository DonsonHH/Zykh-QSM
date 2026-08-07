import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { speakerGainToPercent, speakerPercentToGain } from "../src/utils/volume.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const settingsPage = await readFile(`${root}src/pages/Settings.jsx`, "utf8");

assert.equal(speakerGainToPercent(0), 0);
assert.equal(speakerGainToPercent(255), 100);
assert.equal(speakerPercentToGain(0), 0);
assert.equal(speakerPercentToGain(100), 255);
assert.ok(speakerPercentToGain(50) < 20, "50% should use the 20log curve, not a linear raw gain");
assert.ok(Math.abs(speakerGainToPercent(speakerPercentToGain(75)) - 75) <= 1);
assert.match(settingsPage, /playBeep/, "speaker test must use the direct hardware beep path");
assert.doesNotMatch(settingsPage, /value=\{values\.speaker_volume\}/, "raw speaker gain is still shown to users");

console.log("speaker volume contract: ok");
