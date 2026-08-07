import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const TEST_SCOPE = "生产身份识别与访客显式确认链路";
const inquiryPage = await readFile(new URL("../src/pages/Inquiry.jsx", import.meta.url), "utf8");
const identityGate = await readFile(new URL("../src/components/InquiryIdentityGate.jsx", import.meta.url), "utf8");
const chatStep = await readFile(new URL("../src/components/InquiryChatStep.jsx", import.meta.url), "utf8");
const surfaces = await readFile(new URL("../src/styles/design-polish.css", import.meta.url), "utf8");

assert.match(inquiryPage, /activateIdentity, useFaceIdentity/);
assert.match(inquiryPage, /useFaceIdentity\(\{ auto: false, activateOnMatch: false \}\)/);
assert.match(inquiryPage, /restoredSessionId[\s\S]{0,900}loadInquirySession\(restoredSessionId\)/);
assert.match(inquiryPage, /else if \(!identityConfirmed\)[\s\S]{0,220}identifyFace\(\{ force: true \}\)/);
assert.match(inquiryPage, /function confirmIdentity\(\)[\s\S]{0,320}activateIdentity\(faceIdentity\)/);
assert.match(inquiryPage, /function confirmGuestInquiry\(\)[\s\S]{0,420}activateIdentity\(visitor\)/);
assert.match(inquiryPage, /!identityConfirmed \? \([\s\S]{0,260}<InquiryIdentityGate/);
assert.match(identityGate, /是我，开始问询/);
assert.match(identityGate, /不是我/);
assert.match(identityGate, /重新识别/);
assert.match(identityGate, /不等待识别，以访客身份继续/);
assert.match(identityGate, /以访客身份继续/);

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

console.log(`[${TEST_SCOPE}] contract passed; no identity bypass is exercised.`);
