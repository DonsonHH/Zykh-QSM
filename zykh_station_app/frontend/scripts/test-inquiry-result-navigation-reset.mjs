import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const inquiry = await readFile(`${root}src/pages/Inquiry.jsx`, "utf8");

assert.match(
  inquiry,
  /resetOnResultLeaveRef/,
  "Inquiry must remember whether the recommendation page was visible"
);
assert.match(
  inquiry,
  /session\?\.stage === "result" && resultConfirmed/,
  "only a confirmed result page should arm the leave reset"
);
assert.match(
  inquiry,
  /if \(resetOnResultLeaveRef\.current\) clearInquirySession\(\)/,
  "leaving the recommendation page must clear the active session and identity draft"
);
assert.match(
  inquiry,
  /else if \(!identityConfirmed\)[\s\S]{0,250}identifyFace\(\{ force: true \}\)/,
  "a remounted inquiry without an identity draft must restart identity recognition"
);

console.log("inquiry result navigation reset contract: ok");
