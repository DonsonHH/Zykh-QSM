import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const vitals = await readFile(`${root}src/pages/Vitals.jsx`, "utf8");
const vitalsSession = await readFile(`${root}src/modules/vitalsSession.js`, "utf8");
const calls = vitalsSession.match(/prepareQsmVitals\(\)/g) || [];

assert.equal(calls.length, 1, "Vitals must use one single-flight prepare call instead of restarting UART preheat");
assert.match(vitalsSession, /ensurePrepared/, "Vitals session module must reuse the in-flight preheat request");
assert.match(vitals, /useVitalsSession/, "Vitals page must delegate preheat ownership to the session module");
assert.doesNotMatch(vitals, /prepareQsmVitals/, "Vitals page must not own UART preheat calls");

console.log("vitals prewarm contract: ok");
