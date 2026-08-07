import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const settingsPage = await readFile(`${root}src/pages/Settings.jsx`, "utf8");
const settingsStyles = await readFile(`${root}src/styles/settings.css`, "utf8");
const designPolish = await readFile(`${root}src/styles/design-polish.css`, "utf8");

assert.match(settingsPage, /className=\{`settings-card-grid/, "settings do not expose a clear card workspace");
assert.match(settingsPage, /className="settings-mode-card/, "network mode has no primary settings card");
assert.equal(
  [...settingsPage.matchAll(/className="settings-preference-card/g)].length,
  2,
  "sound and display must be separate preference cards"
);
assert.match(settingsPage, /className="settings-section-body sound-section-body/, "sound controls have no consistent card body");
assert.match(settingsPage, /className="settings-section-body display-section-body/, "display controls have no consistent card body");
assert.doesNotMatch(settingsPage, /basic-settings-panel/, "settings still render three equal competing panels");
assert.match(settingsPage, /const controlsLocked = loading;/, "autosave still freezes every settings control");
assert.match(
  settingsPage,
  /window\.dispatchEvent\([\s\S]*?if \(!mountedRef\.current\) return;/,
  "a completed background save does not refresh the shared settings snapshot"
);
assert.doesNotMatch(
  settingsPage,
  /仅改变|不会切换|小程序|语音路径|AI 问询/,
  "demo-breaking implementation notes leaked into the settings interface"
);

assert.match(
  settingsStyles,
  /\.settings-card-grid\s*\{[\s\S]*grid-template-columns:\s*minmax\([^;]+\)\s+minmax\([^;]+\);[\s\S]*grid-template-rows:/,
  "settings workspace does not expose the two-column card hierarchy"
);
assert.match(
  settingsStyles,
  /\.network-panel\s*\{[\s\S]*grid-row:\s*1\s*\/\s*-1/,
  "the primary network card does not span the settings workspace"
);
assert.match(
  designPolish,
  /\.settings-mode-card,[\s\S]*\.settings-preference-card,[\s\S]*border-color:\s*var\(--border-strong\)/,
  "settings cards are not part of the shared kiosk surface system"
);

console.log("settings layout contract: ok");
