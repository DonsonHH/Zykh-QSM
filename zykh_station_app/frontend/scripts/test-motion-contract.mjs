import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const sourceRoot = `${frontendRoot}src`;
const allowedDrawFiles = new Set([
  "components/DispenseConfirmModal.jsx",
  "components/InquiryChatStep.jsx",
  "components/InquiryEntryCard.jsx",
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
assert.doesNotMatch(bottomNav, /StrokeDrawIcon|useState/, "frequent bottom navigation actions should use stable static icons");
assert.match(bottomNav, /<Icon size=\{27\} strokeWidth=\{2\.1\}/, "bottom navigation lost its consistent icon geometry");

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

const vitalsPage = await readFile(`${sourceRoot}/pages/Vitals.jsx`, "utf8");
assert.match(vitalsPage, /vitals-back-button/, "vitals page is missing its top-left back button");
assert.match(appStyles, /\.vitals-back-button[\s\S]*width:\s*56px[\s\S]*height:\s*56px/, "vitals back button is too small for touch use");
const vitalsEffects = [...vitalsPage.matchAll(/useEffect\(\(\) => \{([\s\S]*?)\n  \}, \[[^\]]*\]\);/g)];
assert.equal(
  vitalsEffects.some((match) => match[1].includes("startVitalsSession()")),
  false,
  "vitals hardware starts before the user presses the measurement button"
);
assert.match(
  vitalsPage,
  /function handleMeasure\(\)[\s\S]*startVitalsSession\(\)[\s\S]*data\.hardware_started[\s\S]*setSessionId\(data\.session_id\)/,
  "the first measurement click does not start a hardware-confirmed QSM session"
);
assert.match(vitalsPage, /loadVitalsSession\(sessionId\)/, "vitals page does not poll the active QSM session");
assert.match(vitalsPage, /cancelVitalsSession\(currentSession\)/, "vitals page cannot cancel the active QSM session");

const app = await readFile(`${sourceRoot}/App.jsx`, "utf8");
assert.match(app, /document\.startViewTransition/, "same-document page transitions are not enabled");
assert.match(app, /flushSync\(update\)/, "React page updates are not committed inside the view transition callback");
assert.doesNotMatch(app, /loadDashboard\(identity|__unconfirmed__/, "home dashboard still depends on a confirmed identity");
const wakeHandler = app.match(/function handleWake\(\) \{([\s\S]*?)\n  \}/)?.[1] || "";
assert.ok(wakeHandler, "home wake handler is missing");
assert.doesNotMatch(wakeHandler, /identify|capture|verify/, "waking the home screen still triggers identity recognition");
assert.doesNotMatch(wakeHandler, /clearIdentity\(\)/, "waking the home screen still changes identity state");
assert.match(app, /commitViewChange\("sleep"[\s\S]*?clearIdentity\(\)/, "entering idle mode no longer clears the prior user session");
assert.match(app, /commitViewChange\("sleep"[\s\S]*?clearInquirySession\(\)[\s\S]*?clearIdentity\(\)/, "entering idle mode does not reset the inquiry identity flow");

const entry = await readFile(`${sourceRoot}/main.jsx`, "utf8");
assert.match(entry, /design-polish\.css[\s\S]*motion-system\.css/, "design and motion polish layers are missing or loaded in the wrong order");

const designPolish = await readFile(`${sourceRoot}/styles/design-polish.css`, "utf8");
assert.match(designPolish, /--surface-shadow:[\s\S]*0 0 0 1px var\(--surface-edge\)/, "primary surfaces lost their shadow hairline");
assert.match(designPolish, /--surface-shadow-item:/, "repeated rows do not have a quiet elevation level");
assert.match(designPolish, /\.card,[\s\S]*border:\s*1px solid transparent;[\s\S]*box-shadow:\s*var\(--surface-shadow\)/, "primary surfaces still combine a gray border with elevation shadow");
assert.match(designPolish, /focus-visible[\s\S]*outline:\s*3px solid var\(--focus-ring\)/, "polished controls have no visible focus treatment");

const motionSystem = await readFile(`${sourceRoot}/styles/motion-system.css`, "utf8");
assert.match(motionSystem, /--motion-control:\s*180ms/, "control feedback no longer shares the standard motion token");
assert.match(motionSystem, /\.inquiry-assistant-orbit[\s\S]*animation-iteration-count:\s*2/, "home decorative motion runs forever");
assert.match(motionSystem, /prefers-reduced-motion:\s*reduce[\s\S]*::view-transition-old/, "polished view transitions ignore reduced motion");

const home = await readFile(`${sourceRoot}/components/MedicationSummaryCard.jsx`, "utf8");
assert.match(home, /plan\.status === "待执行"/, "home medication list includes completed plans");
assert.match(home, /orderMedicationPlans\(pendingPlans, now\)\.slice\(0, 3\)/, "home does not limit its nearest pending task list to three items");
assert.match(home, /home-medication-list/, "home medication tasks are not rendered as a list");
assert.doesNotMatch(home, /metric-grid/, "home medication card still renders the removed summary metrics");
assert.match(home, /home-plan-picker-trigger/, "home medication list has no scalable overflow picker");
assert.match(home, /全部待办/, "home medication card no longer exposes the full pending-task list");
assert.match(home, /<small>待取出<\/small>/, "home medication rows do not use the requested pending pickup label");
assert.doesNotMatch(home, /未完成\s*\{index/, "home medication rows still expose task fractions");
assert.match(home, /<MedicationTaskPicker/, "additional medication tasks cannot be selected from the overflow picker");
assert.match(home, /onPickPlan=\{pickPlanAndDispense\}/, "task picker does not open the selected task's dispense flow");
assert.match(home, /onClick=\{\(\) => onQuickDispense\?\.\(plan\)\}/, "visible medication tasks do not open their own dispense flow");
assert.doesNotMatch(home, /home-current-user|ScanFace/, "home medication summary still exposes identity confirmation");

const homeHero = await readFile(`${sourceRoot}/components/HomeHero.jsx`, "utf8");
assert.ok(
  homeHero.indexOf("<InquiryEntryCard") < homeHero.indexOf("<MedicationSummaryCard"),
  "AI inquiry is not the first primary home task"
);

const inquiryEntry = await readFile(`${sourceRoot}/components/InquiryEntryCard.jsx`, "utf8");
assert.match(inquiryEntry, /StrokeDrawIcon[^>]*icon=\{Bot\}[^>]*mode="once"/, "home inquiry assistant is missing its one-shot draw motion");
assert.doesNotMatch(inquiryEntry, /mode="yoyo"/, "home inquiry assistant animation should settle into a complete static icon");
assert.doesNotMatch(inquiryEntry, /inquiry-assistant-scan/, "home inquiry icon did not return to the previous uncluttered version");
assert.doesNotMatch(inquiryEntry, /inquiry-capability-icon/, "home inquiry capabilities still use the overlapping animated wrappers");

const quickActions = await readFile(`${sourceRoot}/components/QuickActions.jsx`, "utf8");
assert.match(quickActions, /quick-action-cta/, "body measurement card has no explicit action button");
assert.match(quickActions, /开始测量/, "body measurement action is not clearly labeled");
assert.doesNotMatch(quickActions, /点击开始测量/, "body measurement action still contains the redundant tap instruction");
assert.match(appStyles, /\.quick-action-cta[\s\S]*min-height:\s*58px/, "body measurement action is too small for touch use");

const medicationTaskPicker = await readFile(`${sourceRoot}/components/MedicationTaskPicker.jsx`, "utf8");
assert.match(medicationTaskPicker, /role="dialog"/, "medication task picker is not an accessible dialog");
assert.match(medicationTaskPicker, /orderMedicationTaskPickerPlans/, "full medication task list is not ordered chronologically");
assert.match(medicationTaskPicker, /isMedicationPlanCompleted/, "completed medication tasks are not handled separately");
assert.match(medicationTaskPicker, /已取出/, "completed medication tasks do not show the taken label");
assert.match(medicationTaskPicker, /plan\.target_user/, "task picker does not distinguish people sharing the same time");
assert.match(medicationTaskPicker, /plan\.medicine/, "task picker does not identify the selected medicine");
assert.match(medicationTaskPicker, /plan\.dose/, "task picker does not show the dose for repeated user tasks");
assert.match(medicationTaskPicker, /medicationPlanTimeLabel\(plan\)/, "task picker cannot display meal-related or unrestricted schedule labels");
assert.match(appStyles, /\.home-task-picker-list[\s\S]*overflow-y:\s*auto/, "large medication task queues cannot scroll");

const medicines = await readFile(`${sourceRoot}/pages/Medicines.jsx`, "utf8");
assert.doesNotMatch(medicines, /useFaceIdentity/, "opening the medicines page still starts identity recognition");

const dispenseModal = await readFile(`${sourceRoot}/components/DispenseConfirmModal.jsx`, "utf8");
assert.match(dispenseModal, /identifyFingerprint/, "dispense confirmation is missing fingerprint verification");
assert.match(dispenseModal, /verifyDispenseIdentity/, "dispense confirmation is missing face verification");
assert.match(dispenseModal, /plan \? "fingerprint" : "face"/, "today-plan dispense does not default to fingerprint verification");
assert.match(dispenseModal, /plan\.time[\s\S]*plan\.timing_label[\s\S]*plan\.frequency_label/, "dispense confirmation does not preserve clock time, meal timing and frequency together");
assert.ok(
  dispenseModal.indexOf('selectMethod("fingerprint")') < dispenseModal.indexOf('selectMethod("face")'),
  "fingerprint verification is not presented before face verification"
);
assert.match(dispenseModal, /useState\(false\)[\s\S]*previewRetry/, "face preview starts before the user confirms identity");
assert.match(dispenseModal, /facePreviewVisible && previewActive/, "face preview is not available before verification begins");
assert.match(dispenseModal, /resumeFacePreview/, "face preview is not resumed after identity verification");
assert.match(dispenseModal, /facePreviewVisible \? null/, "face confirmation text can still cover the live preview");
assert.doesNotMatch(
  dispenseModal,
  /setPhase\("verifying"\)[\s\S]{0,240}setPreviewActive\(false\)[\s\S]{0,240}verifyDispenseIdentity/,
  "face preview is removed while the confirmation button says it is identifying"
);
assert.match(dispenseModal, /FACE_VERIFICATION_FRAME_INTERVAL_MS\s*=\s*250/, "face verification preview refresh is not bounded");
assert.match(dispenseModal, /\/api\/identity\/frame\?t=/, "face verification does not use the recognition-owned live frame source");
assert.match(dispenseModal, /DISPENSE_AUTO_CLOSE_MS\s*=\s*2000/, "successful dispense does not use the requested two-second close delay");
assert.match(
  dispenseModal,
  /phase === "complete"[\s\S]*window\.setTimeout\([\s\S]*onCancel[\s\S]*DISPENSE_AUTO_CLOSE_MS/,
  "successful dispense does not close the confirmation modal automatically"
);
assert.match(dispenseModal, /const onCancelRef = useRef\(onCancel\)/, "auto-close callback is not stable across parent clock renders");
assert.match(dispenseModal, /onCancelRef\.current\(\)/, "auto-close timer does not call the latest close callback");
assert.match(
  dispenseModal,
  /if \(open && phase === "complete"\)[\s\S]*?\}, \[open, phase\]\);/,
  "auto-close timer can still restart whenever a parent recreates the close callback"
);
assert.match(dispenseModal, /DISPENSE_FINGERPRINT_TIMEOUT_SECONDS = 15/, "dispense fingerprint timeout is still too long");
assert.match(dispenseModal, /await nextPaint\(\)[\s\S]*setPreviewActive\(true\)[\s\S]*await nextPaint\(\)/, "face preview is not remounted safely before retry");
assert.match(dispenseModal, /key=\{`\$\{previewAttempt\}-\$\{previewRetry\}`\}/, "face preview retry reuses the stale image element");
assert.match(
  dispenseModal,
  /await ensureFacePreviewReady\(session, attempt\)[\s\S]*if \(!previewIsReady\)[\s\S]*verifyDispenseIdentity/,
  "face verification starts before the preview has produced its first frame"
);
assert.doesNotMatch(dispenseModal, /await wait\(240\)/, "face verification still relies on a fixed mount delay");
assert.match(dispenseModal, /setPhase\("face_retry"\)/, "technical face failures do not have a retry-only state");
assert.match(dispenseModal, /retryOnlyFaceFailure[\s\S]*重新识别[\s\S]*failedGuestConfirmation/, "retry-only face failure is not separated from visitor confirmation");
assert.match(dispenseModal, /!result && \(verificationError \|\| error\)/, "dispense success can still render together with a stale face error");
assert.match(dispenseModal, /setPhase\("recognized"\)/, "recognized users are not shown before cabinet opening");
assert.match(dispenseModal, /async function verifyAndOpen/, "dispense is missing the one-tap biometric workflow");
assert.match(dispenseModal, /await submitDispense\(verification\.user/, "known users do not automatically continue to cabinet opening");
assert.doesNotMatch(dispenseModal, /confirmAndOpen|verifyIdentity/, "dispense still requires a second confirmation click");
assert.match(dispenseModal, /setPhase\("guest_confirm"\)/, "unknown face flow has no second confirmation state");
assert.match(dispenseModal, /face_guest_confirmed/, "unknown face confirmation is not recorded explicitly");
assert.match(dispenseModal, /确认访客取药并开柜/, "visitor confirmation does not use the requested action label");
assert.match(dispenseModal, /biometric-action-row[\s\S]*faceVerificationActive[\s\S]*正在确认面部[\s\S]*访客取药/, "face verification actions are not split into equal bottom controls");
assert.match(dispenseModal, /正在确认面部/, "face verification status does not use the requested wording");
assert.match(dispenseModal, /guestTrigger === "recognition_failed"[\s\S]*重新识别/, "failed face verification cannot be retried");
assert.match(dispenseModal, /failedGuestConfirmation[\s\S]*重新识别[\s\S]*确认访客取药/, "failed face actions are not grouped in the requested order");
assert.match(dispenseModal, /verificationAttemptRef/, "stale face results can overwrite the visitor confirmation state");
assert.match(dispenseModal, /today_plan_id:\s*guest \? ""/, "guest dispense can incorrectly complete another person's plan");
assert.match(dispenseModal, /sessionRef\.current/, "closing the modal cannot cancel a delayed cabinet action");
assert.doesNotMatch(dispenseModal, /safety-confirmed|confirm-check/, "legacy duplicate safety checkbox is still rendered");
assert.doesNotMatch(
  dispenseModal,
  /点击一次后完成身份确认并自动打开柜门|陌生使用人会在本机留存面部特征|未识别到人脸？以游客身份继续|本次将以游客（未识别人脸）记录|请将手指放在识别模块|请正对摄像头|biometric-guest-during-scan/,
  "dispense confirmation still contains removed visitor or automatic-opening guidance"
);

const inquiry = await readFile(`${sourceRoot}/pages/Inquiry.jsx`, "utf8");
assert.match(inquiry, /<InquiryIdentityGate/, "inquiry does not stop for visible identity confirmation");
assert.match(inquiry, /setIdentityConfirmed\(true\)/, "inquiry identity cannot be explicitly confirmed");
assert.match(inquiry, /activateOnMatch: false/, "inquiry face match is activated before the user confirms it");
assert.doesNotMatch(inquiry, /guestConfirmationPending/, "visitor inquiry still requires a duplicate second screen");
assert.match(inquiry, /onRequestGuest=\{confirmGuestInquiry\}/, "visitor inquiry does not continue directly from the identity gate");
assert.match(inquiry, /onReset=\{resetFlow\}/, "chat reset does not return to identity confirmation");

const inquiryGate = await readFile(`${sourceRoot}/components/InquiryIdentityGate.jsx`, "utf8");
assert.doesNotMatch(inquiryGate, /guestConfirmation|onConfirmGuest|访客问询确认|确认并开始问询/, "identity gate still contains a duplicate visitor confirmation step");
assert.doesNotMatch(inquiryGate, /<p>\{message|正在通过人脸确认使用人|摄像头正在执行另一项任务/, "identity gate still exposes face-recognition technical copy");

const inquiryChat = await readFile(`${sourceRoot}/components/InquiryChatStep.jsx`, "utf8");
assert.match(inquiryChat, /onClick=\{onReset\}/, "chat reset button does not delegate to the full inquiry reset");
assert.doesNotMatch(inquiryChat, /正在通过人脸确认使用人/, "chat still seeds the removed face-recognition technical copy");

const packageJson = JSON.parse(await readFile(`${frontendRoot}package.json`, "utf8"));
assert.equal(packageJson.dependencies?.["lottie-web"], undefined, "lottie-web should not be bundled");

console.log(`Selective motion contract: ${drawUsers.length} approved surfaces, all other icons static`);
