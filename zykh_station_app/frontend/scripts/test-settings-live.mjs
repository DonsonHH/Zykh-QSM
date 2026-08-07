import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

const baseUrl = process.env.QA_BASE_URL;
if (!baseUrl) {
  throw new Error("test-settings-live requires QA_BASE_URL for an isolated frontend build");
}
const parsedBaseUrl = new URL(baseUrl);
if (!["127.0.0.1", "localhost"].includes(parsedBaseUrl.hostname)) {
  throw new Error("test-settings-live only accepts a loopback mock URL");
}
const screenshotPath = process.env.QA_SCREENSHOT_PATH ? resolve(process.env.QA_SCREENSHOT_PATH) : "";
const profileDir = await mkdtemp(join(tmpdir(), "zykh-settings-live-"));
const debuggingPort = 9500 + Math.floor(Math.random() * 300);
const browser = spawn(process.env.CHROMIUM_BIN || "chromium", [
  "--headless=new",
  "--no-sandbox",
  "--hide-scrollbars",
  "--disable-gpu",
  "--disable-accelerated-2d-canvas",
  "--remote-allow-origins=*",
  `--remote-debugging-port=${debuggingPort}`,
  `--user-data-dir=${profileDir}`,
  "--window-size=1920,1200",
  "--force-device-scale-factor=2",
  "about:blank"
], { stdio: "ignore" });

let socket;
let nextMessageId = 0;
let interceptionError = null;
const pending = new Map();
const apiRequests = [];
const mockSettings = {
  network_mode: "sim",
  speaker_volume: 230,
  microphone_volume: 70,
  display_brightness: 100,
  idle_timeout_seconds: 90
};

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

async function fulfillApiRequest({ requestId, request }) {
  const url = new URL(request.url);
  const method = request.method.toUpperCase();
  apiRequests.push({ method, path: url.pathname });
  let payload = { ok: true };
  if (url.pathname === "/api/settings/basic") {
    payload = { settings: mockSettings, warnings: [] };
  } else if (url.pathname === "/api/network/status") {
    payload = {
      label: "联网模式",
      signal: "good",
      wifi_connected: true,
      sim_connected: true,
      simulated: true
    };
  } else if (url.pathname === "/api/dashboard") {
    payload = {};
  }
  await cdp("Fetch.fulfillRequest", {
    requestId,
    responseCode: 200,
    responseHeaders: [{ name: "Content-Type", value: "application/json; charset=utf-8" }],
    body: Buffer.from(JSON.stringify(payload)).toString("base64")
  });
}

