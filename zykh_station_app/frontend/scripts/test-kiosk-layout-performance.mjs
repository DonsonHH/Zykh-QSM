import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const baseUrl = process.env.QA_BASE_URL || "http://127.0.0.1:5174";
const chromiumBin = process.env.CHROMIUM_BIN || "chromium";
const screenshotDir = process.env.QA_SCREENSHOT_DIR
  ? join(frontendRoot, process.env.QA_SCREENSHOT_DIR)
  : "";
const profileDir = await mkdtemp(join(tmpdir(), "zykh-chrome-kiosk-ui-"));
const debuggingPort = 9300 + Math.floor(Math.random() * 500);
const browser = spawn(
  chromiumBin,
  [
    "--headless=new",
    "--no-sandbox",
    "--hide-scrollbars",
    "--remote-allow-origins=*",
    `--remote-debugging-port=${debuggingPort}`,
    `--user-data-dir=${profileDir}`,
    "--window-size=1920,1080",
    "--force-device-scale-factor=1",
    `${baseUrl}/?page=home&awake=1`
  ],
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
  const screenshot = await cdp("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false
  });
  await writeFile(join(screenshotDir, `${name}.png`), Buffer.from(screenshot.data, "base64"));
}

async function readLayout() {
  return evaluate(`(() => {
    const frameElement = document.querySelector('.kiosk-frame');
    const frame = frameElement.getBoundingClientRect();
    const frameStyle = getComputedStyle(frameElement);
    const mainElement = document.querySelector('.kiosk-frame > main');
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
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight, dpr: window.devicePixelRatio },
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
      criticalClipping
    };
  })()`);
}

async function measureNavigation() {
  return evaluate(`(async () => {
    const destinations = [
      { label: '药品', page: 'medicines' },
      { label: '问询', page: 'inquiry' },
      { label: '记录', page: 'records' },
      { label: '首页', page: 'home' }
    ];
    const measurements = [];
    for (const { label, page } of destinations) {
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
        const pageAnimations = document.querySelector('.kiosk-frame > main')?.getAnimations() || [];
        const transitionIsRunning = pageAnimations.some((animation) =>
          animation.animationName?.startsWith('kiosk-page-enter-') &&
          animation.playState !== 'finished'
        );
        if (!transitionIsRunning) break;
      }
      if (document.querySelector('.bottom-nav button[aria-current="page"]') !== button) {
        throw new Error('Navigation did not render destination page: ' + page);
      }
      collecting = false;
      measurements.push({
        label,
        page,
        destinationRenderedMs: renderedAt - startedAt,
        elapsedMs: performance.now() - startedAt,
        maxFrameGapMs: Math.max(0, ...frameGaps),
        usedNativeViewTransition
      });
    }
    return measurements;
  })()`);
}

try {
  await connect(await waitForTarget());
  await cdp("Page.enable");
  await cdp("Runtime.enable");
  if (process.env.QA_REDUCED_MOTION === "1") {
    await cdp("Emulation.setEmulatedMedia", {
      features: [{ name: "prefers-reduced-motion", value: "reduce" }]
    });
  }

  const viewports = [
    { width: 1280, height: 720 },
    { width: 1600, height: 900 },
    { width: 1920, height: 1080 }
  ];
  const pages = ["home", "medicines", "inquiry", "records", "scan", "vitals", "settings", "admin", "idle"];
  const layouts = {};
  for (const viewport of viewports) {
    const viewportKey = `${viewport.width}x${viewport.height}`;
    await cdp("Emulation.setDeviceMetricsOverride", {
      ...viewport,
      deviceScaleFactor: 1,
      mobile: false
    });
    layouts[viewportKey] = {};
    for (const page of pages) {
      await navigate(page === "idle" ? "home" : page, page !== "idle");
      layouts[viewportKey][page] = await readLayout();
      await capture(`${page}-${viewportKey}`);
    }
  }

  const adminConsoleLayouts = {};
  if (process.env.QA_ADMIN_PIN) {
    for (const viewport of viewports) {
      const viewportKey = `${viewport.width}x${viewport.height}`;
      await cdp("Emulation.setDeviceMetricsOverride", {
        ...viewport,
        deviceScaleFactor: 1,
        mobile: false
      });
      await openAdminConsole(process.env.QA_ADMIN_PIN);
      adminConsoleLayouts[viewportKey] = await readLayout();
      await capture(`admin-console-${viewportKey}`);
    }
  }

  await cdp("Emulation.setDeviceMetricsOverride", {
    width: 1920,
    height: 1080,
    deviceScaleFactor: 1,
    mobile: false
  });
  await navigate("home");
  const navigation = await measureNavigation();
  const report = { layouts, adminConsoleLayouts, navigation };
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);

  for (const [viewport, pageLayouts] of Object.entries(layouts)) {
    for (const [page, layout] of Object.entries(pageLayouts)) {
      assert.ok(
        layout.verticalFill >= 0.98,
        `${page} at ${viewport} uses only ${(layout.verticalFill * 100).toFixed(1)}% of the viewport height`
      );
      assert.ok(
        layout.outerTop <= 2 && layout.outerBottom <= 2 && layout.outerLeft <= 2 && layout.outerRight <= 2,
        `${page} at ${viewport} leaves whitespace outside the app frame`
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

  for (const [viewport, layout] of Object.entries(adminConsoleLayouts)) {
    assert.ok(layout.verticalFill >= 0.98, `authenticated admin console at ${viewport} does not fill the viewport`);
    assert.ok(
      layout.outerTop <= 2 && layout.outerBottom <= 2 && layout.outerLeft <= 2 && layout.outerRight <= 2,
      `authenticated admin console at ${viewport} leaves whitespace outside the app frame`
    );
    assert.equal(layout.mainOverflow, 0, `authenticated admin console at ${viewport} overflows its viewport`);
    assert.equal(layout.zoom, "1", `authenticated admin console at ${viewport} uses whole-frame CSS zoom`);
    assert.equal(layout.transform, "none", `authenticated admin console at ${viewport} uses whole-frame scaling`);
  }

  const slowestDestinationRender = Math.max(...navigation.map((sample) => sample.destinationRenderedMs));
  const slowestTransition = Math.max(...navigation.map((sample) => sample.elapsedMs));
  const largestFrameGap = Math.max(...navigation.map((sample) => sample.maxFrameGapMs));
  assert.ok(
    slowestDestinationRender <= 250,
    `navigation destination renders in ${slowestDestinationRender.toFixed(1)}ms (budget: 250ms)`
  );
  assert.ok(
    slowestTransition <= 400,
    `navigation transition completes in ${slowestTransition.toFixed(1)}ms (budget: 400ms)`
  );
  assert.ok(
    largestFrameGap <= 120,
    `navigation blocks a frame for ${largestFrameGap.toFixed(1)}ms (budget: 120ms)`
  );
  assert.ok(
    navigation.every((sample) => !sample.usedNativeViewTransition),
    "navigation returned to native full-page snapshot transitions"
  );
  console.log("kiosk layout and navigation performance: ok");
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  await stopBrowser();
  await removeProfileDirectory();
}
