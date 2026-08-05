import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { millisecondsUntilNextMinute } from "../src/hooks/useMinuteClock.js";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const app = await readFile(`${frontendRoot}src/App.jsx`, "utf8");
const topBar = await readFile(`${frontendRoot}src/components/TopBar.jsx`, "utf8");
const idleScreen = await readFile(`${frontendRoot}src/pages/IdleScreen.jsx`, "utf8");

assert.equal(
  millisecondsUntilNextMinute(new Date("2026-08-05T15:21:12.345Z")),
  47_675,
  "clock refresh is not aligned just after the next minute boundary"
);
assert.doesNotMatch(app, /setNow|now=\{now\}/, "the app shell still rerenders every page for clock updates");
assert.match(app, /startTransition\(applyNavigation\)/, "page navigation is not scheduled as interruptible rendering work");
assert.match(topBar, /useMinuteClock\(\)/, "the top bar does not own its minute-level clock refresh");
assert.match(idleScreen, /useMinuteClock\(\)/, "the idle screen does not own its minute-level clock refresh");

console.log("render ownership boundaries: ok");
