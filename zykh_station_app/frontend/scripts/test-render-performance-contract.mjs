import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const styleFiles = [
  "styles/app.css",
  "styles/settings.css",
  "styles/admin.css",
  "styles/design-polish.css",
  "styles/motion-system.css",
  "styles/adaptive-layout.css"
];
const styles = (await Promise.all(
  styleFiles.map((path) => readFile(`${root}src/${path}`, "utf8"))
)).join("\n");
const idleScreen = await readFile(`${root}src/pages/IdleScreen.jsx`, "utf8");
const launcher = await readFile(`${root}../scripts/launch_kiosk.sh`, "utf8");

assert.doesNotMatch(
  styles,
  /(?:-webkit-)?backdrop-filter\s*:/,
  "full-screen kiosk overlays must not use live backdrop filters"
);

const idleSurface = styles.match(/\.idle-screen\s*\{([^}]*)\}/)?.[1] || "";
assert.doesNotMatch(
  idleSurface,
  /animation\s*:/,
  "the full idle-screen surface must not repaint continuously"
);
assert.doesNotMatch(
  idleScreen,
  /mode="yoyo"|pace="idle"/,
  "the idle screen must not run an infinite programmatic SVG stroke animation"
);

for (const selector of [".idle-wake-area h1", ".idle-reminder-icon"]) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const block = styles.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))?.[1] || "";
  assert.doesNotMatch(
    block,
    /animation\s*:[^;]*infinite/,
    `${selector} must not keep the idle compositor active indefinitely`
  );
}

assert.doesNotMatch(
  launcher,
  /command -v onboard|onboard --size/,
  "the kiosk launcher must not start the legacy Onboard keyboard"
);
assert.match(
  launcher,
  /org\.gnome\.desktop\.a11y\.applications screen-keyboard-enabled true/,
  "the kiosk launcher does not enable the current GNOME screen keyboard"
);
assert.match(
  launcher,
  /--enable-features=TouchVirtualKeyboard/,
  "Chromium touch-keyboard integration is missing"
);

const finiteIdleMotion = [...styles.matchAll(/\.idle-wake-button\s*\{([^}]*)\}/g)]
  .map((match) => match[1])
  .join("\n");
assert.match(
  finiteIdleMotion,
  /animation\s*:\s*idle-wake-enter[^;]*both/,
  "the idle wake control has no finite entry feedback"
);
assert.doesNotMatch(
  finiteIdleMotion,
  /infinite/,
  "the idle wake control must settle after its entry feedback"
);
assert.match(
  styles,
  /@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*\.idle-wake-button[\s\S]*animation:\s*none\s*!important/,
  "idle entry feedback ignores reduced-motion preference"
);

console.log("render performance contract: ok");
