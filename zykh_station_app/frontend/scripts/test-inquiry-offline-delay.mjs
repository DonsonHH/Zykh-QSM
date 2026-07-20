import assert from "node:assert/strict";

import {
  OFFLINE_REPLY_MIN_DELAY_MS,
  offlineReplyDelayMs,
} from "../src/utils/inquiryTiming.js";

assert.equal(OFFLINE_REPLY_MIN_DELAY_MS, 3000);
assert.equal(offlineReplyDelayMs("offline_rules", 0), 3000);
assert.equal(offlineReplyDelayMs("offline_rules", 1200), 1800);
assert.equal(offlineReplyDelayMs("offline_rules", 3600), 0);
assert.equal(offlineReplyDelayMs("offline_rules", 0, "escalate"), 0);
assert.equal(offlineReplyDelayMs("cloud", 0), 0);

console.log("inquiry offline timing contract passed");
