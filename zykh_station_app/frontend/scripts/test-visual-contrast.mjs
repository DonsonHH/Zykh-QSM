import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const appStyles = await readFile(`${frontendRoot}src/styles/app.css`, "utf8");
const polishStyles = await readFile(`${frontendRoot}src/styles/design-polish.css`, "utf8");
const styles = `${appStyles}\n${polishStyles}`;

function lastHexToken(name) {
  const matches = [...styles.matchAll(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`, "g"))];
  assert.ok(matches.length, `missing --${name} color token`);
  return matches.at(-1)[1];
}

function relativeLuminance(hex) {
  const channels = hex.slice(1).match(/../g).map((value) => Number.parseInt(value, 16) / 255);
  const [red, green, blue] = channels.map((value) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  );
  return red * 0.2126 + green * 0.7152 + blue * 0.0722;
}

function contrast(first, second) {
  const firstLuminance = relativeLuminance(first);
  const secondLuminance = relativeLuminance(second);
  return (Math.max(firstLuminance, secondLuminance) + 0.05) /
    (Math.min(firstLuminance, secondLuminance) + 0.05);
}

const surface = lastHexToken("surface");
assert.ok(contrast(lastHexToken("text"), surface) >= 7, "primary text is not high contrast on cards");
assert.ok(contrast(lastHexToken("muted"), surface) >= 4.5, "secondary text is not readable on cards");
assert.ok(contrast(lastHexToken("primary"), surface) >= 4.5, "primary actions are not distinguishable on cards");
assert.ok(contrast(lastHexToken("border-strong"), surface) >= 3, "card edges rely on subtle gray or shadow alone");
assert.ok(contrast(lastHexToken("focus-ring"), surface) >= 4.5, "keyboard focus is not distinct from white controls");
assert.ok(
  contrast(lastHexToken("dark-surface-edge"), lastHexToken("dark-surface")) >= 4.5,
  "near-black camera surfaces do not have a distinguishable edge"
);
assert.match(
  polishStyles,
  /\.card,[^]*?border-color:\s*var\(--border-strong\)/,
  "primary surfaces do not render the high-contrast edge token"
);
assert.match(
  polishStyles,
  /\.camera-stage\.live\s*\{[^}]*border:\s*3px solid var\(--dark-surface-edge\)/,
  "the dark camera surface does not render its high-contrast edge token"
);

console.log("visual contrast contract: ok");
