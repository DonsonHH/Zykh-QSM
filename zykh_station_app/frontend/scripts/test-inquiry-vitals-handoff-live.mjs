import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

import { mockDashboard } from "../src/api/mockData.js";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const profileDir = await mkdtemp(join(tmpdir(), "zykh-inquiry-vitals-handoff-"));
const vite = await createServer({
  root: frontendRoot,
  logLevel: "silent",
  server: { host: "127.0.0.1", port: 0, strictPort: false }
});
await vite.listen();
const baseUrl = vite.resolvedUrls?.local?.[0];
if (!baseUrl) throw new Error("isolated Vite server did not expose a loopback URL");

const debuggingPort = 10400 + Math.floor(Math.random() * 300);
const browser = spawn(process.env.CHROMIUM_BIN || "chromium", [
  "--headless=new",
  "--no-sandbox",
  "--hide-scrollbars",
  "--disable-gpu",
  "--remote-allow-origins=*",
  `--remote-debugging-port=${debuggingPort}`,
  `--user-data-dir=${profileDir}`,
  "about:blank"
], { stdio: "ignore" });

const sessionId = "qa-inquiry-vitals-handoff";
const baseSession = {
  session_id: sessionId,
  user_id: "service-user-qa",
  user_name: "测试使用人",
  user_age: 68,
  user_profile: "高血压",
  user_allergies: "无",
  stage: "vitals",
  reply: "接下来测量体征。",
  source: "cloud_responses",
  reasoning_summary: "需要体征后完成判断",
  model_action_intent: "measure_vitals",
  action_reason: "需要读取核心体征",
  extracted_information: {
    observations: [{ concept: "头晕", status: "present", evidence: "有点头晕", source_turn: 1, confidence: 0.9 }],
    symptom_dimensions: ["恶心暑湿"],
    duration: "今天开始",
    used_medicines: "未使用",
    allergy_or_contraindication: "无"
  },
  vitals: null,
  risk_level: null,
  risk_reasons: [],
  next_action: "measure_vitals",
  primary_candidate: null,
  alternative_candidate: null,
  can_view_medicines: false,
  treatment_options: [],
  selected_option_id: "",
  action_status: "idle",
  action_message: "",
  action_progress_index: 0,
  action_total_items: 0,
  action_items: [],
  medication_safety_notices: [],
  title: "头晕问询",
  messages: [{
    id: "qa-assistant-vitals",
    role: "assistant",
    content: "接下来测量体征。",
    source: "cloud_responses",
    created_at: "2026-08-08T21:00:00+08:00"
  }],
  created_at: "2026-08-08T21:00:00+08:00",
  updated_at: "2026-08-08T21:00:01+08:00"
};
const resultSession = {
  ...baseSession,
  stage: "result",
  reply: "体征已记录，请核对本次问询信息。",
  risk_level: "low",
  risk_reasons: ["未触发硬性危险信号"],
  next_action: "complete",
  vitals: {
    status: "complete",
    temperature: 36.6,
    heart_rate: 76,
    spo2: 98,
    measured_at: "2026-08-08T21:00:08+08:00"
  },
  updated_at: "2026-08-08T21:00:09+08:00"
};

let socket;
let nextMessageId = 0;
let interceptionError = null;
let vitalsAttachStarted = false;
let vitalsAttachPayload = null;
const runtimeErrors = [];
const consoleMessages = [];
const pending = new Map();

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

