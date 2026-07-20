import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import {
  OFFLINE_REPLY_MIN_DELAY_MS,
  offlineReplyDelayMs,
} from "../src/utils/inquiryTiming.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const inquiry = await readFile(`${root}src/pages/Inquiry.jsx`, "utf8");

assert.equal(OFFLINE_REPLY_MIN_DELAY_MS, 3000);
assert.equal(offlineReplyDelayMs("offline_rules"), 3000);
assert.equal(offlineReplyDelayMs("local_llm"), 3000);
assert.equal(offlineReplyDelayMs("cloud", true), 3000);
assert.equal(offlineReplyDelayMs("cloud", false), 0);
assert.match(
  inquiry,
  /const waitForReplyPresentation = useCallback/,
  "inquiry does not share one local reply presentation delay"
);
assert.match(
  inquiry,
  /offlineReplyDelayMs\(\s*data\?\.source,\s*isLocalNetworkMode\(networkStatus\)\s*\)/,
  "inquiry does not delay replies while the terminal is displayed in local mode"
);
assert.match(
  inquiry,
  /sendInquiryTurn\(sessionId, transcript\);\s*await waitForReplyPresentation\(data\)/,
  "spoken inquiry turns do not wait before presenting a local reply"
);
assert.match(
  inquiry,
  /attachInquiryVitals\(sessionId,[\s\S]*?await waitForReplyPresentation\(updated\)/,
  "the AI reply after vitals is not delayed in local mode"
);
assert.doesNotMatch(
  inquiry,
  /performance\.now\(\)\s*-\s*startedAt/,
  "offline reply timing still subtracts backend processing time"
);

console.log("inquiry offline timing contract passed");
