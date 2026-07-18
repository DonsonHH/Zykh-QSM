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

for (const variable of [
  "--surface-shadow",
  "--surface-shadow-quiet",
  "--surface-shadow-item",
  "--surface-shadow-raised"
]) {
  const pattern = new RegExp(`${variable}:\\s*\\n\\s*inset 0 0 0 1px`);
  assert.match(surfaces, pattern, `${variable} must use an inset hairline so overflow containers cannot clip it`);
}

console.log("Inquiry guest session and surface hairline contracts passed.");
