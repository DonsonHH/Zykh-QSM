import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const baseUrl = process.env.QA_BASE_URL || "http://127.0.0.1:5173";
const profileDir = await mkdtemp(join(tmpdir(), "zykh-touch-keyboard-"));
const debuggingPort = 9800 + Math.floor(Math.random() * 100);
const browser = spawn(process.env.CHROMIUM_BIN || "chromium", [
  "--headless=new",
  "--no-sandbox",
  "--disable-gpu",
  "--remote-allow-origins=*",
  `--remote-debugging-port=${debuggingPort}`,
  `--user-data-dir=${profileDir}`,
  "--window-size=1920,1200",
  "--force-device-scale-factor=2",
  `${baseUrl}/?page=admin&awake=1`
], { stdio: "ignore" });

let socket;
let messageId = 0;
const pending = new Map();
const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitForTarget() {
  const deadline = Date.now() + 8_000;
  while (Date.now() < deadline) {
    try {
      const targets = await fetch(`http://127.0.0.1:${debuggingPort}/json/list`).then((response) => response.json());
      const target = targets.find(({ type }) => type === "page");
      if (target?.webSocketDebuggerUrl) return target.webSocketDebuggerUrl;
    } catch {
      // Chromium has not opened the debugging endpoint yet.
    }
    await delay(50);
  }
  throw new Error("Chromium DevTools target did not become ready");
}

async function connect(url) {
  await new Promise((resolve, reject) => {
    socket = new WebSocket(url);
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
    socket.addEventListener("message", ({ data }) => {
      const message = JSON.parse(data);
      const request = pending.get(message.id);
      if (!request) return;
      pending.delete(message.id);
      if (message.error) request.reject(new Error(message.error.message));
      else request.resolve(message.result || {});
    });
  });
}

async function cdp(method, params = {}) {
  const id = ++messageId;
  const response = new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
  socket.send(JSON.stringify({ id, method, params }));
  return response;
}

async function evaluate(expression) {
  const result = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result?.value;
}

async function stopBrowser() {
  if (browser.exitCode !== null || browser.signalCode !== null) return;
  browser.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => browser.once("exit", resolve)),
    delay(1500)
  ]);
  if (browser.exitCode === null && browser.signalCode === null) browser.kill("SIGKILL");
}

try {
  await connect(await waitForTarget());
  await cdp("Runtime.enable");
  const result = await evaluate(`(async () => {
    const deadline = performance.now() + 5000;
    let input;
    while (performance.now() < deadline) {
      input = document.querySelector('.admin-login-panel input');
      if (input) break;
      await new Promise(requestAnimationFrame);
    }
    if (!input) return { inputReady: false, keyboardVisible: false };
    await new Promise((resolve) => setTimeout(resolve, 80));
    input.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerType: 'touch', isPrimary: true }));
    input.focus();
    await new Promise((resolve) => setTimeout(resolve, 120));
    const keyboard = document.querySelector('[data-touch-keyboard]');
    const bounds = keyboard?.getBoundingClientRect();
    for (const key of ['1', '1', '4', '5']) {
      keyboard?.querySelector('[data-key="' + key + '"]')?.click();
      await new Promise(requestAnimationFrame);
    }
    const numericResult = {
      inputFocused: document.activeElement === input,
      keyboardVisible: Boolean(keyboard && bounds && bounds.width > 0 && bounds.height > 0),
      keyboardMode: keyboard?.dataset.mode || '',
      keyCount: keyboard?.querySelectorAll('button').length || 0,
      enteredValue: input.value
    };
    const textInput = document.createElement('input');
    textInput.type = 'text';
    textInput.setAttribute('aria-label', '文本测试');
    document.body.append(textInput);
    textInput.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerType: 'touch', isPrimary: true }));
    textInput.focus();
    await new Promise((resolve) => setTimeout(resolve, 120));
    const textKeyboard = document.querySelector('[data-touch-keyboard]');
    for (const key of ['h', 'i', 'space', 'a']) {
      textKeyboard?.querySelector('[data-key="' + key + '"]')?.click();
      await new Promise(requestAnimationFrame);
    }
    const textBounds = textKeyboard?.getBoundingClientRect();
    const keyBounds = [...(textKeyboard?.querySelectorAll('button') || [])]
      .map((button) => button.getBoundingClientRect());
    return {
      inputReady: true,
      ...numericResult,
      textKeyboardVisible: Boolean(textKeyboard?.getBoundingClientRect().height),
      textKeyboardMode: textKeyboard?.dataset.mode || '',
      textKeyCount: textKeyboard?.querySelectorAll('button').length || 0,
      textEnteredValue: textInput.value,
      textWithinViewport: Boolean(textBounds && textBounds.left >= 0 && textBounds.top >= 0 &&
        textBounds.right <= innerWidth && textBounds.bottom <= innerHeight),
      smallestKeyWidth: Math.min(...keyBounds.map(({ width }) => width)),
      smallestKeyHeight: Math.min(...keyBounds.map(({ height }) => height))
    };
  })()`);
  process.stdout.write(`${JSON.stringify(result)}\n`);
  assert.equal(result.inputReady, true, "admin PIN input did not render");
  assert.equal(result.inputFocused, true, "touch did not focus the admin PIN input");
  assert.equal(result.keyboardVisible, true, "touching a text input did not show a visible screen keyboard");
  assert.equal(result.keyboardMode, "numeric", "admin PIN did not request the numeric keyboard layout");
  assert.ok(result.keyCount >= 12, "numeric keyboard is missing required controls");
  assert.equal(result.enteredValue, "1145", "screen-key presses did not update the controlled PIN input");
  assert.equal(result.textKeyboardVisible, true, "text input did not show the screen keyboard");
  assert.equal(result.textKeyboardMode, "text", "text input did not request the full keyboard layout");
  assert.ok(result.textKeyCount >= 35, "text keyboard is missing required controls");
  assert.equal(result.textEnteredValue, "hi a", "text keyboard did not enter letters and spaces");
  assert.equal(result.textWithinViewport, true, "text keyboard extends outside the kiosk viewport");
  assert.ok(result.smallestKeyWidth >= 44, `keyboard key width is only ${result.smallestKeyWidth}px`);
  assert.ok(result.smallestKeyHeight >= 44, `keyboard key height is only ${result.smallestKeyHeight}px`);
  await cdp("Page.navigate", { url: `${baseUrl}/?page=admin&awake=1&touchKeyboard=0` });
  const disabledKeyboardVisible = await evaluate(`(async () => {
    const deadline = performance.now() + 5000;
    let input;
    while (performance.now() < deadline) {
      input = document.querySelector('.admin-login-panel input');
      if (input) break;
      await new Promise(requestAnimationFrame);
    }
    if (!input) throw new Error('disabled-mode PIN input did not render');
    await new Promise((resolve) => setTimeout(resolve, 80));
    input.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerType: 'touch', isPrimary: true }));
    input.focus();
    await new Promise((resolve) => setTimeout(resolve, 120));
    return Boolean(document.querySelector('[data-touch-keyboard]'));
  })()`);
  assert.equal(disabledKeyboardVisible, false, "touchKeyboard=0 did not disable the app keyboard");
  console.log("touch keyboard interaction: ok");
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  await stopBrowser();
  await rm(profileDir, { recursive: true, force: true });
}
