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

console.log("render performance contract: ok");
