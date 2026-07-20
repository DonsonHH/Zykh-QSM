import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const vitals = await readFile(`${root}src/pages/Vitals.jsx`, "utf8");
const calls = vitals.match(/prepareQsmVitals\(\)/g) || [];

assert.equal(calls.length, 1, "Vitals must use one single-flight prepare call instead of restarting UART preheat");
assert.match(vitals, /ensureVitalsPrepared/, "Vitals must reuse the in-flight preheat request");

console.log("vitals prewarm contract: ok");
