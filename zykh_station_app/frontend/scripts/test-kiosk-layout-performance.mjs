import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const baseUrl = process.env.QA_BASE_URL || "http://127.0.0.1:4173";
const chromiumBin = process.env.CHROMIUM_BIN || "chromium";
const browserWindowWidth = Number(process.env.QA_WINDOW_WIDTH || 1920);
const browserWindowHeight = Number(process.env.QA_WINDOW_HEIGHT || 1200);
const deviceScaleFactor = Number(process.env.QA_DEVICE_SCALE_FACTOR || 2);
const navigationCycles = Math.max(1, Number(process.env.QA_NAVIGATION_CYCLES || 2));
const navigationSettleMs = Math.max(0, Number(process.env.QA_NAVIGATION_SETTLE_MS || 250));
const performanceOnly = process.env.QA_PERFORMANCE_ONLY === "1";
const modalOnly = process.env.QA_MODAL_ONLY === "1";
const skipNavigation = process.env.QA_SKIP_NAVIGATION === "1";
const idleObserveMs = Math.max(0, Number(process.env.QA_IDLE_OBSERVE_MS || 36000));
const headful = process.env.QA_HEADFUL === "1";
const safeGraphics = process.env.QA_SAFE_GRAPHICS !== "0";
const requireApi = process.env.QA_REQUIRE_API !== "0";
const screenshotDir = process.env.QA_SCREENSHOT_DIR
  ? join(frontendRoot, process.env.QA_SCREENSHOT_DIR)
  : "";
const profileDir = await mkdtemp(join(tmpdir(), "zykh-chrome-kiosk-ui-"));
const debuggingPort = 9300 + Math.floor(Math.random() * 500);
const browserArgs = [
  "--no-sandbox",
  "--hide-scrollbars",
  "--disable-background-timer-throttling",
  "--disable-backgrounding-occluded-windows",
  "--disable-renderer-backgrounding",
  "--remote-allow-origins=*",
  `--remote-debugging-port=${debuggingPort}`,
  `--user-data-dir=${profileDir}`,
  `--window-size=${browserWindowWidth},${browserWindowHeight}`,
  `--force-device-scale-factor=${deviceScaleFactor}`,
  `${baseUrl}/?page=home&awake=1`
];
if (!headful) browserArgs.unshift("--headless=new");
else browserArgs.unshift("--ozone-platform=x11", "--window-position=0,0");
if (safeGraphics) {
  browserArgs.splice(browserArgs.length - 1, 0, "--disable-gpu", "--disable-accelerated-2d-canvas");
}
const browser = spawn(
  chromiumBin,
  browserArgs,
  { stdio: "ignore" }
);

let socket;
let nextMessageId = 0;
const pending = new Map();

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function removeProfileDirectory() {
  let lastError;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      await rm(profileDir, { recursive: true, force: true, maxRetries: 2, retryDelay: 50 });
      return;
    } catch (error) {
      lastError = error;
      await delay(100);
    }
  }
  throw lastError;
}

async function stopBrowser() {
  if (browser.exitCode !== null || browser.signalCode !== null) return;
  let exited = false;
  const exitPromise = new Promise((resolve) => {
    browser.once("exit", () => {
      exited = true;
      resolve();
    });
  });
  browser.kill("SIGTERM");
  await Promise.race([exitPromise, delay(1500)]);
  if (!exited && browser.exitCode === null && browser.signalCode === null) {
    browser.kill("SIGKILL");
    await Promise.race([exitPromise, delay(1500)]);
  }
}

