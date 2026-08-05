import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
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
  await cdp("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 600,
    deviceScaleFactor: 2,
    mobile: false
  });
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
    const dictionaryLoadedBeforeText = performance.getEntriesByType('resource')
      .some(({ name }) => name.includes('google_pinyin_dict'));
    const textInput = document.createElement('input');
    textInput.type = 'text';
    textInput.setAttribute('aria-label', '文本测试');
    document.body.append(textInput);
    textInput.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerType: 'touch', isPrimary: true }));
    textInput.focus();
    await new Promise((resolve) => setTimeout(resolve, 120));
    const textKeyboard = document.querySelector('[data-touch-keyboard]');
    const candidateStartedAt = performance.now();
    for (const key of ['n', 'i', 'h', 'a', 'o']) {
      textKeyboard?.querySelector('[data-key="' + key + '"]')?.click();
      await new Promise(requestAnimationFrame);
    }
    const candidateDeadline = performance.now() + 8000;
    let chineseCandidate;
    while (performance.now() < candidateDeadline) {
      chineseCandidate = [...(textKeyboard?.querySelectorAll('[data-pinyin-candidate]') || [])]
        .find((button) => button.textContent.includes('你好'));
      if (chineseCandidate) break;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    const composition = textKeyboard?.querySelector('[data-pinyin-composition]')?.textContent || '';
    const candidateReadyMs = Math.round(performance.now() - candidateStartedAt);
    chineseCandidate?.click();
    await new Promise((resolve) => setTimeout(resolve, 80));
    const chineseEnteredValue = textInput.value;
    textKeyboard?.querySelector('[data-key="language"]')?.click();
    await new Promise(requestAnimationFrame);
    for (const key of ['h', 'i', 'space', 'a']) {
      textKeyboard?.querySelector('[data-key="' + key + '"]')?.click();
      await new Promise(requestAnimationFrame);
    }
    const textBounds = textKeyboard?.getBoundingClientRect();
    const keyBounds = [...(textKeyboard?.querySelectorAll('button') || [])]
      .map((button) => button.getBoundingClientRect());
    const bottomInput = document.createElement('input');
    bottomInput.type = 'text';
    bottomInput.setAttribute('aria-label', '底部文本测试');
    Object.assign(bottomInput.style, {
      position: 'fixed', left: '120px', bottom: '20px', width: '320px', height: '48px', zIndex: '10'
    });
    document.body.append(bottomInput);
    bottomInput.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerType: 'touch', isPrimary: true }));
    bottomInput.focus();
    await new Promise((resolve) => setTimeout(resolve, 160));
    const movableKeyboard = document.querySelector('[data-touch-keyboard]');
    const bottomInputBounds = bottomInput.getBoundingClientRect();
    const keyboardBeforeDrag = movableKeyboard?.getBoundingClientRect();
    const header = movableKeyboard?.querySelector('.touch-keyboard-header');
    const headerBounds = header?.getBoundingClientRect();
    const dragDelta = (keyboardBeforeDrag?.top || 0) < 100 ? 80 : -80;
    header?.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true, pointerId: 7, pointerType: 'touch', isPrimary: true,
      clientX: headerBounds?.left + 80, clientY: headerBounds?.top + 20
    }));
    window.dispatchEvent(new PointerEvent('pointermove', {
      bubbles: true, pointerId: 7, pointerType: 'touch', isPrimary: true,
      clientX: headerBounds?.left + 80, clientY: headerBounds?.top + 20 + dragDelta
    }));
    window.dispatchEvent(new PointerEvent('pointerup', {
      bubbles: true, pointerId: 7, pointerType: 'touch', isPrimary: true
    }));
    await new Promise((resolve) => setTimeout(resolve, 80));
    const keyboardAfterDrag = movableKeyboard?.getBoundingClientRect();
    return {
      inputReady: true,
      ...numericResult,
      dictionaryLoadedBeforeText,
      textKeyboardVisible: Boolean(textKeyboard?.getBoundingClientRect().height),
      textKeyboardMode: textKeyboard?.dataset.mode || '',
      textKeyCount: textKeyboard?.querySelectorAll('button').length || 0,
      chineseComposition: composition,
      chineseCandidateFound: Boolean(chineseCandidate),
      candidateReadyMs,
      chineseEnteredValue,
      textEnteredValue: textInput.value,
      textWithinViewport: Boolean(textBounds && textBounds.left >= 0 && textBounds.top >= 0 &&
        textBounds.right <= innerWidth && textBounds.bottom <= innerHeight),
      bottomInputVisible: Boolean(bottomInputBounds && keyboardBeforeDrag &&
        (bottomInputBounds.bottom <= keyboardBeforeDrag.top - 8 ||
          bottomInputBounds.top >= keyboardBeforeDrag.bottom + 8)),
      bottomInputTop: Math.round(bottomInputBounds?.top || 0),
      keyboardTopBeforeDrag: Math.round(keyboardBeforeDrag?.top || 0),
      keyboardTopAfterDrag: Math.round(keyboardAfterDrag?.top || 0),
      keyboardInlinePosition: movableKeyboard?.getAttribute('style') || '',
      keyboardDragDistance: Math.abs(Math.round((keyboardBeforeDrag?.top || 0) - (keyboardAfterDrag?.top || 0))),
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
  assert.equal(result.dictionaryLoadedBeforeText, false, "pinyin dictionary loaded before a Chinese text field was opened");
  assert.equal(result.textKeyboardVisible, true, "text input did not show the screen keyboard");
  assert.equal(result.textKeyboardMode, "text", "text input did not request the full keyboard layout");
  assert.ok(result.textKeyCount >= 35, "text keyboard is missing required controls");
  assert.equal(result.chineseComposition, "nihao", "Chinese mode did not display the active pinyin composition");
  assert.equal(result.chineseCandidateFound, true, "pinyin candidate list did not include 你好");
  assert.ok(result.candidateReadyMs < 8000, `offline pinyin candidates took ${result.candidateReadyMs}ms to become ready`);
  assert.equal(result.chineseEnteredValue, "你好", "selecting a pinyin candidate did not commit Chinese text");
  assert.equal(result.textEnteredValue, "你好hi a", "English mode did not enter letters and spaces after Chinese text");
  assert.equal(result.textWithinViewport, true, "text keyboard extends outside the kiosk viewport");
  assert.equal(result.bottomInputVisible, true, "screen keyboard covers a bottom-positioned input field");
  assert.ok(result.keyboardDragDistance >= 60, `screen keyboard only moved ${result.keyboardDragDistance}px when dragged`);
  assert.ok(result.smallestKeyWidth >= 44, `keyboard key width is only ${result.smallestKeyWidth}px`);
  assert.ok(result.smallestKeyHeight >= 44, `keyboard key height is only ${result.smallestKeyHeight}px`);
  if (process.env.QA_SCREENSHOT_PATH) {
    const screenshot = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(process.env.QA_SCREENSHOT_PATH, Buffer.from(screenshot.data, "base64"));
  }
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