async function fulfillApiRequest({ requestId, request }) {
  const url = new URL(request.url);
  let payload = { ok: true };
  if (url.pathname === "/api/dashboard") {
    payload = mockDashboard;
  } else if (url.pathname === "/api/network/status") {
    payload = { label: "联网模式", wifi_connected: true, sim_connected: true };
  } else if (url.pathname === "/api/settings/basic") {
    payload = {
      settings: {
        network_mode: "sim",
        speaker_volume: 214,
        microphone_volume: 70,
        display_brightness: 100,
        idle_timeout_seconds: 90
      },
      warnings: []
    };
  } else if (url.pathname === "/api/records/service-users") {
    payload = { users: [] };
  } else if (url.pathname === `/api/inquiry/sessions/${sessionId}` && request.method === "GET") {
    payload = baseSession;
  } else if (url.pathname === `/api/inquiry/sessions/${sessionId}/vitals` && request.method === "POST") {
    vitalsAttachPayload = JSON.parse(request.postData || "{}");
    vitalsAttachStarted = true;
    await delay(1200);
    payload = resultSession;
  } else if (url.pathname === "/api/vitals/prepare") {
    payload = { ok: true, hardware_started: true };
  } else if (url.pathname === "/api/vitals/session/start") {
    payload = {
      ok: true,
      hardware_started: true,
      status: "complete",
      session_id: "qa-vitals-session",
      temperature: 36.6,
      heart_rate: 76,
      spo2: 98,
      measured_at: "2026-08-08T21:00:08+08:00"
    };
  } else if (url.pathname === "/api/audio/speak") {
    payload = { ok: true, status: "complete" };
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
        fulfillApiRequest(message.params).catch((error) => { interceptionError = error; });
        return;
      }
      if (message.method === "Runtime.exceptionThrown") {
        runtimeErrors.push(message.params?.exceptionDetails?.text || "runtime exception");
        return;
      }
      if (message.method === "Runtime.consoleAPICalled") {
        consoleMessages.push((message.params?.args || []).map((arg) => arg.value || arg.description || "").join(" "));
        return;
      }
      if (message.method === "Log.entryAdded") {
        consoleMessages.push(`${message.params?.entry?.level || "log"}: ${message.params?.entry?.text || ""}`);
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

async function waitForNodeState(predicate, label, timeoutMs = 8_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await delay(25);
  }
  throw new Error(`Timed out waiting for ${label}`);
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
  await vite.close();
  await rm(profileDir, { recursive: true, force: true, maxRetries: 4, retryDelay: 50 });
}

try {
  await connect(await waitForTarget());
  await cdp("Page.enable");
  await cdp("Runtime.enable");
  await cdp("Log.enable");
  await cdp("Fetch.enable", {
    patterns: [{ urlPattern: `${new URL(baseUrl).origin}/api/*`, requestStage: "Request" }]
  });
  await cdp("Page.addScriptToEvaluateOnNewDocument", {
    source: `sessionStorage.setItem("zykh-inquiry-backend-session", ${JSON.stringify(sessionId)});`
  });
  await cdp("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 600,
    deviceScaleFactor: 2,
    mobile: false
  });
  await cdp("Page.navigate", { url: `${baseUrl}?page=inquiry&awake=1` });

  await evaluate(`(async () => {
    const waitFor = async (predicate, label, timeoutMs = 9000) => {
      const deadline = performance.now() + timeoutMs;
      while (performance.now() < deadline) {
        const value = predicate();
        if (value) return value;
        await new Promise(requestAnimationFrame);
      }
      throw new Error('Timed out waiting for ' + label);
    };
    const vitals = await waitFor(
      () => document.querySelector('.vitals-page.embedded'),
      'embedded vitals page'
    );
    const start = await waitFor(
      () => vitals.querySelector('.vitals-primary-action'),
      'vitals start action'
    );
    start.click();
    await waitFor(
      () => vitals.querySelector('.vitals-page-heading h2')?.textContent.includes('测量结果'),
      'completed vitals result'
    );
    vitals.querySelector('.vitals-back-button').click();
    return true;
  })()`);

  await waitForNodeState(() => vitalsAttachStarted, "delayed inquiry vitals request");
  assert.deepEqual(
    {
      status: vitalsAttachPayload?.status,
      heart_rate: vitalsAttachPayload?.heart_rate,
      spo2: vitalsAttachPayload?.spo2,
      temperature: vitalsAttachPayload?.temperature
    },
    { status: "complete", heart_rate: 76, spo2: 98, temperature: 36.6 },
    "returning from a completed measurement must preserve the measured vitals"
  );
  const immediateState = await evaluate(`(() => ({
    loadingVisible: Boolean(document.querySelector('.inquiry-vitals-handoff[role="status"]')),
    loadingText: document.querySelector('.inquiry-vitals-handoff')?.textContent || '',
    vitalsStillVisible: Boolean(document.querySelector('.vitals-page.embedded'))
  }))()`);
  assert.equal(
    immediateState.loadingVisible,
    true,
    "returning from completed vitals must show a loading state while the AI result is pending"
  );
  assert.match(
    immediateState.loadingText,
    /正在整理体征与问询信息/,
    "the loading state does not explain the pending inquiry work"
  );
  assert.equal(
    immediateState.vitalsStillVisible,
    false,
    "the completed vitals page remains frozen while the AI result is pending"
  );

  const reviewVisible = await evaluate(`(async () => {
    const deadline = performance.now() + 5000;
    while (performance.now() < deadline) {
      if (document.querySelector('.inquiry-information-review')) return true;
      await new Promise(requestAnimationFrame);
    }
    return false;
  })()`);
  assert.equal(reviewVisible, true, "the information review did not appear after the delayed AI response");
  if (interceptionError) throw interceptionError;
  console.log("inquiry vitals handoff live: ok");
} catch (error) {
  const diagnostics = await evaluate(`(() => ({
    title: document.title,
    url: location.href,
    body: document.body?.innerText?.slice(0, 1200) || '',
    html: document.body?.innerHTML?.slice(0, 1200) || '',
    sessionId: sessionStorage.getItem('zykh-inquiry-backend-session') || '',
    hasInquiry: Boolean(document.querySelector('.inquiry-page')),
    hasChat: Boolean(document.querySelector('.inquiry-chat-step')),
    hasVitals: Boolean(document.querySelector('.vitals-page.embedded')),
    toast: document.querySelector('.toast')?.textContent || '',
    readyState: document.readyState
  }))()`).catch(() => null);
  throw new Error(`${error.message}\nBrowser diagnostics: ${JSON.stringify(diagnostics)}\nRuntime errors: ${JSON.stringify(runtimeErrors)}\nConsole: ${JSON.stringify(consoleMessages.slice(-10))}`);
} finally {
  await stopBrowser();
}
