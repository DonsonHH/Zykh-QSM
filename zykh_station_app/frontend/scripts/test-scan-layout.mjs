import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const scanPage = await readFile(`${frontendRoot}src/pages/Scan.jsx`, "utf8");
const styles = await readFile(`${frontendRoot}src/styles/app.css`, "utf8");

assert.doesNotMatch(
  scanPage,
  /<span>有效期<\/span>/,
  "scan result still renders the removed expiry card"
);
assert.match(
  scanPage,
  /className="scan-meta-wide"[\s\S]*?<span>条码<\/span>/,
  "barcode is not given a full-width result row"
);
assert.match(
  scanPage,
  /className="scan-meta-wide"[\s\S]*?<span>规格<\/span>/,
  "medicine specification is not given a full-width result row"
);
assert.match(
  scanPage,
  /scan-live-status-row/,
  "camera status still has no dedicated row outside the preview"
);
assert.match(
  styles,
  /\.scan-meta-grid article\.scan-meta-wide\s*\{[\s\S]*grid-column:\s*1\s*\/\s*-1/,
  "wide scan result rows do not span both columns"
);
assert.match(
  styles,
  /\.scan-meta-grid strong\s*\{[\s\S]*white-space:\s*normal/,
  "scan result values are still forced onto one clipped line"
);
assert.match(
  styles,
  /\.scan-result-heading h2\s*\{[\s\S]*white-space:\s*normal/,
  "recognized medicine name is still forced onto one clipped line"
);

console.log("scan layout contract passed");
