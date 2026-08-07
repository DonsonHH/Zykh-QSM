import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { mockDashboard } from "../src/api/mockData.js";

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
  let body = null;
  if (request.postData) {
    try { body = JSON.parse(request.postData); } catch { body = request.postData; }
  }
  apiRequests.push({ method, path: url.pathname, body });
  let payload = { ok: true };
  if (url.pathname === "/api/settings/basic") {
    if (method === "PATCH" && body && typeof body === "object") Object.assign(mockSettings, body);
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
    payload = mockDashboard;
  } else if (url.pathname === "/api/medicines") {
    await delay(90);
    payload = { medicines: [] };
  } else if (url.pathname === "/api/records/summary") {
    await delay(90);
    payload = { summary: { today_service_users: 0, pending_sync_count: 0, local_record_count: 0, today_plan_count: 0 } };
  } else if (url.pathname === "/api/records/recent") {
    await delay(90);
    payload = { records: [] };
  } else if (url.pathname === "/api/records/service-users") {
    await delay(90);
    payload = { users: [] };
  } else if (url.pathname === "/api/records/today-plans") {
    await delay(90);
    payload = { plans: [] };
  } else if (url.pathname === "/api/sync/status") {
    await delay(90);
    payload = { status: "已同步", pending_count: 0 };
  } else if (url.pathname === "/api/qsm/capabilities") {
    payload = { camera: "unavailable", vitals: "available" };
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
    const rangeControls = [...document.querySelectorAll('.basic-settings-range')].map((host) => {
      const hostBounds = host.getBoundingClientRect();
      const inputBounds = host.querySelector('input').getBoundingClientRect();
      return {
        hostTop: hostBounds.top,
        hostBottom: hostBounds.bottom,
        inputTop: inputBounds.top,
        inputBottom: inputBounds.bottom,
        inputHeight: inputBounds.height,
        contained: inputBounds.top >= hostBounds.top - 0.5 && inputBounds.bottom <= hostBounds.bottom + 0.5
      };
    });
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

    valueSetter.call(range, '50');
    range.dispatchEvent(new Event('input', { bubbles: true }));
    await waitFor('.settings-autosave-state.pending');
    await waitFor('.settings-autosave-state.saved');
    const calibratedSavedPercent = document.querySelector('.sound-panel .basic-settings-range output')?.textContent.trim();
    const testButton = document.querySelector('.settings-test-sound');
    testButton.click();
    await waitFor('.settings-test-sound', (element) => !element.disabled && element.textContent.includes('测试外放'));

    valueSetter.call(range, String(initialSpeakerValue));
    range.dispatchEvent(new Event('input', { bubbles: true }));
    await waitFor('.settings-autosave-state.pending');
    await waitFor('.settings-autosave-state.saved');

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
      rangeControls,
      idleSelectHeight: document.querySelector('.idle-time-setting select')?.getBoundingClientRect().height || 0,
      minimumModeButtonHeight: Math.min(...modeButtons.map((button) => button.getBoundingClientRect().height)),
      initialSpeakerPercent,
      calibratedSavedPercent,
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
  result.beepRequests = apiRequests.filter(
    ({ method, path }) => method === "POST" && path === "/api/audio/beep"
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

  result.navigation = await evaluate(`(async () => {
    const waitFor = async (selector, predicate = () => true) => {
      const deadline = performance.now() + 5000;
      while (performance.now() < deadline) {
        const element = document.querySelector(selector);
        if (element && predicate(element)) return element;
        await new Promise(requestAnimationFrame);
      }
      throw new Error('Timed out waiting for ' + selector);
    };
    const navButton = (label) => [...document.querySelectorAll('.bottom-nav button')]
      .find((button) => button.textContent.trim() === label);
    const animationProperties = (animation) => [...new Set(animation.effect.getKeyframes().flatMap((frame) =>
      Object.keys(frame).filter((key) => !['offset', 'computedOffset', 'easing', 'composite'].includes(key))
    ))];
    const measure = async (name, trigger, destinationSelector) => {
      const longTasks = [];
      const observer = new PerformanceObserver((list) => {
        longTasks.push(...list.getEntries().map(({ duration, startTime }) => ({ duration, startTime })));
      });
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
      const control = typeof trigger === 'function' ? trigger() : document.querySelector(trigger);
      if (!control) throw new Error('Missing route trigger for ' + name);
      control.click();
      await waitFor(destinationSelector);
      await new Promise(requestAnimationFrame);
      const destinationRenderedMs = performance.now() - startedAt;

      let cueAnimation = null;
      let fallbackCueAnimation = null;
      const cueDeadline = performance.now() + 280;
      while (performance.now() < cueDeadline && !cueAnimation) {
        const activeAnimations = document.getAnimations();
        cueAnimation = activeAnimations.find((animation) =>
          animation.effect?.target?.matches?.('.page-entry-cue, .admin-section-entry-cue')
        );
        fallbackCueAnimation ||= activeAnimations.find((animation) => animation.effect?.target?.matches?.('.bottom-nav-icon'));
        if (!cueAnimation) await new Promise(requestAnimationFrame);
      }
      cueAnimation ||= fallbackCueAnimation;
      const cueTarget = cueAnimation?.effect?.target;
      const cueBounds = cueTarget?.getBoundingClientRect();
      const cue = cueAnimation ? {
        target: cueTarget.className?.baseVal || cueTarget.className || cueTarget.tagName,
        properties: animationProperties(cueAnimation),
        areaRatio: cueBounds ? (cueBounds.width * cueBounds.height) / (innerWidth * innerHeight) : 1
      } : null;
      const fullSurfaceAnimation = document.getAnimations().some((animation) =>
        animation.effect?.target?.matches?.('main, .page-cache, .admin-workspace, .records-main-grid, .settings-card-grid')
      );

      await new Promise((resolve) => setTimeout(resolve, 390));
      collecting = false;
      await new Promise((resolve) => setTimeout(resolve, 0));
      longTasks.push(...observer.takeRecords().map(({ duration, startTime }) => ({ duration, startTime })));
      observer.disconnect();
      return {
        name,
        destinationRenderedMs,
        maxFrameGapMs: Math.max(0, ...frameGaps),
        longTasks,
        cue,
        fullSurfaceAnimation
      };
    };

    const samples = [];
    samples.push(await measure('settings-home', '.basic-settings-header .icon-action', '.home-page-cache.active .home-page'));
    samples.push(await measure('home-medicines', () => navButton('药品'), '.medicines-page-cache.active .medicines-page'));
    samples.push(await measure('medicines-scan', '.medicines-page-cache.active .scan-button', '.scan-page'));
    samples.push(await measure('scan-home', '.scan-heading .icon-action', '.home-page-cache.active .home-page'));
    samples.push(await measure('home-vitals', 'button[aria-label="开始身体状态测量"]', '.vitals-page'));
    samples.push(await measure('vitals-home', '.vitals-back-button', '.home-page-cache.active .home-page'));
    samples.push(await measure('home-inquiry', () => navButton('问询'), '.inquiry-page'));
    samples.push(await measure('inquiry-records', () => navButton('记录'), '.records-page'));
    samples.push(await measure('records-home', () => navButton('首页'), '.home-page-cache.active .home-page'));
    samples.push(await measure('home-settings', '.system-check-button', '.settings-page-cache.active .basic-settings-page'));
    samples.push(await measure('settings-admin', '.admin-entry-button', '.admin-login-page'));
    samples.push(await measure('admin-settings', '.admin-login-exit', '.settings-page-cache.active .basic-settings-page'));
    return samples;
  })()`);

  await cdp("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-motion", value: "reduce" }]
  });
  result.reducedMotionNavigation = await evaluate(`(async () => {
    const button = document.querySelector('.basic-settings-header .icon-action');
    button.click();
    const deadline = performance.now() + 3000;
    while (performance.now() < deadline && !document.querySelector('.home-page-cache.active .home-page')) {
      await new Promise(requestAnimationFrame);
    }
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return {
      transitionMarker: document.documentElement.dataset.pageTransition || '',
      cueAnimations: document.getAnimations().filter((animation) =>
        animation.effect?.target?.matches?.('.page-entry-cue, .bottom-nav-icon')
      ).map((animation) => animation.animationName).filter(Boolean)
    };
  })()`);

  await cdp("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-motion", value: "no-preference" }]
  });
  await cdp("Page.navigate", { url: `${baseUrl}/?page=home` });
  await waitForApp();
  await delay(180);
  result.idleMotion = await evaluate(`(async () => {
    const longTasks = [];
    const observer = new PerformanceObserver((list) => {
      longTasks.push(...list.getEntries().map(({ duration, startTime }) => ({ duration, startTime })));
    });
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

    const animations = document.getAnimations().filter((animation) =>
      animation.effect?.target?.matches?.('.idle-wake-button, .idle-wake-glyph, .idle-wake-area h1')
    );
    const properties = [...new Set(animations.flatMap((animation) => animation.effect.getKeyframes().flatMap((frame) =>
      Object.keys(frame).filter((key) => !['offset', 'computedOffset', 'easing', 'composite'].includes(key))
    )))];
    await new Promise((resolve) => setTimeout(resolve, 3800));
    collecting = false;
    await new Promise((resolve) => setTimeout(resolve, 0));
    longTasks.push(...observer.takeRecords().map(({ duration, startTime }) => ({ duration, startTime })));
    observer.disconnect();
    return {
      count: animations.length,
      properties,
      fullSurfaceAnimation: document.getAnimations().some((animation) => animation.effect?.target?.matches?.('.idle-screen')),
      maxFrameGapMs: Math.max(0, ...frameGaps),
      longTasks
    };
  })()`);

  await cdp("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-motion", value: "reduce" }]
  });
  await cdp("Page.navigate", { url: `${baseUrl}/?page=home` });
  await waitForApp();
  await delay(100);
  result.reducedIdleAnimationCount = await evaluate(`document.getAnimations().filter((animation) =>
    animation.effect?.target?.matches?.('.idle-wake-button, .idle-wake-glyph, .idle-wake-area h1')
  ).length`);

  console.log(JSON.stringify(result, null, 2));

  assert.deepEqual(result.viewport, { width: 960, height: 600, dpr: 2 });
  assert.equal(result.cards.length, 3, "settings no longer render three logical cards");
  assert.equal(result.cardsInsideMain, true, "settings cards clip outside the main workspace");
  assert.equal(result.mainOverflow, 0, "settings main area overflows at 960x600");
  assert.ok(Number.parseFloat(result.cardRadius) >= 20, "settings cards lost the shared kiosk radius");
  assert.ok(result.minimumModeButtonHeight >= 84, "network mode touch target is too small");
  assert.ok(result.rangeControls.every(({ contained }) => contained), "a range input overflows its visible control");
  assert.ok(result.rangeControls.every(({ inputHeight }) => inputHeight >= 44), "a range input is below the 44px touch target");
  assert.ok(result.idleSelectHeight >= 44, "idle-time selector is below the 44px touch target");
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
  assert.equal(result.calibratedSavedPercent, "50%", "calibrated slider did not remain stable after autosave");
  assert.deepEqual(
    result.settingsWriteRequests.map(({ body }) => body?.speaker_volume),
    [180, 230],
    "isolated autosave did not persist 50% as raw 180 and restore the original raw 230"
  );
  assert.deepEqual(
    result.beepRequests.map(({ body }) => body?.volume),
    [180],
    "isolated speaker test did not send the same calibrated raw 180"
  );
  assert.equal(result.finalSaveLabel, "设置已保存");
  assert.equal(result.finalSpeakerPercent, result.initialSpeakerPercent);
  assert.equal(result.navigation.length, 12, "live motion coverage lost a kiosk route");
  for (const sample of result.navigation) {
    assert.ok(sample.cue, `${sample.name} produced no localized transition cue`);
    assert.deepEqual(sample.cue.properties.sort(), ["opacity", "transform"], `${sample.name} cue animates unsupported properties`);
    assert.ok(sample.cue.areaRatio < 0.12, `${sample.name} cue covers too much of the kiosk surface`);
    assert.equal(sample.fullSurfaceAnimation, false, `${sample.name} animates a full kiosk surface`);
    assert.ok(sample.maxFrameGapMs <= 67, `${sample.name} frame gap is ${sample.maxFrameGapMs.toFixed(1)}ms`);
    assert.ok(sample.longTasks.every(({ duration }) => duration < 50), `${sample.name} produced long tasks: ${JSON.stringify(sample.longTasks)}`);
  }
  assert.deepEqual(result.reducedMotionNavigation, { transitionMarker: "", cueAnimations: [] });
  assert.ok(result.idleMotion.count >= 1, "idle screen has no localized motion cue");
  assert.ok(result.idleMotion.properties.every((property) => ["opacity", "transform"].includes(property)), "idle screen animates unsupported properties");
  assert.equal(result.idleMotion.fullSurfaceAnimation, false, "idle screen animates its full surface");
  assert.ok(result.idleMotion.maxFrameGapMs <= 50, `idle breathing frame gap is ${result.idleMotion.maxFrameGapMs.toFixed(1)}ms`);
  assert.ok(result.idleMotion.longTasks.every(({ duration }) => duration < 50), `idle breathing produced long tasks: ${JSON.stringify(result.idleMotion.longTasks)}`);
  assert.equal(result.reducedIdleAnimationCount, 0, "idle motion ignores reduced-motion preference");

} finally {
  await stopBrowser();
}