async function waitForTarget() {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${debuggingPort}/json/list`);
      const targets = await response.json();
      const page = targets.find((target) => target.type === "page");
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch {
      // Chromium is still starting.
    }
    await delay(50);
  }
  throw new Error("Chromium DevTools target did not become ready");
}

async function connect(url) {
  return new Promise((resolve, reject) => {
    socket = new WebSocket(url);
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !pending.has(message.id)) return;
      const { resolve: resolveMessage, reject: rejectMessage } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) rejectMessage(new Error(message.error.message));
      else resolveMessage(message.result || {});
    });
  });
}

async function cdp(method, params = {}) {
  const id = ++nextMessageId;
  const response = new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
  socket.send(JSON.stringify({ id, method, params }));
  return response;
}

async function evaluate(expression) {
  const response = await cdp("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true
  });
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.text || "Browser evaluation failed");
  }
  return response.result?.value;
}

async function waitForApp() {
  const deadline = Date.now() + 8_000;
  while (Date.now() < deadline) {
    const ready = await evaluate(
      "document.readyState === 'complete' && Boolean(document.querySelector('.kiosk-frame'))"
    );
    if (ready) {
      await delay(350);
      return;
    }
    await delay(40);
  }
  throw new Error("Kiosk app did not render");
}

async function navigate(page, awake = true) {
  const query = new URLSearchParams({ page });
  if (awake) query.set("awake", "1");
  await cdp("Page.navigate", { url: `${baseUrl}/?${query}` });
  await waitForApp();
  await evaluate("window.scrollTo(0, 0)");
}

async function verifyMedicineKeyboardNavigation() {
  const deadline = Date.now() + 8_000;
  while (Date.now() < deadline) {
    const ready = await evaluate("Boolean(document.querySelector('.medicine-grid [role=option]'))");
    if (ready) break;
    await delay(50);
  }
  return evaluate(`(async () => {
    const selected = document.querySelector('.medicine-grid [role=option][aria-selected="true"]');
    if (!selected) return { ready: false };
    selected.focus();
    selected.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await new Promise((resolve) => setTimeout(resolve, 50));
    const grid = document.querySelector('.medicine-grid');
    const last = grid?.querySelector('[data-medicine-index="22"]');
    const gridBounds = grid?.getBoundingClientRect();
    const lastBounds = last?.getBoundingClientRect();
    return {
      ready: true,
      selected: last?.getAttribute('aria-selected') === 'true',
      focused: document.activeElement === last,
      position: last?.getAttribute('aria-posinset'),
      setSize: last?.getAttribute('aria-setsize'),
      visible: Boolean(gridBounds && lastBounds &&
        lastBounds.top >= gridBounds.top - 1 && lastBounds.bottom <= gridBounds.bottom + 1)
    };
  })()`);
}

async function verifyMedicineCacheLifecycle() {
  return evaluate(`(async () => {
    const waitFor = async (selector) => {
      const deadline = performance.now() + 5000;
      while (performance.now() < deadline) {
        const element = document.querySelector(selector);
        if (element) return element;
        await new Promise(requestAnimationFrame);
      }
      throw new Error('Timed out waiting for ' + selector);
    };
    (await waitFor('.system-check-button')).click();
    (await waitFor('.admin-entry-button')).click();
    await waitFor('.admin-login-panel');
    const cachePresentDuringAdmin = Boolean(document.querySelector('.medicines-page-cache'));
    (await waitFor('.admin-login-exit')).click();
    await waitFor('.basic-settings-page');
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await new Promise((resolve) => setTimeout(resolve, 350));
    return {
      cachePresentDuringAdmin,
      cachePresentAfterExit: Boolean(document.querySelector('.medicines-page-cache'))
    };
  })()`);
}

async function verifyMedicineModalCoverage() {
  return evaluate(`(async () => {
    const waitFor = async (selector) => {
      const deadline = performance.now() + 5000;
      while (performance.now() < deadline) {
        const element = document.querySelector(selector);
        if (element) return element;
        await new Promise(requestAnimationFrame);
      }
      throw new Error('Timed out waiting for ' + selector);
    };
    const current = await waitFor('.medicine-grid [role=option][aria-selected="true"]');
    current.focus();
    current.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    const first = await waitFor('.medicine-grid [data-medicine-index="0"][aria-selected="true"]');
    const visibleMedicine = first.querySelector('.medicine-card-copy > strong')?.textContent.trim() || '';
    const detailDeadline = performance.now() + 5000;
    while (performance.now() < detailDeadline) {
      const heading = document.querySelector('.detail-heading h2')?.textContent.trim();
      const action = document.querySelector('.detail-action');
      if (heading === visibleMedicine && action && !action.disabled) break;
      await new Promise(requestAnimationFrame);
    }
    const frameGaps = [];
    let previousFrame = 0;
    let collecting = true;
    const tick = (timestamp) => {
      if (previousFrame) frameGaps.push(timestamp - previousFrame);
      previousFrame = timestamp;
      if (collecting) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    await new Promise(requestAnimationFrame);
    const startedAt = performance.now();
    (await waitFor('.detail-action')).click();
    const layer = await waitFor('.modal-layer');
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    collecting = false;
    const frame = document.querySelector('.kiosk-frame').getBoundingClientRect();
    const bounds = layer.getBoundingClientRect();
    const navBounds = document.querySelector('.bottom-nav').getBoundingClientRect();
    const navigationHit = document.elementFromPoint(
      navBounds.left + navBounds.width / 2,
      navBounds.top + navBounds.height / 2
    );
    const dialogMedicine = document.querySelector('#dispense-title')?.textContent.trim() || '';
    const result = {
      coversFrame: Math.abs(bounds.top - frame.top) <= 1 && Math.abs(bounds.left - frame.left) <= 1 &&
        Math.abs(bounds.right - frame.right) <= 1 && Math.abs(bounds.bottom - frame.bottom) <= 1,
      capturesNavigation: navigationHit === layer || layer.contains(navigationHit),
      medicineMatches: visibleMedicine === dialogMedicine,
      backdropFilter: getComputedStyle(layer).backdropFilter || getComputedStyle(layer).webkitBackdropFilter || 'none',
      openMs: performance.now() - startedAt,
      maxFrameGapMs: Math.max(0, ...frameGaps)
    };
    document.querySelector('.modal-close')?.click();
    return result;
  })()`);
}

async function verifyHomeTaskPickerPerformance() {
  return evaluate(`(async () => {
    const waitFor = async (selector) => {
      const deadline = performance.now() + 5000;
      while (performance.now() < deadline) {
        const element = document.querySelector(selector);
        if (element) return element;
        await new Promise(requestAnimationFrame);
      }
      throw new Error('Timed out waiting for ' + selector);
    };
    const trigger = await waitFor('.home-plan-picker-trigger');
    const frameGaps = [];
    let previousFrame = 0;
    let collecting = true;
    const tick = (timestamp) => {
      if (previousFrame) frameGaps.push(timestamp - previousFrame);
      previousFrame = timestamp;
      if (collecting) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    await new Promise(requestAnimationFrame);
    const startedAt = performance.now();
    trigger.click();
    const layer = await waitFor('.home-task-picker-layer');
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    collecting = false;
    const result = {
      openMs: performance.now() - startedAt,
      maxFrameGapMs: Math.max(0, ...frameGaps),
      backdropFilter: getComputedStyle(layer).backdropFilter || getComputedStyle(layer).webkitBackdropFilter || 'none'
    };
    document.querySelector('.home-task-picker-close')?.click();
    return result;
  })()`);
}

async function openAdminConsole(pin) {
  await navigate("admin");
  const readinessDeadline = Date.now() + 5_000;
  while (Date.now() < readinessDeadline) {
    const state = await evaluate(`(() => ({
      authenticated: Boolean(document.querySelector('.admin-console')),
      loginReady: Boolean(document.querySelector('.admin-login-panel input'))
    }))()`);
    if (state.authenticated) {
      await delay(350);
      return;
    }
    if (state.loginReady) break;
    await delay(50);
  }
  await evaluate(`(() => {
    const input = document.querySelector('.admin-login-panel input');
    if (!input) throw new Error('Admin PIN input is unavailable');
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    valueSetter.call(input, ${JSON.stringify(pin)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await delay(40);
  await evaluate("document.querySelector('.admin-login-panel form')?.requestSubmit()");
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    if (await evaluate("Boolean(document.querySelector('.admin-console'))")) {
      await delay(350);
      return;
    }
    await delay(50);
  }
  throw new Error("Admin console did not open with the supplied QA_ADMIN_PIN");
}

async function capture(name) {
  if (!screenshotDir) return;
  await mkdir(screenshotDir, { recursive: true });
  await cdp("Page.bringToFront");
  await evaluate("new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
  await delay(80);
  const screenshot = await cdp("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false
  });
  await writeFile(join(screenshotDir, `${name}.png`), Buffer.from(screenshot.data, "base64"));
}

async function readLayout() {
  return evaluate(`(() => {
    const frameElement = document.querySelector('.kiosk-frame');
    const frame = frameElement.getBoundingClientRect();
    const frameStyle = getComputedStyle(frameElement);
    const mainElement = document.querySelector(
      '.kiosk-frame > main, .kiosk-frame > .page-cache.active > main'
    );
    const main = mainElement?.getBoundingClientRect();
    const animationNames = {};
    for (const animation of document.getAnimations()) {
      const name = animation.animationName || 'web-animation';
      animationNames[name] = (animationNames[name] || 0) + 1;
    }
    const criticalClipping = [...document.querySelectorAll(
      '.vitals-pose-card > .vitals-pose-graphic, .vitals-pose-card > .vitals-pose-label'
    )].flatMap((element) => {
      const container = element.closest('.vitals-pose-card');
      const bounds = element.getBoundingClientRect();
      const containerBounds = container?.getBoundingClientRect();
      if (!containerBounds) return [];
      const clipped = bounds.top < containerBounds.top - 1 ||
        bounds.left < containerBounds.left - 1 ||
        bounds.right > containerBounds.right + 1 ||
        bounds.bottom > containerBounds.bottom + 1;
      return clipped ? [element.className] : [];
    });
    const inquiryFacts = document.querySelector('.inquiry-fact-list')?.getBoundingClientRect();
    const inquiryVitals = document.querySelector('.inquiry-core-vitals')?.getBoundingClientRect();
    if (inquiryFacts && inquiryVitals && inquiryFacts.bottom > inquiryVitals.top + 1) {
      criticalClipping.push('inquiry-facts-overlap-vitals');
    }
    for (const element of document.querySelectorAll(
      '.basic-settings-panel, .admin-login-panel, .admin-sidebar, .admin-workspace, .idle-brand, .idle-wake-area'
    )) {
      const bounds = element.getBoundingClientRect();
      const clipped = bounds.top < -1 || bounds.left < -1 ||
        bounds.right > window.innerWidth + 1 || bounds.bottom > window.innerHeight + 1;
      if (clipped) criticalClipping.push(element.className || element.tagName.toLowerCase());
    }
    const topBar = document.querySelector('.top-bar')?.getBoundingClientRect();
    const bottomNav = document.querySelector('.bottom-nav')?.getBoundingClientRect();
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight, dpr: window.devicePixelRatio },
      scroll: { x: window.scrollX, y: window.scrollY },
      frame: { top: frame.top, bottom: frame.bottom, width: frame.width, height: frame.height },
      mainHeight: main?.height || 0,
      mainOverflow: mainElement ? Math.max(0, mainElement.scrollHeight - mainElement.clientHeight) : 0,
      verticalFill: frame.height / window.innerHeight,
      outerTop: frame.top,
      outerBottom: window.innerHeight - frame.bottom,
      outerLeft: frame.left,
      outerRight: window.innerWidth - frame.right,
      zoom: frameStyle.zoom,
      transform: frameStyle.transform,
      activeAnimations: document.getAnimations().length,
      animationNames,
      shellChrome: {
        topBar: topBar ? { top: topBar.top, bottom: topBar.bottom } : null,
        bottomNav: bottomNav ? { top: bottomNav.top, bottom: bottomNav.bottom } : null
      },
      criticalClipping
    };
  })()`);
}

async function measureNavigation() {
  return evaluate(`(async () => {
    const route = [
      { label: '药品', page: 'medicines' },
      { label: '问询', page: 'inquiry' },
      { label: '记录', page: 'records' },
      { label: '首页', page: 'home' }
    ];
    const destinations = Array.from({ length: ${navigationCycles} }, () => route).flat();
    const measurements = [];
    const visits = {};
    const longTasks = [];
    const longAnimationFrames = [];
    const observers = [];
    if (PerformanceObserver.supportedEntryTypes.includes('longtask')) {
      const observer = new PerformanceObserver((list) => {
        longTasks.push(...list.getEntries().map(({ startTime, duration }) => ({ startTime, duration })));
      });
      observer.observe({ type: 'longtask' });
      observers.push(observer);
    }
    if (PerformanceObserver.supportedEntryTypes.includes('long-animation-frame')) {
      const observer = new PerformanceObserver((list) => {
        longAnimationFrames.push(...list.getEntries().map(({ startTime, duration, blockingDuration, scripts }) => ({
          startTime,
          duration,
          blockingDuration,
          scripts: (scripts || []).map((script) => ({
            sourceURL: script.sourceURL,
            functionName: script.functionName,
            duration: script.duration,
            forcedStyleAndLayoutDuration: script.forcedStyleAndLayoutDuration,
            invoker: script.invoker,
            invokerType: script.invokerType
          }))
        })));
      });
      observer.observe({ type: 'long-animation-frame' });
      observers.push(observer);
    }
    for (const { label, page } of destinations) {
      visits[page] = (visits[page] || 0) + 1;
      const button = [...document.querySelectorAll('.bottom-nav button')]
        .find((candidate) => candidate.textContent.includes(label));
      if (!button) throw new Error('Missing navigation button: ' + label);
      const frameGaps = [];
      let lastFrame = 0;
      let collecting = true;
      const tick = (timestamp) => {
        if (lastFrame) frameGaps.push(timestamp - lastFrame);
        lastFrame = timestamp;
        if (collecting) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      await new Promise(requestAnimationFrame);
      const startedAt = performance.now();
      button.click();
      const usedNativeViewTransition = Boolean(document.activeViewTransition);
      const deadline = performance.now() + 1000;
      let renderedAt = 0;
      while (performance.now() < deadline) {
        await new Promise(requestAnimationFrame);
        const activeButton = document.querySelector('.bottom-nav button[aria-current="page"]');
        if (activeButton !== button) continue;
        if (!renderedAt) renderedAt = performance.now();
        const feedbackAnimations = button.querySelector('.bottom-nav-icon')?.getAnimations({ subtree: true }) || [];
        const transitionIsRunning = feedbackAnimations.some((animation) =>
          animation.animationName?.startsWith('kiosk-nav-confirm-') &&
          animation.playState !== 'finished'
        );
        if (!transitionIsRunning) break;
      }
      if (document.querySelector('.bottom-nav button[aria-current="page"]') !== button) {
        throw new Error('Navigation did not render destination page: ' + page);
      }
      const completedAt = performance.now();
      if (${navigationSettleMs} > 0) {
        await new Promise((resolve) => setTimeout(resolve, ${navigationSettleMs}));
      }
      collecting = false;
      measurements.push({
        label,
        page,
        visit: visits[page],
        destinationRenderedMs: renderedAt - startedAt,
        elapsedMs: completedAt - startedAt,
        maxFrameGapMs: Math.max(0, ...frameGaps),
        usedNativeViewTransition
      });
    }
    await new Promise(requestAnimationFrame);
    observers.forEach((observer) => observer.disconnect());
    return { samples: measurements, longTasks, longAnimationFrames };
  })()`);
}

async function observeIdleWork() {
  if (!idleObserveMs) return null;
  return evaluate(`(async () => {
    performance.clearResourceTimings();
    const startedAt = performance.now();
    const frameGaps = [];
    const longTasks = [];
    const longAnimationFrames = [];
    const observers = [];
    if (PerformanceObserver.supportedEntryTypes.includes('longtask')) {
      const observer = new PerformanceObserver((list) => {
        longTasks.push(...list.getEntries().filter(({ startTime }) => startTime >= startedAt).map(({ startTime, duration }) => ({
          atMs: startTime - startedAt,
          duration
        })));
      });
      observer.observe({ type: 'longtask' });
      observers.push(observer);
    }
    if (PerformanceObserver.supportedEntryTypes.includes('long-animation-frame')) {
      const observer = new PerformanceObserver((list) => {
        longAnimationFrames.push(...list.getEntries()
          .filter(({ startTime }) => startTime >= startedAt)
          .map(({ startTime, duration, blockingDuration, scripts }) => ({
          atMs: startTime - startedAt,
          duration,
          blockingDuration,
          scripts: (scripts || []).map((script) => ({
            sourceURL: script.sourceURL,
            functionName: script.functionName,
            duration: script.duration,
            forcedStyleAndLayoutDuration: script.forcedStyleAndLayoutDuration,
            invoker: script.invoker,
            invokerType: script.invokerType
          }))
        })));
      });
      observer.observe({ type: 'long-animation-frame' });
      observers.push(observer);
    }
    let previousFrame = 0;
    let collecting = true;
    const tick = (timestamp) => {
      if (previousFrame) frameGaps.push({ atMs: timestamp - startedAt, duration: timestamp - previousFrame });
      previousFrame = timestamp;
      if (collecting) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    await new Promise((resolve) => setTimeout(resolve, ${idleObserveMs}));
    collecting = false;
    await new Promise(requestAnimationFrame);
    observers.forEach((observer) => observer.disconnect());
    return {
      durationMs: performance.now() - startedAt,
      slowFrames: frameGaps.filter(({ duration }) => duration > 34),
      maxFrameGapMs: Math.max(0, ...frameGaps.map(({ duration }) => duration)),
      longTasks,
      longAnimationFrames,
      resources: performance.getEntriesByType('resource')
        .filter(({ name, startTime }) => name.includes('/api/') && startTime >= startedAt)
        .map(({ name, startTime, duration }) => ({
          path: new URL(name).pathname,
          atMs: startTime - startedAt,
          duration
        }))
    };
  })()`);
}

function parseViewports(value) {
  if (!value) {
    // The production panel is 1920x1200 at Chromium DPR 2: 960x600 CSS pixels.
    return [{ width: 960, height: 600 }];
  }
  return value.split(",").map((entry) => {
    const match = entry.trim().match(/^(\d+)x(\d+)$/);
    if (!match) throw new Error(`Invalid QA_VIEWPORTS entry: ${entry}`);
    return { width: Number(match[1]), height: Number(match[2]) };
  });
}

function metricMap(metrics) {
  return Object.fromEntries((metrics || []).map(({ name, value }) => [name, value]));
}

function metricDelta(before, after, name) {
  return (after[name] || 0) - (before[name] || 0);
}

try {
  await connect(await waitForTarget());
  await cdp("Page.enable");
  await cdp("Runtime.enable");
  await cdp("Performance.enable");
  if (process.env.QA_REDUCED_MOTION === "1") {
    await cdp("Emulation.setEmulatedMedia", {
      features: [{ name: "prefers-reduced-motion", value: "reduce" }]
    });
  }

  await waitForApp();
  const apiHealth = await evaluate(`Promise.all(['/api/dashboard', '/api/records/summary'].map(async (path) => {
    try {
      const response = await fetch(path);
      return { path, ok: response.ok, status: response.status };
    } catch {
      return { path, ok: false, status: 0 };
    }
  }))`);
  if (requireApi) {
    assert.ok(
      apiHealth.every(({ ok }) => ok),
      `required kiosk APIs are unavailable: ${JSON.stringify(apiHealth)}`
    );
  }
  const developmentBuild = await evaluate(`[...document.scripts].some(({ src }) =>
    src.includes('/@vite/client') || src.includes('/src/') || src.includes('react-dom_client')
  )`);
  const nativeBrowserLayout = await readLayout();
  const viewports = parseViewports(process.env.QA_VIEWPORTS);
  const pages = ["home", "medicines", "inquiry", "records", "scan", "vitals", "settings", "admin", "idle"];
  const layouts = {};
  for (const viewport of performanceOnly ? [] : viewports) {
    const viewportKey = `${viewport.width}x${viewport.height}`;
    await cdp("Emulation.setDeviceMetricsOverride", {
      ...viewport,
      deviceScaleFactor,
      mobile: false
    });
    layouts[viewportKey] = {};
    for (const page of pages) {
      await navigate(page === "idle" ? "home" : page, page !== "idle");
      layouts[viewportKey][page] = await readLayout();
      await capture(`${page}-${viewportKey}`);
    }
  }

  let medicineKeyboardNavigation = null;
  let medicineModalCoverage = null;
  let medicineCacheLifecycle = null;
  let homeTaskPickerPerformance = null;
  if (!performanceOnly) {
    await navigate("home");
    homeTaskPickerPerformance = await verifyHomeTaskPickerPerformance();
    await navigate("medicines");
    medicineKeyboardNavigation = modalOnly ? null : await verifyMedicineKeyboardNavigation();
    medicineModalCoverage = await verifyMedicineModalCoverage();
    medicineCacheLifecycle = modalOnly ? null : await verifyMedicineCacheLifecycle();
  }

  const adminConsoleLayouts = {};
  if (!performanceOnly && process.env.QA_ADMIN_PIN) {
    for (const viewport of viewports) {
      const viewportKey = `${viewport.width}x${viewport.height}`;
      await cdp("Emulation.setDeviceMetricsOverride", {
        ...viewport,
        deviceScaleFactor,
        mobile: false
      });
      await openAdminConsole(process.env.QA_ADMIN_PIN);
      adminConsoleLayouts[viewportKey] = await readLayout();
      await capture(`admin-console-${viewportKey}`);
    }
  }

  const performanceViewport = viewports.at(-1);
  await cdp("Emulation.setDeviceMetricsOverride", {
    ...performanceViewport,
    deviceScaleFactor,
    mobile: false
  });
  await navigate(idleObserveMs ? "records" : "home");
  const idleObservation = await observeIdleWork();
  if (idleObservation) idleObservation.page = "records";
  await navigate("home");
  const metricsBefore = metricMap((await cdp("Performance.getMetrics")).metrics);
  const navigationResult = skipNavigation
    ? { samples: [], longTasks: [], longAnimationFrames: [] }
    : await measureNavigation();
  const metricsAfter = metricMap((await cdp("Performance.getMetrics")).metrics);
  const navigation = navigationResult.samples;
  const performanceMetrics = {
    layoutCount: metricDelta(metricsBefore, metricsAfter, "LayoutCount"),
    recalcStyleCount: metricDelta(metricsBefore, metricsAfter, "RecalcStyleCount"),
    scriptDurationMs: metricDelta(metricsBefore, metricsAfter, "ScriptDuration") * 1000,
    taskDurationMs: metricDelta(metricsBefore, metricsAfter, "TaskDuration") * 1000,
    jsHeapDeltaBytes: metricDelta(metricsBefore, metricsAfter, "JSHeapUsedSize")
  };
  const report = {
    nativeBrowserLayout,
    browserConfiguration: {
      window: `${browserWindowWidth}x${browserWindowHeight}`,
      deviceScaleFactor,
      safeGraphics,
      developmentBuild,
      apiHealth,
      headful,
      navigationCycles,
      navigationSettleMs,
      performanceOnly,
      modalOnly,
      skipNavigation,
      idleObserveMs
    },
    layouts,
    medicineKeyboardNavigation,
    medicineModalCoverage,
    medicineCacheLifecycle,
    homeTaskPickerPerformance,
    adminConsoleLayouts,
    navigation,
    longTasks: navigationResult.longTasks,
    longAnimationFrames: navigationResult.longAnimationFrames,
    performanceMetrics,
    idleObservation
  };
  if (process.env.QA_REPORT_SUMMARY === "1") {
    process.stdout.write(`${JSON.stringify({
      browserConfiguration: report.browserConfiguration,
      navigation: {
        samples: navigation.length,
        slowestDestinationRenderMs: Math.max(0, ...navigation.map((sample) => sample.destinationRenderedMs)),
        slowestTransitionMs: Math.max(0, ...navigation.map((sample) => sample.elapsedMs)),
        largestFrameGapMs: Math.max(0, ...navigation.map((sample) => sample.maxFrameGapMs)),
        slowestSamples: [...navigation]
          .sort((first, second) => second.maxFrameGapMs - first.maxFrameGapMs)
          .slice(0, 5)
      },
      longTaskCount: report.longTasks.length,
      longestLongTaskMs: Math.max(0, ...report.longTasks.map((entry) => entry.duration)),
      longAnimationFrameCount: report.longAnimationFrames.length,
      longestLongAnimationFrameBlockingMs: Math.max(
        0,
        ...report.longAnimationFrames.map((entry) => entry.blockingDuration || 0)
      ),
      longestLongAnimationFrames: [...report.longAnimationFrames]
        .sort((first, second) => (second.blockingDuration || 0) - (first.blockingDuration || 0))
        .slice(0, 5),
      performanceMetrics: report.performanceMetrics,
      modalPerformance: {
        pendingTasks: report.homeTaskPickerPerformance,
        dispenseConfirm: report.medicineModalCoverage
      },
      idleObservation: report.idleObservation,
      layoutDiagnostics: Object.fromEntries(
        Object.entries(report.layouts).map(([viewport, pageLayouts]) => [viewport, Object.fromEntries(
          Object.entries(pageLayouts).map(([page, layout]) => [page, {
            scroll: layout.scroll,
            mainOverflow: layout.mainOverflow,
            shellChrome: layout.shellChrome,
            criticalClipping: layout.criticalClipping
          }])
        )])
      )
    }, null, 2)}\n`);
  } else {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  }

  for (const [viewport, pageLayouts] of Object.entries(layouts)) {
    for (const [page, layout] of Object.entries(pageLayouts)) {
      const [expectedWidth, expectedHeight] = viewport.split("x").map(Number);
      assert.deepEqual(
        layout.viewport,
        { width: expectedWidth, height: expectedHeight, dpr: deviceScaleFactor },
        `${page} at ${viewport} was not tested at the configured CSS viewport and device scale`
      );
      assert.ok(
        layout.verticalFill >= 0.98,
        `${page} at ${viewport} uses only ${(layout.verticalFill * 100).toFixed(1)}% of the viewport height`
      );
      assert.ok(
        [layout.outerTop, layout.outerBottom, layout.outerLeft, layout.outerRight]
          .every((gap) => Math.abs(gap) <= 2),
        `${page} at ${viewport} leaves whitespace or overflows outside the app frame`
      );
      assert.equal(layout.zoom, "1", `${page} at ${viewport} uses whole-frame CSS zoom`);
      assert.equal(layout.transform, "none", `${page} at ${viewport} uses whole-frame transform scaling`);
      assert.equal(layout.mainOverflow, 0, `${page} at ${viewport} clips content outside its page area`);
      assert.deepEqual(layout.criticalClipping, [], `${page} at ${viewport} clips a critical nested component`);
      if (process.env.QA_REDUCED_MOTION === "1") {
        const namedAnimations = Object.keys(layout.animationNames).filter((name) => name !== "web-animation");
        assert.deepEqual(namedAnimations, [], `${page} at ${viewport} keeps named animations in reduced-motion mode`);
      }
    }
  }

  if (medicineKeyboardNavigation) {
    assert.deepEqual(
      medicineKeyboardNavigation,
      { ready: true, selected: true, focused: true, position: "23", setSize: "23", visible: true },
      "the virtual medicine list cannot reach and expose its final off-screen option by keyboard"
    );
  }
  if (medicineCacheLifecycle) {
    assert.deepEqual(
      medicineCacheLifecycle,
      { cachePresentDuringAdmin: false, cachePresentAfterExit: false },
      "the medicine cache remounts hidden work after entering or leaving admin mode"
    );
  }
  if (medicineModalCoverage) {
    assert.equal(medicineModalCoverage.coversFrame, true, "the dispense confirmation does not cover the full kiosk");
    assert.equal(medicineModalCoverage.capturesNavigation, true, "the dispense confirmation does not capture navigation");
    assert.equal(medicineModalCoverage.medicineMatches, true, "the dispense confirmation uses a different medicine than the visible detail");
    assert.equal(medicineModalCoverage.backdropFilter, "none", "the dispense confirmation uses a live backdrop filter");
    assert.ok(
      medicineModalCoverage.openMs <= Number(process.env.QA_MAX_MODAL_OPEN_MS || 300),
      `the dispense confirmation opens in ${medicineModalCoverage.openMs.toFixed(1)}ms`
    );
    assert.ok(
      medicineModalCoverage.maxFrameGapMs <= Number(process.env.QA_MAX_MODAL_FRAME_GAP_MS || 84),
      `the dispense confirmation blocks a frame for ${medicineModalCoverage.maxFrameGapMs.toFixed(1)}ms`
    );
  }
  if (homeTaskPickerPerformance) {
    assert.equal(homeTaskPickerPerformance.backdropFilter, "none", "the full pending-task picker uses a live backdrop filter");
    assert.ok(
      homeTaskPickerPerformance.openMs <= Number(process.env.QA_MAX_MODAL_OPEN_MS || 300),
      `the full pending-task picker opens in ${homeTaskPickerPerformance.openMs.toFixed(1)}ms`
    );
    assert.ok(
      homeTaskPickerPerformance.maxFrameGapMs <= Number(process.env.QA_MAX_MODAL_FRAME_GAP_MS || 84),
      `the full pending-task picker blocks a frame for ${homeTaskPickerPerformance.maxFrameGapMs.toFixed(1)}ms`
    );
  }

  for (const [viewport, layout] of Object.entries(adminConsoleLayouts)) {
    assert.ok(layout.verticalFill >= 0.98, `authenticated admin console at ${viewport} does not fill the viewport`);
    assert.ok(
      [layout.outerTop, layout.outerBottom, layout.outerLeft, layout.outerRight]
        .every((gap) => Math.abs(gap) <= 2),
      `authenticated admin console at ${viewport} leaves whitespace or overflows outside the app frame`
    );
    assert.equal(layout.mainOverflow, 0, `authenticated admin console at ${viewport} overflows its viewport`);
    assert.equal(layout.zoom, "1", `authenticated admin console at ${viewport} uses whole-frame CSS zoom`);
    assert.equal(layout.transform, "none", `authenticated admin console at ${viewport} uses whole-frame scaling`);
  }

  if (navigation.length) {
    assert.equal(
      developmentBuild,
      false,
      "performance regression tests must target the production build from `npm run preview`"
    );
    const slowestDestinationRender = Math.max(...navigation.map((sample) => sample.destinationRenderedMs));
    const slowestTransition = Math.max(...navigation.map((sample) => sample.elapsedMs));
    const largestFrameGap = Math.max(...navigation.map((sample) => sample.maxFrameGapMs));
    const repeatedNavigation = navigation.filter((sample) => sample.visit > 1);
    const largestRepeatedFrameGap = Math.max(0, ...repeatedNavigation.map((sample) => sample.maxFrameGapMs));
    const destinationBudget = Number(process.env.QA_MAX_DESTINATION_MS || 250);
    const transitionBudget = Number(process.env.QA_MAX_TRANSITION_MS || 500);
    const coldFrameGapBudget = Number(process.env.QA_MAX_COLD_FRAME_GAP_MS || 84);
    const repeatedFrameGapBudget = Number(process.env.QA_MAX_REPEATED_FRAME_GAP_MS || 75);
    const longTaskBudget = Number(process.env.QA_MAX_LONG_TASK_MS || 75);
    const longAnimationFrameBlockingBudget = Number(process.env.QA_MAX_LOAF_BLOCKING_MS || 35);
    const longestLongTask = Math.max(0, ...navigationResult.longTasks.map((entry) => entry.duration));
    const longestLongAnimationFrameBlocking = Math.max(
      0,
      ...navigationResult.longAnimationFrames.map((entry) => entry.blockingDuration || 0)
    );
    assert.ok(
      slowestDestinationRender <= destinationBudget,
      `navigation destination renders in ${slowestDestinationRender.toFixed(1)}ms (budget: ${destinationBudget}ms)`
    );
    assert.ok(
      slowestTransition <= transitionBudget,
      `navigation transition completes in ${slowestTransition.toFixed(1)}ms (budget: ${transitionBudget}ms)`
    );
    assert.ok(
      largestFrameGap <= coldFrameGapBudget,
      `cold navigation blocks a frame for ${largestFrameGap.toFixed(1)}ms (budget: ${coldFrameGapBudget}ms)`
    );
    assert.ok(
      largestRepeatedFrameGap <= repeatedFrameGapBudget,
      `repeated navigation blocks a frame for ${largestRepeatedFrameGap.toFixed(1)}ms ` +
        `(budget: ${repeatedFrameGapBudget}ms)`
    );
    assert.ok(
      longestLongTask <= longTaskBudget,
      `navigation produced a ${longestLongTask.toFixed(1)}ms long task (budget: ${longTaskBudget}ms)`
    );
    assert.ok(
      longestLongAnimationFrameBlocking <= longAnimationFrameBlockingBudget,
      `navigation blocked a long animation frame for ${longestLongAnimationFrameBlocking.toFixed(1)}ms ` +
        `(budget: ${longAnimationFrameBlockingBudget}ms)`
    );
    assert.ok(
      navigation.every((sample) => !sample.usedNativeViewTransition),
      "navigation returned to native full-page snapshot transitions"
    );
  }
  if (idleObservation) {
    const frameGapBudget = Number(process.env.QA_MAX_IDLE_FRAME_GAP_MS || 75);
    const longTaskBudget = Number(process.env.QA_MAX_IDLE_LONG_TASK_MS || 75);
    const longAnimationFrameBlockingBudget = Number(process.env.QA_MAX_IDLE_LOAF_BLOCKING_MS || 35);
    const longestLongTask = Math.max(0, ...idleObservation.longTasks.map((entry) => entry.duration));
    const longestLongAnimationFrameBlocking = Math.max(
      0,
      ...idleObservation.longAnimationFrames.map((entry) => entry.blockingDuration || 0)
    );
    assert.ok(
      idleObservation.maxFrameGapMs <= frameGapBudget,
      `idle observation blocks a frame for ${idleObservation.maxFrameGapMs.toFixed(1)}ms (budget: ${frameGapBudget}ms)`
    );
    assert.ok(
      longestLongTask <= longTaskBudget,
      `idle observation produced a ${longestLongTask.toFixed(1)}ms long task (budget: ${longTaskBudget}ms)`
    );
    assert.ok(
      longestLongAnimationFrameBlocking <= longAnimationFrameBlockingBudget,
      `idle observation blocked a long animation frame for ${longestLongAnimationFrameBlocking.toFixed(1)}ms ` +
        `(budget: ${longAnimationFrameBlockingBudget}ms)`
    );
  }
  console.log("kiosk layout and navigation performance: ok");
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  await stopBrowser();
  await removeProfileDirectory();
}
