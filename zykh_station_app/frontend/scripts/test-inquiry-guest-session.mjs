import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const inquiryPage = await readFile(new URL("../src/pages/Inquiry.jsx", import.meta.url), "utf8");
const chatStep = await readFile(new URL("../src/components/InquiryChatStep.jsx", import.meta.url), "utf8");
const surfaces = await readFile(new URL("../src/styles/design-polish.css", import.meta.url), "utf8");

assert.match(inquiryPage, /const mountedRef = useRef\(false\)/);
assert.match(inquiryPage, /const creationToken = Symbol\("inquiry-session-creation"\)/);
assert.match(inquiryPage, /creatingRef\.current !== creationToken/);
assert.doesNotMatch(
  inquiryPage,
  /let cancelled = false;[\s\S]{0,1200}createInquirySession/,
  "session creation must not discard the first StrictMode request via an effect cleanup flag"
);

assert.doesNotMatch(
  chatStep,
  /previousReplyRef/,
  "the initial reply typewriter must restart after a StrictMode effect cleanup"
);
assert.match(chatStep, /const reply = session\.reply \|\| "";/);
assert.match(chatStep, /setStreamedReply\(""\)/);

assert.match(surfaces, /--border-strong:\s*#[0-9a-f]{6}/i, "surface system has no high-contrast edge token");
assert.match(
  surfaces,
  /\.card,[\s\S]*?\.inquiry-user-card,[\s\S]*?border-color:\s*var\(--border-strong\)/,
  "inquiry surfaces rely on a subtle shadow instead of an unclipped solid edge"
);
assert.doesNotMatch(
  surfaces,
  /\.card,[\s\S]*?\.inquiry-user-card,[\s\S]*?border(?:-color)?:\s*(?:1px solid )?transparent/,
  "inquiry surfaces can lose their edge on the low-gamut display"
);

console.log("Inquiry guest session and surface edge contracts passed.");
