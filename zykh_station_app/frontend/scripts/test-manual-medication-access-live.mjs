import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

import { mockDashboard } from "../src/api/mockData.js";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const profileDir = await mkdtemp(join(tmpdir(), "zykh-manual-medication-access-"));
const vite = await createServer({
  root: frontendRoot,
  logLevel: "silent",
  server: { host: "127.0.0.1", port: 0, strictPort: false }
});
await vite.listen();
const baseUrl = vite.resolvedUrls?.local?.[0];
if (!baseUrl) throw new Error("isolated Vite server did not expose a loopback URL");

const debuggingPort = 10700 + Math.floor(Math.random() * 300);
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

const medicine = {
  id: "slot-13-ibuprofen",
  slot: "13",
  hardware_slot: 13,
  cabinet_id: 1,
  cabinet_label: "日常用药",
  barcode: "6913991301572",
  manufacturer: "芬必得",
  name: "布洛芬缓释胶囊",
  category: "解热镇痛",
  spec: "0.3克×20粒",
  trace_code: "",
  tags: ["头痛", "关节痛"],
  aliases: ["布洛芬"],
  active_ingredients: ["布洛芬"],
  indications: "缓解轻至中度疼痛",
  dosage: "按实物包装说明书使用",
  contraindications: ["消化性溃疡患者禁用"],
  structured_contraindications: [{ concept_code: "peptic_ulcer", display_text: "消化性溃疡" }],
  stock: 3,
  low_stock_line: 1,
  unit: "盒",
  expire_date: "2029-01",
  image_hint: "capsule",
  is_otc: false,
  is_emergency: false,
  safety_note: "请核对包装说明书",
  guidance_source: "label_reference",
  guidance_review_required: false,
  package_verified: true,
  guidance_updated_at: "2026-08-10 10:00:00",
  safety_review_status: "reviewed",
  safety_reviewed_by: "qa-reviewer",
  safety_reviewed_at: "2026-08-10 10:00:00",
  review_fingerprint: "review-fingerprint-slot-13",
  dispense_count: 2
};
const secondMedicine = {
  ...medicine,
  id: "slot-17-iodophor",
  slot: "17",
  hardware_slot: 17,
  cabinet_id: 2,
  cabinet_label: "外用护理",
  barcode: "6901234567019",
  manufacturer: "康护制药",
  name: "碘伏消毒液",
  category: "消毒护理",
  spec: "100毫升",
  tags: ["皮肤消毒", "伤口护理"],
  aliases: ["碘伏"],
  active_ingredients: ["聚维酮碘"],
  indications: "用于皮肤和浅表伤口消毒",
  contraindications: [],
  structured_contraindications: [],
  safety_note: "仅供外用",
  review_fingerprint: "review-fingerprint-slot-17",
  dispense_count: 1
};
const registeredUser = {
  id: "wang-nainai",
  name: "王奶奶",
  age: 72,
  profile: "高血压；既往胃溃疡",
  allergies: "青霉素类药物过敏",
  note: "女儿为绑定家属",
  status: "重点照护"
};
const guestUser = {
  id: "guest-manual-qa",
  name: "访客",
  age: 0,
  profile: "身份未登记",
  allergies: "",
  note: "现场访客",
  status: "访客"
};

let socket;
let nextMessageId = 0;
let interceptionError = null;
const pending = new Map();
const runtimeErrors = [];
const consoleMessages = [];
const requests = {
  assess: [],
  confirm: [],
  inventory: [],
  legacyConfirm: [],
  directDispense: [],
  lightOff: [],
  audio: []
};
const requestOrder = [];
const requestTimeline = [];
let assessmentMode = "blocked";
let confirmationMode = "success";
let identityMode = "guest";
let lightOffFailuresRemaining = 0;
let deferNextInventoryResponse = false;
const deferredInventoryResponses = [];
let deferNextAudioStopResponse = false;
const deferredAudioStopResponses = [];

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

function jsonBody(request) {
  try {
    return JSON.parse(request.postData || "{}");
  } catch {
    return {};
  }
}

async function fulfillJson(requestId, payload, responseCode = 200) {
  await cdp("Fetch.fulfillRequest", {
    requestId,
    responseCode,
    responseHeaders: [{ name: "Content-Type", value: "application/json; charset=utf-8" }],
    body: Buffer.from(JSON.stringify(payload)).toString("base64")
  });
}

async function fulfillImage(requestId) {
  await cdp("Fetch.fulfillRequest", {
    requestId,
    responseCode: 200,
    responseHeaders: [{ name: "Content-Type", value: "image/gif" }],
    body: "R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
  });
}

