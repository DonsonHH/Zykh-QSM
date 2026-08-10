import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const api = await readFile(`${root}src/api/admin.js`, "utf8");
const devices = await readFile(`${root}src/components/admin/AdminDevices.jsx`, "utf8");
const styles = await readFile(`${root}src/styles/admin.css`, "utf8");

assert.match(api, /export function issueAdminPairingCode\(serviceUserIds, ttlMinutes = 10\)/);
assert.match(api, /adminRequest\("\/api\/admin\/pairing-codes",\s*\{\s*method:\s*"POST"/s);
assert.match(api, /service_user_ids:\s*serviceUserIds/);
assert.match(api, /ttl_minutes:\s*ttlMinutes/);

assert.match(devices, /loadAdminUsers/);
assert.match(devices, /issueAdminPairingCode/);
assert.match(devices, /value=\{pairingUserId\}/);
assert.match(devices, /select[^>]+disabled=\{pairingBusy\}/s);
assert.match(devices, /disabled=\{pairingBusy \|\| !pairingUserId\}/);
assert.match(devices, /pairing_code/);
assert.match(devices, /expires_at/);
assert.match(devices, /window\.setInterval/);
assert.match(devices, /window\.clearInterval/);
assert.match(devices, /setIssuedPairing\(null\)/);
assert.match(devices, /issuedPairing\?\.service_user_ids/);
assert.match(devices, /授权对象/);
assert.doesNotMatch(devices, /localStorage|sessionStorage/);
assert.doesNotMatch(devices, /console\.(?:log|info|warn|error)/);

assert.match(styles, /\.admin-pairing-panel\s*\{/);
assert.match(styles, /\.admin-pairing-code\s*\{/);

console.log("admin pairing code contract: ok");
