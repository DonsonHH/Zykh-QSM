import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const inquiry = await readFile(`${root}src/pages/Inquiry.jsx`, "utf8");
const chat = await readFile(`${root}src/components/InquiryChatStep.jsx`, "utf8");
const vitals = await readFile(`${root}src/pages/Vitals.jsx`, "utf8");
const sessionUtils = await readFile(`${root}src/utils/inquirySession.js`, "utf8");

assert.match(inquiry, /<Vitals\s+embedded/, "AI inquiry must render vitals as an embedded tool step");
assert.match(inquiry, /onReplyPlaybackStart=\{handleReplyPlaybackStart\}/, "vitals opens without a playback start signal");
assert.match(inquiry, /3000/, "vitals must open three seconds after spoken guidance starts");
assert.doesNotMatch(inquiry, /InquiryVitalsTransition/, "AI inquiry still renders an intermediate vitals page");
assert.doesNotMatch(inquiry, /setVitalsFlow\("transition"\)/, "AI inquiry still enters the intermediate transition state");
assert.match(inquiry, /status:\s*"complete"/, "complete vitals are not attached to the active inquiry session");
assert.match(inquiry, /"failed"\s*:\s*"cancelled"/, "failed and cancelled measurements do not return to AI");
assert.doesNotMatch(inquiry, /onNavigate\("vitals"/, "AI inquiry still navigates to a separate vitals page");
assert.doesNotMatch(inquiry, /zykh-latest-vitals/, "AI vitals still depend on sessionStorage result transfer");
assert.doesNotMatch(
  inquiry,
  /prepareQsmVitals|startVitalsSession|loadVitalsSession|cancelVitalsSession/,
  "AI inquiry owns a second QSM measurement implementation instead of sharing the home Vitals component"
);
assert.doesNotMatch(inquiry, /preparedVitalsRequestRef/, "AI inquiry still owns duplicate vitals prewarm state");
assert.doesNotMatch(sessionUtils, /INQUIRY_VITALS_AWAITING_KEY/, "legacy vitals transfer state remains");

assert.match(chat, /utterance\.onend\s*=\s*\(\)\s*=>\s*resolve\(true\)/, "browser TTS does not expose actual playback completion");
assert.match(chat, /onReplyPlaybackStart\?\.\(\)/, "chat does not report spoken guidance start");
assert.match(chat, /preservePlaybackOnExitRef/, "entering vitals interrupts the active spoken guidance");

assert.match(vitals, /completionReportedRef/, "embedded vitals can submit the same result repeatedly");
assert.match(vitals, /onComplete\?\.\(result\)/, "completed vitals do not return to AI");
assert.match(vitals, /onExit\?\.\(\{\s*status:\s*"cancelled"/, "cancelled vitals do not return to AI");
assert.match(vitals, /prepareQsmVitals/, "shared Vitals component does not own device prewarm");
assert.match(vitals, /startVitalsSession/, "shared Vitals component does not own measurement start");
assert.match(vitals, /loadVitalsSession/, "shared Vitals component does not own session polling");
assert.match(vitals, /cancelVitalsSession/, "shared Vitals component does not own cancellation");
assert.doesNotMatch(vitals, /zykh-latest-vitals/, "vitals page still writes a cross-page handoff");

console.log("inquiry vitals tool flow: ok");
