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
  "styles/touch-keyboard.css",
  "styles/adaptive-layout.css"
];
const styles = (await Promise.all(
  styleFiles.map((path) => readFile(`${root}src/${path}`, "utf8"))
)).join("\n");
const idleScreen = await readFile(`${root}src/pages/IdleScreen.jsx`, "utf8");
const launcher = await readFile(`${root}../scripts/launch_kiosk.sh`, "utf8");
const pinyinLoader = await readFile(`${root}src/utils/pinyinIme.js`, "utf8");
const appSource = await readFile(`${root}src/App.jsx`, "utf8");
const motionStyles = await readFile(`${root}src/styles/motion-system.css`, "utf8");

assert.doesNotMatch(
  styles,
  /(?:-webkit-)?backdrop-filter\s*:/,
  "full-screen kiosk overlays must not use live backdrop filters"
);

const pageCache = styles.match(/\.page-cache\s*\{([^}]*)\}/)?.[1] || "";
assert.doesNotMatch(pageCache, /will-change/, "hidden full-page caches keep a permanent compositor layer");
assert.match(
  styles,
  /\.page-cache\.inactive\s*\{[^}]*display:\s*none/,
  "inactive cached pages still participate in layout and paint"
);
assert.doesNotMatch(appSource, /startTransition/, "navigation is still scheduled as a low-priority update");
assert.doesNotMatch(
  motionStyles,
  /html\[data-page-transition\]\s+\.top-bar\s*\{[^}]*animation/,
  "navigation animates the full top bar surface"
);
assert.match(
  motionStyles,
  /\.inquiry-assistant-orbit,[\s\S]*\.inquiry-voice-wave i,[\s\S]*\.quick-action-cta\.vitals-cta::after\s*\{[^}]*animation:\s*none/,
  "home decorative animations still compete for frames"
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
  /command -v onboard|onboard --size|screen-keyboard-enabled/,
  "the kiosk launcher must not depend on a legacy or incompatible desktop keyboard"
);
assert.match(
  launcher,
  /KIOSK_APP_URL=.*touchKeyboard=0/,
  "the kiosk launcher cannot disable the app keyboard when explicitly requested"
);
assert.doesNotMatch(
  launcher,
  /TouchVirtualKeyboard/,
  "the kiosk still requests the incompatible Chromium desktop keyboard bridge"
);
assert.match(
  await readFile(`${root}src/App.jsx`, "utf8"),
  /<TouchKeyboard enabled=\{touchKeyboardEnabled\}/,
  "the kiosk shell does not render its reliable app keyboard fallback"
);
assert.match(
  pinyinLoader,
  /import\("pinyin-ime\/dictionary\/google_pinyin_dict"\)/,
  "the large offline pinyin dictionary must remain lazy-loaded"
);
assert.doesNotMatch(
  pinyinLoader,
  /^import\s+.*pinyin-ime/m,
  "the pinyin engine must not increase initial kiosk bundle work"
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
