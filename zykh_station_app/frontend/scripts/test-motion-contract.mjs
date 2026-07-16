import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const sourceRoot = `${frontendRoot}src`;
const allowedDrawFiles = new Set([
  "components/BottomNav.jsx",
  "components/DispenseConfirmModal.jsx",
  "components/InquiryChatStep.jsx",
  "components/InquiryIdentityGate.jsx",
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
assert.match(component, /DRAW_CYCLE_MS\s*=\s*DRAW_PHASE_MS \* 2/, "standard loop cycle does not contain matching draw and erase phases");
assert.match(component, /IDLE_DRAW_CYCLE_MS\s*=\s*IDLE_DRAW_PHASE_MS \* 2/, "idle loop cycle does not contain matching draw and erase phases");
assert.match(component, /strokeDashoffset:\s*-1/, "loop animation does not erase forward along the path");
assert.match(component, /direction:\s*"normal"/, "loop animation still reverses its timeline");
assert.match(component, /iterations:\s*mode === "yoyo" \? Infinity/, "active measurement animation does not keep running");
assert.match(component, /!active/, "state-driven animation cannot stop when the task completes");
assert.match(component, /DRAW_PHASE_MS\s*=\s*1600/, "normal draw animations did not return to the 1.6 second phase");
assert.match(component, /IDLE_DRAW_PHASE_MS\s*=\s*2500/, "idle draw animation does not keep the slower 2.5 second phase");
assert.match(component, /easing:\s*"linear"/, "draw and erase paths do not move at a linear speed");
assert.match(component, /duration:\s*mode === "yoyo" \? cycleDuration : phaseDuration/, "loop animations do not use their selected full cycle");
assert.match(component, /pace = "standard"/, "drawn icons do not default to the normal speed");
assert.match(component, /replayOnPointer/, "drawn icons cannot opt into pointer-triggered replay");
assert.match(component, /document\.addEventListener\("pointerdown"/, "screen interaction does not replay the logo");
assert.match(component, /event\.isPrimary === false/, "secondary pointer events can replay the logo");

const topBar = await readFile(`${sourceRoot}/components/TopBar.jsx`, "utf8");
assert.match(topBar, /<BrandLogoImage/, "brand logo does not use the supplied static image");
assert.doesNotMatch(topBar, /StrokeDrawIcon/, "top bar brand logo should stay static");

const idleScreen = await readFile(`${sourceRoot}/pages/IdleScreen.jsx`, "utf8");
assert.match(idleScreen, /icon=\{HeartHandshake\}/, "idle screen does not use the original simple heart-handshake glyph");
assert.match(idleScreen, /pace="idle"/, "idle screen icon does not use the slower isolated pace");
assert.doesNotMatch(idleScreen, /HandwrittenHello|<HandwrittenHello/, "idle screen still renders the Hello animation");

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
assert.match(appStyles, /--motion-phase-duration:\s*1600ms/, "normal CSS motion phase did not return to 1.6 seconds");
assert.match(appStyles, /--motion-cycle-duration:\s*3200ms/, "normal CSS motion cycle did not return to 3.2 seconds");
assert.match(appStyles, /idle-wake-prompt[\s\S]*4200ms/, "idle wake prompt does not gently fade");
assert.match(appStyles, /::view-transition-new\(kiosk-page\)/, "page transition feedback is missing");
assert.match(appStyles, /button:not\(:disabled\):active[\s\S]*scale:\s*0\.97/, "touch press feedback is missing");
assert.match(appStyles, /prefers-reduced-motion:\s*reduce[\s\S]*::view-transition-old\(\*\)/, "view transitions ignore reduced motion");
assert.match(appStyles, /\.vitals-measure-progress/, "vitals progress feedback is missing");
assert.match(appStyles, /transform-origin:\s*left center/, "vitals progress does not advance from left to right");
assert.doesNotMatch(appStyles, /vitals-heart-pulses/, "vitals page renders more than one loading signal");
assert.doesNotMatch(appStyles, /vitals-loader-(?:rotate|arc)/, "legacy rotating vitals loader is still present");

const app = await readFile(`${sourceRoot}/App.jsx`, "utf8");
assert.match(app, /document\.startViewTransition/, "same-document page transitions are not enabled");
assert.match(app, /flushSync\(update\)/, "React page updates are not committed inside the view transition callback");
assert.doesNotMatch(app, /loadDashboard\(identity|__unconfirmed__/, "home dashboard still depends on a confirmed identity");
const wakeHandler = app.match(/function handleWake\(\) \{([\s\S]*?)\n  \}/)?.[1] || "";
assert.ok(wakeHandler, "home wake handler is missing");
assert.doesNotMatch(wakeHandler, /identify|capture|verify/, "waking the home screen still triggers identity recognition");
assert.match(wakeHandler, /clearIdentity\(\)/, "waking the home screen does not reset the prior user session");

const home = await readFile(`${sourceRoot}/components/MedicationSummaryCard.jsx`, "utf8");
assert.match(home, /PLAN_ROTATION_MS\s*=\s*4500/, "home medication plans do not rotate every few seconds");
assert.match(home, /next-dose-track/, "home medication plans do not use a scrolling track");
assert.doesNotMatch(home, /home-current-user|ScanFace/, "home medication summary still exposes identity confirmation");

const medicines = await readFile(`${sourceRoot}/pages/Medicines.jsx`, "utf8");
assert.doesNotMatch(medicines, /useFaceIdentity/, "opening the medicines page still starts identity recognition");

const dispenseModal = await readFile(`${sourceRoot}/components/DispenseConfirmModal.jsx`, "utf8");
assert.match(dispenseModal, /identifyFingerprint/, "dispense confirmation is missing fingerprint verification");
assert.match(dispenseModal, /verifyDispenseIdentity/, "dispense confirmation is missing face verification");
assert.match(dispenseModal, /setPhase\("recognized"\)/, "recognized users are not shown before cabinet opening");
assert.match(dispenseModal, /phase === "recognized" \? confirmAndOpen : verifyIdentity/, "dispense does not require an explicit post-recognition confirmation");
assert.match(dispenseModal, /sessionRef\.current/, "closing the modal cannot cancel a delayed cabinet action");
assert.doesNotMatch(dispenseModal, /safety-confirmed|confirm-check/, "legacy duplicate safety checkbox is still rendered");

const inquiry = await readFile(`${sourceRoot}/pages/Inquiry.jsx`, "utf8");
assert.match(inquiry, /<InquiryIdentityGate/, "inquiry does not stop for visible identity confirmation");
assert.match(inquiry, /setIdentityConfirmed\(true\)/, "inquiry identity cannot be explicitly confirmed");
assert.match(inquiry, /activateOnMatch: false/, "inquiry face match is activated before the user confirms it");

const packageJson = JSON.parse(await readFile(`${frontendRoot}package.json`, "utf8"));
assert.equal(packageJson.dependencies?.["lottie-web"], undefined, "lottie-web should not be bundled");

console.log(`Selective motion contract: ${drawUsers.length} approved surfaces, all other icons static`);