async function waitForTarget() {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${debuggingPort}/json/list`);
      const page = (await response.json()).find((target) => target.type === "page");
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch {
      // Chromium is still starting.
    }
    await delay(50);
  }
  throw new Error("Chromium DevTools target did not become ready");
}

async function connect(url) {
  await new Promise((resolveSocket, rejectSocket) => {
    socket = new WebSocket(url);
    socket.addEventListener("open", resolveSocket, { once: true });
    socket.addEventListener("error", rejectSocket, { once: true });
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.method === "Fetch.requestPaused") {
        fulfillApiRequest(message.params).catch((error) => {
          interceptionError = error;
        });
        return;
      }
      if (!message.id || !pending.has(message.id)) return;
      const handlers = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) handlers.reject(new Error(message.error.message));
      else handlers.resolve(message.result || {});
    });
  });
}

async function cdp(method, params = {}) {
  const id = ++nextMessageId;
  const response = new Promise((resolveMessage, rejectMessage) => {
    pending.set(id, { resolve: resolveMessage, reject: rejectMessage });
  });
  socket.send(JSON.stringify({ id, method, params }));
  return response;
}

async function evaluate(expression) {
  const result = await cdp("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Browser evaluation failed");
  return result.result?.value;
}

async function waitForApp() {
  const deadline = Date.now() + 8_000;
  while (Date.now() < deadline) {
    if (await evaluate("document.readyState === 'complete' && Boolean(document.querySelector('.kiosk-frame'))")) return;
    await delay(40);
  }
  throw new Error("Kiosk app did not render");
}

async function stopBrowser() {
  if (browser.exitCode === null && browser.signalCode === null) {
    browser.kill("SIGTERM");
    await Promise.race([
      new Promise((resolveExit) => browser.once("exit", resolveExit)),
      delay(1500)
    ]);
  }
  socket?.close();
  await rm(profileDir, { recursive: true, force: true, maxRetries: 4, retryDelay: 50 });
}

try {
  await connect(await waitForTarget());
  await cdp("Page.enable");
  await cdp("Runtime.enable");
  await cdp("Fetch.enable", {
    patterns: [{ urlPattern: "*/api/*", requestStage: "Request" }]
  });
  await cdp("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 600,
    deviceScaleFactor: 2,
    mobile: false
  });
  await cdp("Page.navigate", { url: `${baseUrl}/?page=home&awake=1` });
  await waitForApp();
  await delay(350);

  const result = await evaluate(`(async () => {
    const waitFor = async (selector, predicate = () => true) => {
      const deadline = performance.now() + 5000;
      while (performance.now() < deadline) {
        const element = document.querySelector(selector);
        if (element && predicate(element)) return element;
        await new Promise(requestAnimationFrame);
      }
      throw new Error('Timed out waiting for ' + selector);
    };

    const longTasks = [];
    const recordLongTasks = (entries) => {
      longTasks.push(...entries.map(({ duration, startTime, name, attribution }) => ({
        duration,
        startTime,
        name,
        attribution: attribution?.map((item) => ({ name: item.name, containerType: item.containerType })) || []
      })));
    };
    const observer = new PerformanceObserver((list) => recordLongTasks(list.getEntries()));
    try { observer.observe({ entryTypes: ['longtask'] }); } catch {}

    const frameGaps = [];
    let previousFrame = 0;
    let collecting = true;
    const tick = (timestamp) => {
      if (previousFrame) frameGaps.push(timestamp - previousFrame);
      previousFrame = timestamp;
      if (collecting) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);

    const startedAt = performance.now();
    (await waitFor('.system-check-button')).click();
    const settings = await waitFor('.basic-settings-page');
    await new Promise(requestAnimationFrame);
    const destinationRenderedMs = performance.now() - startedAt;

    await waitFor('.settings-autosave-state.saved');
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    collecting = false;
    await new Promise((resolve) => setTimeout(resolve, 0));
    recordLongTasks(observer.takeRecords());
    observer.disconnect();

    const cueAnimations = document.getAnimations()
      .filter((animation) => animation.effect?.target?.classList?.contains('page-entry-cue'));
    const cueProperties = [...new Set(cueAnimations.flatMap((animation) =>
      animation.effect.getKeyframes().flatMap((frame) => Object.keys(frame))
    ))].filter((property) => !['offset', 'computedOffset', 'easing', 'composite'].includes(property));
    const fullSurfaceAnimation = document.getAnimations().some((animation) =>
      animation.effect?.target?.matches?.('main, .page-cache, .settings-card-grid, .settings-card')
    );

    const main = settings.getBoundingClientRect();
    const cards = [...document.querySelectorAll('.settings-card')];
    const cardBounds = cards.map((card) => card.getBoundingClientRect());
    const initialSpeakerPercent = document.querySelector('.sound-panel .basic-settings-range output')?.textContent.trim();
    const modeButtons = [...document.querySelectorAll('.network-mode-button')];

    const range = document.querySelector('.sound-panel .basic-settings-range input');
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    const initialSpeakerValue = Number.parseInt(initialSpeakerPercent, 10);
    const editedSpeakerValue = initialSpeakerValue === 50 ? 51 : 50;
    valueSetter.call(range, String(editedSpeakerValue));
    range.dispatchEvent(new Event('input', { bubbles: true }));
    await waitFor('.sound-panel .basic-settings-range output', (element) => element.textContent.trim() === editedSpeakerValue + '%');
    await waitFor('.settings-autosave-state.pending');
    await new Promise(requestAnimationFrame);
    const pendingSave = {
      label: document.querySelector('.settings-autosave-state')?.textContent.trim(),
      shieldVisible: Boolean(document.querySelector('.settings-loading-shield')),
      disabledControls: [...document.querySelectorAll('.settings-card input, .settings-card button, .settings-card select')]
        .filter((control) => control.disabled).length
    };
    valueSetter.call(range, String(initialSpeakerValue));
    range.dispatchEvent(new Event('input', { bubbles: true }));
    await waitFor('.sound-panel .basic-settings-range output', (element) => element.textContent.trim() === initialSpeakerPercent);
    await waitFor('.settings-autosave-state.saved');
    await new Promise((resolve) => setTimeout(resolve, 1050));

    const cueBounds = cueAnimations[0]?.effect?.target?.getBoundingClientRect();
    return {
      viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
      destinationRenderedMs,
      maxFrameGapMs: Math.max(0, ...frameGaps),
      longTasks,
      cueCount: cueAnimations.length,
      cueProperties,
      cueAreaRatio: cueBounds ? (cueBounds.width * cueBounds.height) / (innerWidth * innerHeight) : 1,
      fullSurfaceAnimation,
      mainOverflow: Math.max(0, settings.scrollHeight - settings.clientHeight),
      cards: cardBounds.map((bounds) => ({ top: bounds.top, bottom: bounds.bottom, left: bounds.left, right: bounds.right })),
      cardsInsideMain: cardBounds.every((bounds) =>
        bounds.top >= main.top - 1 && bounds.left >= main.left - 1 &&
        bounds.right <= main.right + 1 && bounds.bottom <= main.bottom + 1
      ),
      cardRadius: getComputedStyle(cards[0]).borderRadius,
      minimumModeButtonHeight: Math.min(...modeButtons.map((button) => button.getBoundingClientRect().height)),
      initialSpeakerPercent,
      pendingSave,
      finalSaveLabel: document.querySelector('.settings-autosave-state')?.textContent.trim(),
      finalSpeakerPercent: document.querySelector('.sound-panel .basic-settings-range output')?.textContent.trim()
    };
  })()`);

  if (interceptionError) throw interceptionError;
  result.interceptedApiRequests = apiRequests;
  result.settingsWriteRequests = apiRequests.filter(
    ({ method, path }) => path === "/api/settings/basic" && !["GET", "HEAD"].includes(method)
  );

  if (screenshotPath) {
    await mkdir(dirname(screenshotPath), { recursive: true });
    const screenshot = await cdp("Page.captureScreenshot", {
      format: "png",
      fromSurface: true,
      captureBeyondViewport: false
    });
    await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  }

  console.log(JSON.stringify(result, null, 2));

  assert.deepEqual(result.viewport, { width: 960, height: 600, dpr: 2 });
  assert.equal(result.cards.length, 3, "settings no longer render three logical cards");
  assert.equal(result.cardsInsideMain, true, "settings cards clip outside the main workspace");
  assert.equal(result.mainOverflow, 0, "settings main area overflows at 960x600");
  assert.ok(Number.parseFloat(result.cardRadius) >= 20, "settings cards lost the shared kiosk radius");
  assert.ok(result.minimumModeButtonHeight >= 84, "network mode touch target is too small");
  assert.equal(result.initialSpeakerPercent, "85%", "saved raw gain 230 is not shown using the calibrated scale");
  assert.ok(result.cueCount >= 1, "settings navigation produced no localized page cue");
  assert.deepEqual(result.cueProperties.sort(), ["opacity", "transform"], "page cue animates unsupported properties");
  assert.ok(result.cueAreaRatio < 0.08, "page cue covers too much of the kiosk surface");
  assert.equal(result.fullSurfaceAnimation, false, "settings navigation animates a full surface");
  assert.ok(result.maxFrameGapMs <= 50, `settings navigation frame gap is ${result.maxFrameGapMs.toFixed(1)}ms`);
  assert.ok(result.longTasks.every(({ duration }) => duration < 50), `settings navigation produced long tasks: ${JSON.stringify(result.longTasks)}`);
  assert.equal(result.pendingSave.shieldVisible, false, "autosave still covers the settings workspace");
  assert.equal(result.pendingSave.disabledControls, 0, "autosave still disables all settings controls");
  assert.ok(
    result.interceptedApiRequests.some(({ method, path }) => method === "POST" && path === "/api/fingerprint/wake"),
    "browser API interception did not catch the app startup hardware request"
  );
  assert.deepEqual(result.settingsWriteRequests, [], "settings live test attempted to save its temporary slider value");
  assert.equal(result.finalSaveLabel, "设置已保存");
  assert.equal(result.finalSpeakerPercent, result.initialSpeakerPercent);

} finally {
  await stopBrowser();
}
