import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import {
  CLOUD_REPLY_STREAM_PROFILE,
  LOCAL_REPLY_STREAM_PROFILE,
  inquiryReplyStreamProfile,
} from "../src/utils/inquiryStreaming.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const inquiry = await readFile(`${root}src/pages/Inquiry.jsx`, "utf8");
const chat = await readFile(`${root}src/components/InquiryChatStep.jsx`, "utf8");

assert.deepEqual(LOCAL_REPLY_STREAM_PROFILE, { chunkSize: 1, intervalMs: 72 });
assert.deepEqual(CLOUD_REPLY_STREAM_PROFILE, { chunkSize: 4, intervalMs: 42 });
assert.deepEqual(inquiryReplyStreamProfile("offline_rules"), LOCAL_REPLY_STREAM_PROFILE);
assert.deepEqual(inquiryReplyStreamProfile("local_llm"), LOCAL_REPLY_STREAM_PROFILE);
assert.deepEqual(inquiryReplyStreamProfile("cloud", true), CLOUD_REPLY_STREAM_PROFILE);
assert.deepEqual(inquiryReplyStreamProfile("cloud", false), CLOUD_REPLY_STREAM_PROFILE);
assert.doesNotMatch(inquiry, /offlineReplyDelayMs|waitForReplyPresentation/,
  "inquiry replies still wait for the legacy fixed offline delay");
assert.match(chat, /inquiryReplyStreamProfile\(session\.source\)/,
  "chat replies do not select a streaming profile from the actual response source");
assert.doesNotMatch(chat, /localDisplayMode/,
  "display mode still changes inquiry reply presentation");
assert.match(chat, /index \+ streamProfile\.chunkSize/,
  "chat replies do not reveal text using the selected streaming chunk size");
assert.match(chat, /streamProfile\.intervalMs/,
  "chat replies do not use the selected streaming interval");
assert.match(chat, /setStreaming\(false\);\s*playReply\(reply, true\)/,
  "speech playback behavior changed while replacing the text delay");
assert.match(chat, /disabled=\{sending \|\| transcribingVoice \|\| streaming\}/,
  "voice input can overlap a reply that is still being revealed");

console.log("inquiry reply streaming contract passed");