async function fulfillApiRequest({ requestId, request }) {
  const url = new URL(request.url);
  if (["/api/camera/stream", "/api/identity/frame"].includes(url.pathname)) {
    await fulfillImage(requestId);
    return;
  }

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
        idle_timeout_seconds: 0
      },
      warnings: []
    };
  } else if (url.pathname === "/api/medicines") {
    payload = {
      ok: true,
      total: 2,
      warehouse_total: 6,
      categories: [medicine.category, secondMedicine.category],
      cabinets: [{
        id: 1,
        label: "日常用药",
        description: "感冒、发热、咳嗽、过敏、咽喉与胃肠常用药",
        medicine_ids: [medicine.id]
      }, {
        id: 2,
        label: "外用护理",
        description: "消毒、伤口、皮肤、鼻部与局部疼痛护理",
        medicine_ids: [secondMedicine.id]
      }, {
        id: 3,
        label: "慢病处方储备",
        description: "慢病固定用药、处方药与低频储备用药",
        medicine_ids: []
      }],
      medicines: [medicine, secondMedicine]
    };
  } else if ([medicine, secondMedicine].some((item) => url.pathname === `/api/medicines/${item.id}`)) {
    const requestedMedicine = [medicine, secondMedicine]
      .find((item) => url.pathname === `/api/medicines/${item.id}`);
    payload = { ok: true, medicine: requestedMedicine };
  } else if (url.pathname === "/api/fingerprint/identify") {
    payload = {
      ok: true,
      status: "matched",
      user: registeredUser,
      score: 93,
      verification_assertion_id: "identity-assertion-wang",
      message: "指纹已确认：王奶奶"
    };
  } else if (url.pathname === "/api/identity/verify-dispense") {
    payload = identityMode === "no_face"
      ? {
        ok: false,
        status: "no_face",
        user: null,
        error_message: "未检测到可确认的人脸。"
      }
      : {
        ok: true,
        status: "created",
        user: guestUser,
        confidence: null,
        new_guest: true,
        verification_assertion_id: "identity-assertion-guest",
        message: "已建立本地访客记录：访客"
      };
  } else if (url.pathname === "/api/manual-medication-access/assess") {
    requests.assess.push(jsonBody(request));
    requestOrder.push("assess");
    if (assessmentMode === "network_error") {
      await cdp("Fetch.failRequest", { requestId, errorReason: "ConnectionRefused" });
      return;
    }
    if (assessmentMode === "guest") await delay(800);
    payload = assessmentMode === "passed"
      ? {
        ok: true,
        check_id: "safety-check-passed",
        check_status: "PASSED",
        reason_codes: [],
        message: "基于已登记资料未发现明确冲突，请确认后继续。",
        expires_at: "2026-08-10 10:01:30",
        dispense_status: "NOT_STARTED"
      }
      : assessmentMode === "guest"
        ? {
          ok: true,
          check_id: "safety-check-guest-failed",
          check_status: "CHECK_FAILED",
          reason_codes: ["PROFILE_UNAVAILABLE"],
          message: "未找到可用于核查的个人健康档案，本次柜门未打开。",
          expires_at: "",
          dispense_status: "NOT_STARTED"
        }
      : {
        ok: true,
        check_id: "safety-check-blocked",
        check_status: "BLOCKED",
        reason_codes: ["CONDITION_CONTRAINDICATION"],
        message: "已登记病史“既往胃溃疡”与布洛芬缓释胶囊禁忌冲突，本次已阻止取药，柜门未打开。",
        expires_at: "",
        dispense_status: "NOT_STARTED"
      };
  } else if (url.pathname === "/api/manual-medication-access/confirm") {
    requests.confirm.push(jsonBody(request));
    requestOrder.push("confirm");
    requestTimeline.push({ type: "confirm" });
    if (confirmationMode === "server_error") {
      await fulfillJson(requestId, { detail: "开柜服务响应超时" }, 503);
      return;
    }
    if (confirmationMode === "network_error") {
      await cdp("Fetch.failRequest", { requestId, errorReason: "ConnectionRefused" });
      return;
    }
    if (confirmationMode === "conflict") {
      await fulfillJson(requestId, { detail: "安全核查凭据已失效" }, 409);
      return;
    }
    payload = assessmentMode === "passed"
      ? {
        ok: true,
        safety_check_id: "safety-check-passed",
        dispense_status: "DISPENSED",
        message: "柜门已打开，请取出药品并关闭柜门。",
        dispense_record_id: "dispense-record-manual-passed",
        inventory_confirmation_required: true
      }
      : {
        ok: false,
        safety_check_id: "safety-check-blocked",
        dispense_status: "HARDWARE_FAILED",
        message: "BLOCKED 不应进入确认"
      };
  } else if (url.pathname === "/api/dispense/confirm") {
    requests.legacyConfirm.push(jsonBody(request));
    payload = { ok: false, message: "隔离测试禁止旧取药接口" };
  } else if (url.pathname === "/api/dispense") {
    requests.directDispense.push(jsonBody(request));
    payload = { ok: false, message: "隔离测试禁止直接开柜" };
  } else if ([medicine, secondMedicine]
    .some((item) => url.pathname === `/api/medicines/${item.id}/inventory-confirmation`)) {
    const requestedMedicine = [medicine, secondMedicine]
      .find((item) => url.pathname === `/api/medicines/${item.id}/inventory-confirmation`);
    const inventoryRequest = jsonBody(request);
    requests.inventory.push(inventoryRequest);
    requestOrder.push("inventory");
    const depleted = inventoryRequest.observation === "DEPLETED";
    const inventoryPayload = {
      ok: true,
      medicine_id: requestedMedicine.id,
      inventory_state: depleted ? "DEPLETED" : "AVAILABLE",
      stock: depleted ? 0 : requestedMedicine.stock,
      inventory_confirmed_at: "2026-08-20 10:00:00"
    };
    if (deferNextInventoryResponse) {
      deferNextInventoryResponse = false;
      deferredInventoryResponses.push({ requestId, payload: inventoryPayload });
      return;
    }
    payload = inventoryPayload;
  } else if (url.pathname === "/api/qsm/cabinet-light/off") {
    requests.lightOff.push(jsonBody(request));
    requestOrder.push("off");
    if (lightOffFailuresRemaining > 0) {
      lightOffFailuresRemaining -= 1;
      await fulfillJson(requestId, { detail: "控制器未确认 OFF，请重试" }, 503);
      return;
    }
    payload = { ok: true, result: "off", message: "分类柜指示灯已关闭" };
  } else if (url.pathname === "/api/audio/speak") {
    const speech = { type: "speak", text: String(jsonBody(request).text || "") };
    requests.audio.push(speech);
    requestTimeline.push(speech);
    payload = { ok: true, status: "complete" };
  } else if (url.pathname === "/api/audio/stream/stop") {
    const stop = { type: "stop", text: "" };
    requests.audio.push(stop);
    requestTimeline.push(stop);
    if (deferNextAudioStopResponse) {
      deferNextAudioStopResponse = false;
      deferredAudioStopResponses.push({ requestId });
      return;
    }
    payload = { ok: true, status: "complete" };
  }
  await fulfillJson(requestId, payload);
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
          if (!String(error.message || error).includes("Invalid InterceptionId")) {
            interceptionError = error;
          }
        });
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
    try {
      if (await predicate()) return;
    } catch (error) {
      const message = String(error.message || error);
      if (!message.includes("Promise was collected") && !message.includes("Execution context was destroyed")) {
        throw error;
      }
    }
    await delay(25);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function startFingerprintFlow() {
  await waitForNodeState(
    async () => evaluate(`document.readyState === 'complete' && Boolean(document.querySelector('.dispense-modal'))`),
    "navigated manual dispense modal"
  );
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
    const modal = await waitFor(
      () => document.querySelector('.dispense-modal'),
      'manual dispense modal'
    );
    const fingerprint = [...modal.querySelectorAll('.biometric-method-toggle button')]
      .find((button) => button.textContent.includes('指纹'));
    fingerprint.click();
    const action = await waitFor(
      () => modal.querySelector('.biometric-confirm-action:not([disabled])'),
      'identity confirmation action'
    );
    action.click();
    return true;
  })()`);
}

async function startFaceFlow() {
  await waitForNodeState(
    async () => evaluate(`document.readyState === 'complete' && Boolean(document.querySelector('.dispense-modal'))`),
    "navigated face dispense modal"
  );
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
    const modal = await waitFor(
      () => document.querySelector('.dispense-modal'),
      'manual dispense modal'
    );
    const action = await waitFor(
      () => modal.querySelector('.biometric-confirm-action:not([disabled])'),
      'face identity confirmation action'
    );
    action.click();
    return true;
  })()`);
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
  await cdp("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 720,
    deviceScaleFactor: 1,
    mobile: false
  });
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1`
  });

  await startFingerprintFlow();

  await waitForNodeState(
    () => requests.assess.length > 0 || requests.legacyConfirm.length > 0,
    "manual assessment or forbidden legacy dispense request"
  );
  await delay(250);

  assert.equal(requests.assess.length, 1, "registered manual pick must run one person-medicine assessment");
  assert.deepEqual(
    {
      medicine_id: requests.assess[0]?.medicine_id,
      slot: requests.assess[0]?.slot,
      service_user_id: requests.assess[0]?.service_user_id,
      verification_method: requests.assess[0]?.verification_method,
      verification_assertion_id: requests.assess[0]?.verification_assertion_id,
      expected_review_fingerprint: requests.assess[0]?.expected_review_fingerprint
    },
    {
      medicine_id: medicine.id,
      slot: medicine.slot,
      service_user_id: registeredUser.id,
      verification_method: "fingerprint",
      verification_assertion_id: "identity-assertion-wang",
      expected_review_fingerprint: medicine.review_fingerprint
    },
    "manual assessment must bind the verified person, assertion, medicine and review fingerprint"
  );
  assert.match(String(requests.assess[0]?.request_id || ""), /^manual-assess-/, "assessment request has no stable idempotency key");
  assert.equal(requests.confirm.length, 0, "BLOCKED assessment must not call manual confirmation");
  assert.equal(requests.legacyConfirm.length, 0, "manual inventory must never call the legacy dispense confirmation");
  assert.equal(requests.directDispense.length, 0, "BLOCKED assessment must not call direct dispense");

  const blockedView = await evaluate(`(() => ({
    text: document.querySelector('.dispense-modal')?.innerText || '',
    detailText: document.querySelector('.medicine-detail-panel')?.innerText || '',
    status: document.querySelector('.manual-access-result')?.getAttribute('data-status') || '',
    alertRole: document.querySelector('.manual-access-result')?.getAttribute('role') || '',
    identityMethodsLocked: [...document.querySelectorAll('.biometric-method-toggle button')]
      .every((button) => button.disabled)
  }))()`);
  assert.equal(blockedView.status, "blocked", "BLOCKED response is not rendered as a terminal blocked state");
  assert.equal(blockedView.alertRole, "alert", "blocked safety result is not announced assertively");
  assert.equal(blockedView.identityMethodsLocked, true, "blocked result can be bypassed by changing identity method");
  assert.match(blockedView.text, /王奶奶/, "blocked result does not identify the verified person");
  assert.match(blockedView.text, /布洛芬缓释胶囊/, "blocked result does not identify the medicine");
  assert.match(blockedView.text, /禁忌提醒：消化性溃疡患者禁用/, "dispense confirmation omits contraindications");
  assert.match(blockedView.text, /慎用与指导提醒：请核对包装说明书/, "dispense confirmation hides the safety note when contraindications exist");
  assert.match(blockedView.detailText, /禁忌提醒[\s\S]*消化性溃疡患者禁用/, "medicine details omit contraindications");
  assert.match(blockedView.detailText, /慎用与指导提醒[\s\S]*请核对包装说明书/, "medicine details omit the independent safety note");
  assert.match(blockedView.text, /既往胃溃疡/, "blocked result does not show the server-provided reason");
  assert.match(blockedView.text, /分类柜指示灯未亮/, "blocked result does not explicitly say that the cabinet light stayed off");
  assert.match(blockedView.text, /已记录并将同步家属/, "blocked result does not explain family visibility");

  assessmentMode = "network_error";
  Object.values(requests).forEach((items) => { items.length = 0; });
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=assess-network-error`
  });
  await startFingerprintFlow();
  await waitForNodeState(() => requests.assess.length === 1, "network-failed manual assessment");
  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "check_failed";
  }, "network-failed assessment check-failed state");
  const unpersistedAssessmentView = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
  assert.match(unpersistedAssessmentView, /分类柜指示灯未亮/, "failed assessment does not keep the cabinet light off");
  assert.doesNotMatch(
    unpersistedAssessmentView,
    /已记录并将同步家属/,
    "a locally synthesized assessment failure falsely claims it was persisted"
  );
  assert.equal(requests.confirm.length, 0);
  assert.equal(requests.legacyConfirm.length, 0);
  assert.equal(requests.directDispense.length, 0);

  assessmentMode = "passed";
  lightOffFailuresRemaining = 1;
  Object.values(requests).forEach((items) => { items.length = 0; });
  requestOrder.length = 0;
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=passed`
  });
  await startFingerprintFlow();
  await waitForNodeState(() => requests.assess.length === 1, "PASSED manual assessment");
  await waitForNodeState(() => requests.confirm.length === 1, "automatic manual confirmation after PASSED assessment");
  assert.equal(requests.legacyConfirm.length, 0, "PASSED manual flow must not fall back to legacy dispense");
  assert.deepEqual(
    {
      safety_check_id: requests.confirm[0]?.safety_check_id,
      confirmed_safety_notice: requests.confirm[0]?.confirmed_safety_notice
    },
    {
      safety_check_id: "safety-check-passed",
      confirmed_safety_notice: true
    },
    "automatic manual confirmation must consume the passed one-time safety check"
  );
  assert.match(String(requests.confirm[0]?.request_id || ""), /^manual-confirm-/, "confirmation request has no idempotency key");
  assert.equal(requests.legacyConfirm.length, 0, "automatic manual confirmation must not call the legacy endpoint");
  assert.equal(requests.directDispense.length, 0, "automatic manual confirmation must not call direct dispense");
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("分类柜内还有药吗？");
  }, "automatic inventory confirmation after cabinet light");
  const inventoryView = await evaluate(`(() => ({
    text: document.querySelector('.dispense-modal')?.innerText || '',
    actions: [...document.querySelectorAll('.dispense-modal button')].map((button) => button.textContent.trim())
  }))()`);
  assert.match(inventoryView.text, /分类柜内还有药吗？/);
  assert.doesNotMatch(inventoryView.actions.join(" "), /确认取药并亮灯|我已取药，关闭指示灯/);
  assert.equal(requests.lightOff.length, 0, "cabinet light must remain on while the inventory page is visible");
  const firstCabinetLightSpeech = `${medicine.name}所在的1号柜指示灯已亮`;
  await waitForNodeState(
    () => requests.audio.some((entry) => entry.type === "speak" && entry.text.includes(firstCabinetLightSpeech)),
    "cabinet 1 collection speech"
  );
  deferNextAudioStopResponse = true;
  await evaluate(`([...document.querySelectorAll('.dispense-modal button')]
    .find((button) => button.textContent.includes('还有药'))).click()`);
  await waitForNodeState(() => requests.inventory.length === 1, "inventory observation after medicine collection");
  assert.equal(requests.inventory[0]?.dispense_record_id, "dispense-record-manual-passed");
  assert.equal(requests.inventory[0]?.observation, "HAS_REMAINING");
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("已确认分类柜内还有药") && !text.includes("分类柜内还有药吗？");
  }, "inventory question disappearing after the observation is saved");
  assert.equal(requests.lightOff.length, 0, "cabinet light must not turn off before the inventory question disappears");
  await waitForNodeState(() => requests.lightOff.length === 1, "automatic cabinet light OFF after inventory page disappears");
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("库存已保存，但指示灯关闭失败");
  }, "visible automatic OFF failure");
  assert.equal(
    await evaluate(`Boolean(document.querySelector('.inventory-light-off-retry:not([disabled])'))`),
    true,
    "an automatic OFF failure must remain visible with a safe retry action"
  );
  await evaluate(`document.querySelector('.inventory-light-off-retry:not([disabled])').click()`);
  await waitForNodeState(() => requests.lightOff.length === 2, "retried automatic cabinet light OFF request");
  await waitForNodeState(
    async () => evaluate(`!document.querySelector('.dispense-modal')`),
    "dispense modal closing only after OFF is confirmed"
  );
  assert.deepEqual(requestOrder, ["assess", "confirm", "inventory", "off", "off"]);
  const firstCabinetSpeechIndex = requests.audio.findIndex(
    (entry) => entry.type === "speak" && entry.text.includes(firstCabinetLightSpeech)
  );
  await waitForNodeState(
    () => requests.audio.some((entry, index) => index > firstCabinetSpeechIndex && entry.type === "stop"),
    "audio stop after cabinet 1 session closes"
  );
  const firstCabinetCloseStopIndex = requests.audio.findIndex(
    (entry, index) => index > firstCabinetSpeechIndex && entry.type === "stop"
  );

  const secondModalAudioStart = requests.audio.length;
  const secondModalTimelineStart = requestTimeline.length;
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
    const card = await waitFor(
      () => [...document.querySelectorAll('.medicine-card, .cabinet-medicine')]
        .find((item) => item.textContent.includes('${secondMedicine.name}')),
      'cabinet 2 medicine card'
    );
    card.click();
    const action = await waitFor(
      () => {
        const panel = document.querySelector('.medicine-detail-panel');
        const button = panel?.querySelector('.detail-action:not([disabled])');
        return panel?.textContent.includes('${secondMedicine.name}') ? button : null;
      },
      'cabinet 2 manual dispense action'
    );
    action.click();
    await waitFor(() => document.querySelector('.dispense-modal'), 'cabinet 2 dispense modal');
    return true;
  })()`);
  await delay(250);
  assert.equal(
    deferredAudioStopResponses.length,
    1,
    "cabinet 1 close did not leave the controlled audio STOP pending"
  );
  assert.equal(
    requests.audio.slice(secondModalAudioStart).some((entry) => entry.type === "speak"),
    false,
    "cabinet 2 speech started before cabinet 1's close STOP had completed"
  );
  const deferredAudioStop = deferredAudioStopResponses.shift();
  await fulfillJson(deferredAudioStop.requestId, { ok: true, status: "complete" });
  await waitForNodeState(
    () => requests.audio.slice(secondModalAudioStart).some((entry) => entry.type === "speak"),
    "first speech after cabinet 2 modal opens"
  );
  const firstSecondModalSpeech = requests.audio
    .slice(secondModalAudioStart)
    .find((entry) => entry.type === "speak");
  assert.match(
    firstSecondModalSpeech?.text || "",
    new RegExp(`^${secondMedicine.name}，请`),
    `cabinet 2 modal first played stale cabinet-light speech: ${firstSecondModalSpeech?.text || "<none>"}`
  );
  assert.doesNotMatch(
    firstSecondModalSpeech?.text || "",
    /指示灯已亮/,
    "cabinet 2 modal must not begin with a cabinet-light completion announcement"
  );
  await delay(220);
  const preIdentitySpeeches = requests.audio
    .slice(secondModalAudioStart)
    .filter((entry) => entry.type === "speak");
  assert.equal(
    preIdentitySpeeches.some((entry) => entry.text.includes("指示灯已亮")),
    false,
    `cabinet 2 modal announced cabinet illumination before identity confirmation: ${JSON.stringify(preIdentitySpeeches)}`
  );
  await startFingerprintFlow();
  await waitForNodeState(() => requests.assess.length === 2, "cabinet 2 manual assessment");
  await waitForNodeState(() => requests.confirm.length === 2, "cabinet 2 automatic confirmation");
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("分类柜内还有药吗？");
  }, "cabinet 2 inventory confirmation page");
  const secondCabinetLightSpeech = `${secondMedicine.name}所在的2号柜指示灯已亮`;
  await waitForNodeState(
    () => requests.audio.some((entry, index) => (
      index > firstCabinetCloseStopIndex
      && entry.type === "speak"
      && entry.text.includes(secondCabinetLightSpeech)
    )),
    "cabinet 2 collection speech"
  );

  const secondSessionAudio = requests.audio.slice(firstCabinetCloseStopIndex + 1);
  const secondGuidanceIndex = requests.audio.findIndex((entry, index) => (
    index > firstCabinetCloseStopIndex
    && entry.type === "speak"
    && entry.text.includes(secondMedicine.name)
    && entry.text.includes("请将手指平放在指纹传感器上")
  ));
  const secondCabinetSpeechIndex = requests.audio.findIndex((entry, index) => (
    index > firstCabinetCloseStopIndex
    && entry.type === "speak"
    && entry.text.includes(secondCabinetLightSpeech)
  ));
  const secondSessionTimeline = requestTimeline.slice(secondModalTimelineStart);
  const secondConfirmTimelineIndex = secondSessionTimeline.findIndex((entry) => entry.type === "confirm");
  const secondCabinetSpeechTimelineIndex = secondSessionTimeline.findIndex((entry) => (
    entry.type === "speak" && entry.text.includes(secondCabinetLightSpeech)
  ));
  assert.ok(secondGuidanceIndex > firstCabinetCloseStopIndex, "cabinet 2 identity page did not speak its own guidance");
  assert.ok(secondCabinetSpeechIndex > secondGuidanceIndex, "cabinet 2 collection speech did not follow its identity guidance");
  assert.ok(secondConfirmTimelineIndex >= 0, "cabinet 2 collection speech has no preceding confirmation request");
  assert.ok(
    secondCabinetSpeechTimelineIndex > secondConfirmTimelineIndex,
    "cabinet 2 collection speech started before the cabinet confirmation request"
  );
  assert.equal(
    requests.audio[secondGuidanceIndex - 1]?.type,
    "stop",
    "cabinet 2 identity guidance did not wait for an audio stop boundary"
  );
  assert.equal(
    requests.audio[secondCabinetSpeechIndex - 1]?.type,
    "stop",
    "cabinet 2 collection guidance did not stop the identity-page speech first"
  );
  assert.equal(
    secondSessionAudio.some((entry) => entry.type === "speak" && entry.text.includes(firstCabinetLightSpeech)),
    false,
    "cabinet 2 session replayed cabinet 1's stale cabinet-light speech"
  );

  await evaluate(`([...document.querySelectorAll('.dispense-modal button')]
    .find((button) => button.textContent.includes('还有药'))).click()`);
  await waitForNodeState(() => requests.inventory.length === 2, "cabinet 2 inventory observation");
  await waitForNodeState(() => requests.lightOff.length === 3, "cabinet 2 automatic cabinet light OFF");
  await waitForNodeState(
    async () => evaluate(`!document.querySelector('.dispense-modal')`),
    "cabinet 2 modal closing after cabinet light OFF"
  );
  await waitForNodeState(
    () => requests.audio.some((entry, index) => index > secondCabinetSpeechIndex && entry.type === "stop"),
    "audio stop after cabinet 2 session closes"
  );
  const secondCabinetCloseStopIndex = requests.audio.findIndex(
    (entry, index) => index > secondCabinetSpeechIndex && entry.type === "stop"
  );
  assert.deepEqual(
    [
      requests.audio[firstCabinetSpeechIndex]?.type,
      requests.audio[firstCabinetCloseStopIndex]?.type,
      requests.audio[secondGuidanceIndex]?.type,
      requests.audio[secondCabinetSpeechIndex]?.type,
      requests.audio[secondCabinetCloseStopIndex]?.type
    ],
    ["speak", "stop", "speak", "speak", "stop"],
    "two cabinet sessions did not preserve speak/stop session boundaries"
  );

  assessmentMode = "passed";
  confirmationMode = "success";
  lightOffFailuresRemaining = 1;
  Object.values(requests).forEach((items) => { items.length = 0; });
  requestOrder.length = 0;
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=depleted-off-failure`
  });
  await startFingerprintFlow();
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("分类柜内还有药吗？");
  }, "depleted inventory confirmation after cabinet light");
  await evaluate(`([...document.querySelectorAll('.dispense-modal button')]
    .find((button) => button.textContent.includes('已经用完'))).click()`);
  await waitForNodeState(() => requests.inventory.length === 1, "depleted inventory observation");
  await waitForNodeState(() => requests.lightOff.length === 1, "automatic OFF after depleted inventory page");
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("库存已保存，但指示灯关闭失败");
  }, "visible depleted-inventory OFF failure");
  assert.equal(
    await evaluate(`Boolean(document.querySelector('.inventory-light-off-retry:not([disabled])'))`),
    true,
    "depleted inventory must not dismiss the retry action before OFF is confirmed"
  );
  assert.doesNotMatch(
    await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`),
    /指示灯已关闭/,
    "a failed depleted-inventory OFF must not claim that the cabinet light is off"
  );
  await evaluate(`document.querySelector('.inventory-light-off-retry:not([disabled])').click()`);
  await waitForNodeState(() => requests.lightOff.length === 2, "retried depleted-inventory OFF request");
  await waitForNodeState(
    async () => evaluate(`!document.querySelector('.dispense-modal')`),
    "depleted-inventory modal closing only after OFF is confirmed"
  );
  assert.deepEqual(requestOrder, ["assess", "confirm", "inventory", "off", "off"]);

  assessmentMode = "passed";
  confirmationMode = "success";
  identityMode = "guest";
  lightOffFailuresRemaining = 0;
  deferNextInventoryResponse = true;
  deferredInventoryResponses.length = 0;
  Object.values(requests).forEach((items) => { items.length = 0; });
  requestOrder.length = 0;
  await evaluate(`(async () => {
    const ReactModule = await import('/@id/react');
    const React = ReactModule.default || ReactModule;
    const ReactDOMClientModule = await import('/@id/react-dom/client');
    const { createRoot } = ReactDOMClientModule.default || ReactDOMClientModule;
    const { DispenseConfirmModal } = await import('/src/components/DispenseConfirmModal.jsx');
    const raceMedicine = ${JSON.stringify(medicine)};
    const racePlan = {
      id: 'race-plan',
      service_user_id: '${registeredUser.id}',
      target_user: '${registeredUser.name}',
      time: '10:00'
    };
    const medicineUpdatedListener = () => { window.__lateInventoryUpdateCount += 1; };
    window.__lateInventoryUpdateCount = 0;
    window.addEventListener('zykh:medicine-updated', medicineUpdatedListener);
    const mount = (sessionName) => {
      const host = document.createElement('div');
      host.dataset.raceSession = sessionName;
      document.body.appendChild(host);
      const root = createRoot(host);
      root.render(React.createElement(DispenseConfirmModal, {
        medicine: raceMedicine,
        plan: { ...racePlan, id: 'race-plan-' + sessionName },
        open: true,
        submitting: false,
        result: '',
        error: '',
        onCancel: () => undefined,
        onSubmit: async () => ({
          ok: true,
          record_id: 'race-dispense-' + sessionName,
          inventory_confirmation_required: true
        })
      }));
      return { host, root };
    };
    window.__inventoryRaceHarness = {
      active: mount('a'),
      mount,
      medicineUpdatedListener
    };
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return true;
  })()`);
  await startFingerprintFlow();
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("分类柜内还有药吗？");
  }, "race session A inventory confirmation");
  await evaluate(`([...document.querySelectorAll('.dispense-modal button')]
    .find((button) => button.textContent.includes('还有药'))).click()`);
  await waitForNodeState(
    () => requests.inventory.length === 1 && deferredInventoryResponses.length === 1,
    "deferred race session A inventory request"
  );
  await evaluate(`(() => {
    window.__inventoryRaceHarness.active.root.unmount();
    window.__inventoryRaceHarness.active.host.remove();
    window.__inventoryRaceHarness.active = null;
  })()`);
  await waitForNodeState(() => requests.lightOff.length === 1, "race session A unmount OFF");
  await evaluate(`(async () => {
    window.__inventoryRaceHarness.active = window.__inventoryRaceHarness.mount('b');
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return true;
  })()`);
  await startFingerprintFlow();
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("分类柜内还有药吗？");
  }, "race session B cabinet light and inventory confirmation");
  const deferredInventory = deferredInventoryResponses.shift();
  await fulfillJson(deferredInventory.requestId, deferredInventory.payload);
  await delay(1250);
  assert.equal(
    requests.lightOff.length,
    1,
    "session A's late inventory response must not turn off session B's cabinet light"
  );
  assert.equal(
    await evaluate(`window.__lateInventoryUpdateCount`),
    0,
    "session A's late inventory response must not publish an update into session B"
  );
  assert.match(
    await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`),
    /分类柜内还有药吗？/,
    "session B must remain on its own inventory confirmation page"
  );
  await evaluate(`(() => {
    const harness = window.__inventoryRaceHarness;
    harness.active.root.unmount();
    harness.active.host.remove();
    window.removeEventListener('zykh:medicine-updated', harness.medicineUpdatedListener);
    delete window.__inventoryRaceHarness;
  })()`);
  await waitForNodeState(() => requests.lightOff.length === 2, "race session B cleanup OFF");

  Object.values(requests).forEach((items) => { items.length = 0; });
  requestOrder.length = 0;
  await evaluate(`(async () => {
    const ReactModule = await import('/@id/react');
    const React = ReactModule.default || ReactModule;
    const ReactDOMClientModule = await import('/@id/react-dom/client');
    const { createRoot } = ReactDOMClientModule.default || ReactDOMClientModule;
    const { DispenseConfirmModal } = await import('/src/components/DispenseConfirmModal.jsx');
    let resolveConfirmation;
    const confirmation = new Promise((resolve) => { resolveConfirmation = resolve; });
    window.__illuminateRaceAssessments = [];
    window.__illuminateRaceConfirmStarts = [];
    const mount = (sessionName) => {
      const host = document.createElement('div');
      host.dataset.illuminateRace = sessionName;
      document.body.appendChild(host);
      const root = createRoot(host);
      root.render(React.createElement(DispenseConfirmModal, {
        medicine: ${JSON.stringify(medicine)},
        manualAccess: true,
        open: true,
        submitting: false,
        result: '',
        error: '',
        onCancel: () => undefined,
        onAssessManual: async () => {
          window.__illuminateRaceAssessments.push(sessionName);
          return {
            ok: true,
            check_id: 'illuminate-race-check-' + sessionName,
            check_status: 'PASSED',
            reason_codes: [],
            message: '核查通过',
            expires_at: '2026-08-20 10:01:30',
            dispense_status: 'NOT_STARTED'
          };
        },
        onConfirmManual: async () => {
          window.__illuminateRaceConfirmStarts.push(sessionName);
          if (sessionName === 'a') return confirmation;
          return {
            ok: true,
            safety_check_id: 'illuminate-race-check-' + sessionName,
            dispense_status: 'DISPENSED',
            dispense_record_id: 'illuminate-race-dispense-' + sessionName,
            inventory_confirmation_required: true
          };
        }
      }));
      return { host, root };
    };
    window.__illuminateRaceHarness = {
      active: mount('a'),
      mount,
      resolveSuccess: () => resolveConfirmation({
        ok: true,
        safety_check_id: 'illuminate-race-check-a',
        dispense_status: 'DISPENSED',
        dispense_record_id: 'illuminate-race-dispense-a',
        inventory_confirmation_required: true
      })
    };
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return true;
  })()`);
  await startFingerprintFlow();
  await waitForNodeState(
    async () => evaluate(`window.__illuminateRaceConfirmStarts.includes('a')`),
    "deferred cabinet illumination request for session A"
  );
  await evaluate(`(() => {
    const harness = window.__illuminateRaceHarness;
    harness.active.root.unmount();
    harness.active.host.remove();
    harness.active = harness.mount('b');
  })()`);
  assert.equal(requests.lightOff.length, 0, "an unresolved illuminate request must not claim that OFF already ran");
  await startFingerprintFlow();
  await waitForNodeState(
    async () => evaluate(`window.__illuminateRaceAssessments.includes('b')`),
    "session B safety assessment while session A is settling"
  );
  await delay(150);
  assert.deepEqual(
    await evaluate(`window.__illuminateRaceConfirmStarts`),
    ["a"],
    "session B must not illuminate until session A's stale request has settled and been turned off"
  );
  await evaluate(`window.__illuminateRaceHarness.resolveSuccess()`);
  await waitForNodeState(
    () => requests.lightOff.length === 1,
    "best-effort OFF after session A's late illuminate success"
  );
  await waitForNodeState(
    async () => evaluate(`window.__illuminateRaceConfirmStarts.includes('b')`),
    "session B illumination after session A cleanup"
  );
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("分类柜内还有药吗？");
  }, "session B cabinet light and inventory confirmation");
  assert.equal(
    requests.lightOff.length,
    1,
    "session A's stale cleanup must finish before session B illuminates"
  );
  await evaluate(`(() => {
    const harness = window.__illuminateRaceHarness;
    harness.active.root.unmount();
    harness.active.host.remove();
    delete window.__illuminateRaceHarness;
    delete window.__illuminateRaceAssessments;
    delete window.__illuminateRaceConfirmStarts;
  })()`);
  await waitForNodeState(() => requests.lightOff.length === 2, "session B cleanup OFF");

  lightOffFailuresRemaining = 2;
  Object.values(requests).forEach((items) => { items.length = 0; });
  requestOrder.length = 0;
  await evaluate(`(async () => {
    const ReactModule = await import('/@id/react');
    const React = ReactModule.default || ReactModule;
    const ReactDOMClientModule = await import('/@id/react-dom/client');
    const { createRoot } = ReactDOMClientModule.default || ReactDOMClientModule;
    const { DispenseConfirmModal } = await import('/src/components/DispenseConfirmModal.jsx');
    let resolveConfirmation;
    const confirmation = new Promise((resolve) => { resolveConfirmation = resolve; });
    window.__failedCleanupAssessments = [];
    window.__failedCleanupConfirmStarts = [];
    const mount = (sessionName) => {
      const host = document.createElement('div');
      host.dataset.failedCleanupRace = sessionName;
      document.body.appendChild(host);
      const root = createRoot(host);
      root.render(React.createElement(DispenseConfirmModal, {
        medicine: ${JSON.stringify(medicine)},
        manualAccess: true,
        open: true,
        submitting: false,
        result: '',
        error: '',
        onCancel: () => undefined,
        onAssessManual: async () => {
          window.__failedCleanupAssessments.push(sessionName);
          return {
            ok: true,
            check_id: 'failed-cleanup-check-' + sessionName,
            check_status: 'PASSED',
            reason_codes: [],
            message: '核查通过',
            expires_at: '2026-08-20 10:01:30',
            dispense_status: 'NOT_STARTED'
          };
        },
        onConfirmManual: async () => {
          window.__failedCleanupConfirmStarts.push(sessionName);
          if (sessionName === 'a') return confirmation;
          return {
            ok: true,
            safety_check_id: 'failed-cleanup-check-' + sessionName,
            dispense_status: 'DISPENSED',
            dispense_record_id: 'failed-cleanup-dispense-' + sessionName,
            inventory_confirmation_required: true
          };
        }
      }));
      return { host, root };
    };
    window.__failedCleanupHarness = {
      active: mount('a'),
      mount,
      resolveA: () => resolveConfirmation({
        ok: true,
        safety_check_id: 'failed-cleanup-check-a',
        dispense_status: 'DISPENSED',
        dispense_record_id: 'failed-cleanup-dispense-a',
        inventory_confirmation_required: true
      })
    };
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return true;
  })()`);
  await startFingerprintFlow();
  await waitForNodeState(
    async () => evaluate(`window.__failedCleanupConfirmStarts.includes('a')`),
    "failed-cleanup session A illumination request"
  );
  await evaluate(`(() => {
    const harness = window.__failedCleanupHarness;
    harness.active.root.unmount();
    harness.active.host.remove();
    harness.active = harness.mount('b');
  })()`);
  await startFingerprintFlow();
  await waitForNodeState(
    async () => evaluate(`window.__failedCleanupAssessments.includes('b')`),
    "failed-cleanup session B safety assessment"
  );
  await evaluate(`window.__failedCleanupHarness.resolveA()`);
  await waitForNodeState(
    () => requests.lightOff.length === 2,
    "failed stale OFF followed by failed strict pre-illumination OFF",
    2_000
  );
  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "dispense_failed";
  }, "visible pre-illumination OFF failure");
  assert.deepEqual(
    await evaluate(`window.__failedCleanupConfirmStarts`),
    ["a"],
    "session B must not call the illumination endpoint while verified OFF cannot be established"
  );
  assert.match(
    await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`),
    /无法确认.*指示灯已关闭|未能确认.*指示灯已关闭/,
    "session B does not explain why illumination was blocked"
  );
  await evaluate(`(() => {
    const harness = window.__failedCleanupHarness;
    harness.active.root.unmount();
    harness.active.host.remove();
    harness.active = harness.mount('c');
  })()`);
  await startFingerprintFlow();
  await waitForNodeState(
    async () => evaluate(`window.__failedCleanupAssessments.includes('c')`),
    "recovery session C safety assessment"
  );
  await waitForNodeState(
    () => requests.lightOff.length === 3,
    "successful strict OFF before recovery session C illumination"
  );
  await waitForNodeState(
    async () => evaluate(`window.__failedCleanupConfirmStarts.includes('c')`),
    "recovery session C illumination after verified OFF"
  );
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("分类柜内还有药吗？");
  }, "recovery session C cabinet light and inventory confirmation");
  assert.deepEqual(
    await evaluate(`window.__failedCleanupConfirmStarts`),
    ["a", "c"],
    "only a session preceded by a successful verified OFF may illuminate after cleanup failure"
  );
  assert.equal(
    requests.lightOff.length,
    3,
    "recovery session C must illuminate only after the successful strict OFF"
  );
  await evaluate(`(() => {
    const harness = window.__failedCleanupHarness;
    harness.active.root.unmount();
    harness.active.host.remove();
    delete window.__failedCleanupHarness;
    delete window.__failedCleanupAssessments;
    delete window.__failedCleanupConfirmStarts;
  })()`);
  await waitForNodeState(() => requests.lightOff.length === 4, "recovery session C cleanup OFF");

  Object.values(requests).forEach((items) => { items.length = 0; });
  requestOrder.length = 0;
  await evaluate(`(async () => {
    const ReactModule = await import('/@id/react');
    const React = ReactModule.default || ReactModule;
    const ReactDOMClientModule = await import('/@id/react-dom/client');
    const { createRoot } = ReactDOMClientModule.default || ReactDOMClientModule;
    const { DispenseConfirmModal } = await import('/src/components/DispenseConfirmModal.jsx');
    const host = document.createElement('div');
    host.dataset.illuminateRace = 'late-network-error';
    document.body.appendChild(host);
    const root = createRoot(host);
    let rejectDispense;
    const dispense = new Promise((resolve, reject) => { rejectDispense = reject; });
    window.__ambiguousIlluminateStarted = false;
    root.render(React.createElement(DispenseConfirmModal, {
      medicine: ${JSON.stringify(medicine)},
      plan: {
        id: 'ambiguous-illuminate-plan',
        service_user_id: '${registeredUser.id}',
        target_user: '${registeredUser.name}',
        time: '10:00'
      },
      open: true,
      submitting: false,
      result: '',
      error: '',
      onCancel: () => undefined,
      onSubmit: async () => {
        window.__ambiguousIlluminateStarted = true;
        return dispense;
      }
    }));
    window.__ambiguousIlluminateHarness = {
      host,
      root,
      reject: () => rejectDispense(new TypeError('亮灯请求连接中断'))
    };
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return true;
  })()`);
  await startFingerprintFlow();
  await waitForNodeState(
    async () => evaluate(`window.__ambiguousIlluminateStarted === true`),
    "deferred plan illumination request"
  );
  await evaluate(`(() => {
    const harness = window.__ambiguousIlluminateHarness;
    harness.root.unmount();
    harness.host.remove();
  })()`);
  assert.equal(requests.lightOff.length, 0, "an in-flight ambiguous illuminate request cannot be cleaned before it settles");
  await evaluate(`window.__ambiguousIlluminateHarness.reject()`);
  await waitForNodeState(
    () => requests.lightOff.length === 1,
    "best-effort OFF after a stale ambiguous illuminate result"
  );
  await evaluate(`(() => {
    delete window.__ambiguousIlluminateHarness;
    delete window.__ambiguousIlluminateStarted;
  })()`);

  confirmationMode = "server_error";
  lightOffFailuresRemaining = 0;
  Object.values(requests).forEach((items) => { items.length = 0; });
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=confirm-503`
  });
  await startFingerprintFlow();
  await waitForNodeState(() => requests.confirm.length === 1, "503 manual confirmation");
  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "result_unknown";
  }, "503 confirmation result-unknown state");
  const uncertainView = await evaluate(`(() => ({
    status: document.querySelector('.manual-access-result')?.getAttribute('data-status') || '',
    text: document.querySelector('.dispense-modal')?.innerText || '',
    action: document.querySelector('.biometric-confirm-action:not([disabled])')?.textContent || ''
  }))()`);
  assert.equal(uncertainView.status, "result_unknown");
  assert.match(uncertainView.text, /请勿重复操作/, "uncertain physical result does not prevent retry");
  assert.match(uncertainView.text, /现场确认指示灯状态/, "uncertain physical result has no safe next step");
  assert.match(uncertainView.action, /关闭分类柜指示灯/, "uncertain physical result has no explicit safe OFF action");
  assert.doesNotMatch(uncertainView.action, /确认取药|点亮|再次/, "uncertain physical result can be physically retried");
  assert.equal(requests.legacyConfirm.length, 0);
  assert.equal(requests.directDispense.length, 0);
  await evaluate(`document.querySelector('.biometric-confirm-action:not([disabled])').click()`);
  await waitForNodeState(() => requests.lightOff.length === 1, "uncertain-result cabinet light OFF request");
  await waitForNodeState(
    async () => evaluate(`!document.querySelector('.dispense-modal')`),
    "uncertain-result modal closing only after cabinet light OFF"
  );

  confirmationMode = "network_error";
  lightOffFailuresRemaining = 0;
  Object.values(requests).forEach((items) => { items.length = 0; });
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=confirm-network-error`
  });
  await startFingerprintFlow();
  await waitForNodeState(() => requests.confirm.length === 1, "network-failed manual confirmation");
  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "result_unknown";
  }, "network-failed confirmation result-unknown state");
  const networkUnknownView = await evaluate(`(() => ({
    text: document.querySelector('.dispense-modal')?.innerText || '',
    action: document.querySelector('.biometric-confirm-action:not([disabled])')?.textContent || ''
  }))()`);
  assert.match(networkUnknownView.text, /请勿重复操作/);
  assert.match(networkUnknownView.text, /现场确认指示灯状态/);
  assert.match(networkUnknownView.action, /关闭分类柜指示灯/);
  assert.equal(requests.legacyConfirm.length, 0);
  assert.equal(requests.directDispense.length, 0);
  await evaluate(`document.querySelector('.biometric-confirm-action:not([disabled])').click()`);
  await waitForNodeState(() => requests.lightOff.length === 1, "network-unknown cabinet light OFF request");
  await waitForNodeState(
    async () => evaluate(`!document.querySelector('.dispense-modal')`),
    "network-unknown modal closing only after cabinet light OFF"
  );

  confirmationMode = "conflict";
  Object.values(requests).forEach((items) => { items.length = 0; });
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=confirm-409`
  });
  await startFingerprintFlow();
  await waitForNodeState(() => requests.confirm.length === 1, "409 manual confirmation");
  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "check_failed";
  }, "409 confirmation check-failed state");
  const rejectedView = await evaluate(`(() => ({
    text: document.querySelector('.dispense-modal')?.innerText || '',
    action: document.querySelector('.biometric-confirm-action:not([disabled])')?.textContent || ''
  }))()`);
  assert.match(rejectedView.text, /安全核查凭据已失效/);
  assert.match(rejectedView.text, /分类柜指示灯未亮/, "explicitly rejected confirmation does not keep the light off");
  assert.doesNotMatch(
    rejectedView.text,
    /已记录并将同步家属/,
    "a rejected confirmation without a terminal server event falsely claims family sync"
  );
  assert.doesNotMatch(rejectedView.text, /请勿重复操作/, "explicit 4xx rejection was misclassified as an unknown physical result");
  assert.match(rejectedView.action, /返回药品列表/);
  assert.equal(requests.legacyConfirm.length, 0);
  assert.equal(requests.directDispense.length, 0);

  confirmationMode = "success";
  identityMode = "no_face";
  assessmentMode = "guest";
  Object.values(requests).forEach((items) => { items.length = 0; });
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=no-face`
  });
  await startFaceFlow();
  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "check_failed";
  }, "unverified face check-failed state");
  const unverifiedFaceView = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
  assert.match(unverifiedFaceView, /分类柜指示灯未亮/);
  assert.doesNotMatch(
    unverifiedFaceView,
    /已记录并将同步家属/,
    "an unverified face outcome falsely claims a persisted family safety event"
  );
  assert.equal(requests.assess.length, 0, "an unverified face must not invent an assessment assertion");
  assert.equal(requests.confirm.length, 0);

  identityMode = "guest";
  assessmentMode = "guest";
  Object.values(requests).forEach((items) => { items.length = 0; });
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=guest`
  });
  await startFaceFlow();
  await waitForNodeState(async () => {
    if (requests.assess.length > 0) return true;
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("访客取药确认");
  }, "guest assessment or forbidden guest confirmation state");

  assert.equal(requests.assess.length, 1, "verified guest must enter the server safety assessment");
  assert.deepEqual(
    {
      service_user_id: requests.assess[0]?.service_user_id,
      verification_method: requests.assess[0]?.verification_method,
      verification_assertion_id: requests.assess[0]?.verification_assertion_id,
      expected_review_fingerprint: requests.assess[0]?.expected_review_fingerprint
    },
    {
      service_user_id: guestUser.id,
      verification_method: "face",
      verification_assertion_id: "identity-assertion-guest",
      expected_review_fingerprint: medicine.review_fingerprint
    },
    "guest assessment must use the issued identity assertion and selected medicine fingerprint"
  );
  const checkingView = await evaluate(`(() => ({
    role: document.querySelector('.manual-access-progress')?.getAttribute('role') || '',
    text: document.querySelector('.manual-access-progress')?.textContent || ''
  }))()`);
  assert.equal(checkingView.role, "status", "manual safety assessment has no announced checking state");
  assert.match(checkingView.text, /正在核查/, "checking state does not explain the pending safety assessment");
  assert.equal(requests.confirm.length, 0, "guest CHECK_FAILED result must not call manual confirmation");
  assert.equal(requests.legacyConfirm.length, 0, "guest manual pick must not call legacy dispense confirmation");
  assert.equal(requests.directDispense.length, 0, "guest manual pick must not call direct dispense");

  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "check_failed";
  }, "guest CHECK_FAILED result");

  const guestView = await evaluate(`(() => ({
    status: document.querySelector('.manual-access-result')?.getAttribute('data-status') || '',
    role: document.querySelector('.manual-access-result')?.getAttribute('role') || '',
    text: document.querySelector('.dispense-modal')?.innerText || ''
  }))()`);
  assert.equal(guestView.status, "check_failed", "PROFILE_UNAVAILABLE is not shown as CHECK_FAILED");
  assert.equal(guestView.role, "alert", "guest CHECK_FAILED result is not announced assertively");
  assert.match(guestView.text, /分类柜指示灯未亮/, "guest CHECK_FAILED result does not explicitly keep the cabinet light off");
  assert.doesNotMatch(guestView.text, /确认访客取药/, "guest still has a bypass action after identity verification");

  if (interceptionError) throw interceptionError;
  console.log("manual medication access blocked, passed and guest live: ok");
} catch (error) {
  const diagnostics = await evaluate(`(() => ({
    url: location.href,
    body: document.body?.innerText?.slice(0, 1800) || '',
    html: document.body?.innerHTML?.slice(0, 1800) || '',
    readyState: document.readyState
  }))()`).catch(() => null);
  throw new Error(`${error.message}\nBrowser diagnostics: ${JSON.stringify(diagnostics)}\nRequests: ${JSON.stringify(requests)}\nRuntime errors: ${JSON.stringify(runtimeErrors)}\nConsole: ${JSON.stringify(consoleMessages.slice(-12))}`);
} finally {
  await stopBrowser();
}
