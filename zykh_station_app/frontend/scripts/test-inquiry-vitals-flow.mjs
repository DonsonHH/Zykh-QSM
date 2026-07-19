import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const inquiry = await readFile(`${root}src/pages/Inquiry.jsx`, "utf8");
const chat = await readFile(`${root}src/components/InquiryChatStep.jsx`, "utf8");
const vitals = await readFile(`${root}src/pages/Vitals.jsx`, "utf8");
const sessionUtils = await readFile(`${root}src/utils/inquirySession.js`, "utf8");
const transition = await readFile(`${root}src/components/InquiryVitalsTransition.jsx`, "utf8");

assert.match(inquiry, /<Vitals\s+embedded/, "AI inquiry must render vitals as an embedded tool step");
assert.match(inquiry, /onReplyPlaybackComplete=\{handleReplyPlaybackComplete\}/, "vitals opens without a playback completion signal");
assert.match(inquiry, /setVitalsFlow\("transition"\)/, "spoken guidance has no visible transition state");
assert.match(inquiry, /2200/, "the post-guidance transition delay is missing");
assert.match(inquiry, /status:\s*"complete"/, "complete vitals are not attached to the active inquiry session");
assert.match(inquiry, /"failed"\s*:\s*"cancelled"/, "failed and cancelled measurements do not return to AI");
assert.doesNotMatch(inquiry, /onNavigate\("vitals"/, "AI inquiry still navigates to a separate vitals page");
assert.doesNotMatch(inquiry, /zykh-latest-vitals/, "AI vitals still depend on sessionStorage result transfer");
assert.doesNotMatch(sessionUtils, /INQUIRY_VITALS_AWAITING_KEY/, "legacy vitals transfer state remains");

assert.match(chat, /utterance\.onend\s*=\s*\(\)\s*=>\s*resolve\(true\)/, "browser TTS does not expose actual playback completion");
assert.match(chat, /const result = await speakText/, "QSM speech is not awaited before vitals transition");
assert.match(chat, /onReplyPlaybackComplete\?\.\(\)/, "chat does not report completed spoken guidance");
assert.match(chat, /语音引导未完成，请点击右上角重播后继续/, "failed guidance can silently enter measurement");

assert.match(vitals, /completionReportedRef/, "embedded vitals can submit the same result repeatedly");
assert.match(vitals, /onComplete\?\.\(result\)/, "completed vitals do not return to AI");
assert.match(vitals, /onExit\?\.\(\{\s*status:\s*"cancelled"/, "cancelled vitals do not return to AI");
assert.doesNotMatch(vitals, /zykh-latest-vitals/, "vitals page still writes a cross-page handoff");
assert.match(transition, /语音引导已完成/, "transition does not explain why the page is changing");

console.log("inquiry vitals tool flow: ok");
