import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const sourceRoot = `${frontendRoot}src`;
const allowedDrawFiles = new Set([
  "components/BottomNav.jsx",
  "components/InquiryChatStep.jsx",
  "components/TopBar.jsx",
  "pages/IdleScreen.jsx",
  "pages/Scan.jsx",
  "pages/Vitals.jsx"
]);

async function listFiles(directory, prefix = "") {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      files.push(...(await listFiles(`${directory}/${entry.name}`, relativePath)));
    } else {
      files.push(relativePath);
    }
  }
  return files;
}

const sourceFiles = (await listFiles(sourceRoot)).filter((file) => /\.(jsx|js|css)$/.test(file));
const drawUsers = [];

for (const file of sourceFiles) {
  const content = await readFile(`${sourceRoot}/${file}`, "utf8");
  assert.doesNotMatch(content, /MotionIcon|lottie-web/, `${file} still uses the removed Lottie system`);
  if (file !== "components/StrokeDrawIcon.jsx" && content.includes("StrokeDrawIcon")) {
    drawUsers.push(file);
    assert.ok(allowedDrawFiles.has(file), `${file} is not approved for selective motion`);
  }
}

assert.deepEqual(new Set(drawUsers), allowedDrawFiles, "selective motion file list changed");

const component = await readFile(`${sourceRoot}/components/StrokeDrawIcon.jsx`, "utf8");
assert.match(component, /setComplete\(true\)/, "drawn icon never returns to the static state");
assert.match(component, /pathLength/, "draw animation is not normalized to the original Lucide geometry");
assert.match(component, /direction:\s*mode === "yoyo" \? "alternate"/, "yoyo animation does not reverse from its completed state");
assert.match(component, /iterations:\s*mode === "yoyo" \? Infinity/, "active measurement animation does not keep running");
assert.match(component, /!active/, "state-driven animation cannot stop when the task completes");
assert.match(component, /DRAW_PHASE_MS\s*=\s*1600/, "draw animations do not share the 1.6 second phase");
assert.match(component, /duration:\s*DRAW_PHASE_MS/, "yoyo animations do not share one cycle source");
assert.match(component, /replayOnPointer/, "drawn icons cannot opt into pointer-triggered replay");
assert.match(component, /document\.addEventListener\("pointerdown"/, "screen interaction does not replay the logo");
assert.match(component, /event\.isPrimary === false/, "secondary pointer events can replay the logo");

const topBar = await readFile(`${sourceRoot}/components/TopBar.jsx`, "utf8");
assert.match(topBar, /<StrokeDrawIcon[^>]*replayOnPointer/, "brand logo does not replay after a screen touch");

const bottomNav = await readFile(`${sourceRoot}/components/BottomNav.jsx`, "utf8");
assert.match(bottomNav, /mode="once"/, "bottom navigation icon motion is not single-shot");
assert.match(bottomNav, /token:\s*current\.token \+ 1/, "repeated taps cannot replay bottom navigation motion");

for (const file of allowedDrawFiles) {
  const content = await readFile(`${sourceRoot}/${file}`, "utf8");
  assert.doesNotMatch(content, /<StrokeDrawIcon[^>]*(?:duration|stagger|hold)=/, `${file} overrides the shared timing`);
}

const styles = await readFile(`${sourceRoot}/styles/stroke-draw.css`, "utf8");
assert.match(styles, /stroke-dashoffset:\s*0/, "draw animation does not finish on the complete icon");
assert.match(styles, /prefers-reduced-motion:\s*reduce/, "reduced motion fallback is missing");

const appStyles = await readFile(`${sourceRoot}/styles/app.css`, "utf8");
assert.match(appStyles, /--motion-phase-duration:\s*1600ms/, "CSS motion phase is not synchronized");
assert.match(appStyles, /--motion-cycle-duration:\s*3200ms/, "CSS motion cycle is not synchronized");
assert.match(appStyles, /\.vitals-measure-progress/, "vitals progress feedback is missing");
assert.match(appStyles, /transform-origin:\s*left center/, "vitals progress does not advance from left to right");
assert.doesNotMatch(appStyles, /vitals-heart-pulses/, "vitals page renders more than one loading signal");
assert.doesNotMatch(appStyles, /vitals-loader-(?:rotate|arc)/, "legacy rotating vitals loader is still present");

const packageJson = JSON.parse(await readFile(`${frontendRoot}package.json`, "utf8"));
assert.equal(packageJson.dependencies?.["lottie-web"], undefined, "lottie-web should not be bundled");

console.log(`Selective motion contract: ${drawUsers.length} approved surfaces, all other icons static`);
