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
  cabinet_label: "口服药品",
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
  legacyConfirm: [],
  directDispense: [],
  lightOff: []
};
let assessmentMode = "blocked";
let confirmationMode = "success";
let identityMode = "guest";
let lightOffFailuresRemaining = 1;

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
      total: 1,
      warehouse_total: 3,
      categories: [medicine.category],
      cabinets: [{
        id: 1,
        label: "口服药品",
        description: "口服药品分类柜",
        medicine_ids: [medicine.id]
      }, {
        id: 2,
        label: "外用药品",
        description: "外用药品分类柜",
        medicine_ids: []
      }, {
        id: 3,
        label: "医疗护理用品",
        description: "医疗护理用品分类柜",
        medicine_ids: []
      }],
      medicines: [medicine]
    };
  } else if (url.pathname === `/api/medicines/${medicine.id}`) {
    payload = { ok: true, medicine };
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
        dispense_record_id: "dispense-record-manual-passed"
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
  } else if (url.pathname === "/api/qsm/cabinet-light/off") {
    requests.lightOff.push(jsonBody(request));
    if (lightOffFailuresRemaining > 0) {
      lightOffFailuresRemaining -= 1;
      await fulfillJson(requestId, { detail: "控制器未确认 OFF，请重试" }, 503);
      return;
    }
    payload = { ok: true, result: "off", message: "分类柜指示灯已关闭" };
  } else if (["/api/audio/speak", "/api/audio/stream/stop"].includes(url.pathname)) {
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
  Object.values(requests).forEach((items) => { items.length = 0; });
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=passed`
  });
  await startFingerprintFlow();
  await waitForNodeState(() => requests.assess.length === 1, "PASSED manual assessment");
  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "passed";
  }, "PASSED assessment result");
  assert.equal(requests.confirm.length, 0, "PASSED assessment must wait for an explicit user confirmation");
  assert.equal(requests.legacyConfirm.length, 0, "PASSED manual flow must not fall back to legacy dispense");

  const passedView = await evaluate(`(() => ({
    status: document.querySelector('.manual-access-result')?.getAttribute('data-status') || '',
    text: document.querySelector('.dispense-modal')?.innerText || '',
    action: document.querySelector('.biometric-confirm-action:not([disabled])')?.textContent || ''
  }))()`);
  assert.equal(passedView.status, "passed", "PASSED response is not rendered as a passed safety state");
  assert.match(passedView.text, /核查通过/, "PASSED state does not explain the safety result");
  assert.match(passedView.action, /确认取药并亮灯/, "PASSED state has no explicit final confirmation action");

  await evaluate(`document.querySelector('.biometric-confirm-action:not([disabled])').click()`);
  await waitForNodeState(() => requests.confirm.length > 0, "explicit manual confirmation");
  assert.deepEqual(
    {
      safety_check_id: requests.confirm[0]?.safety_check_id,
      confirmed_safety_notice: requests.confirm[0]?.confirmed_safety_notice
    },
    {
      safety_check_id: "safety-check-passed",
      confirmed_safety_notice: true
    },
    "manual confirmation must consume the passed one-time safety check"
  );
  assert.match(String(requests.confirm[0]?.request_id || ""), /^manual-confirm-/, "confirmation request has no idempotency key");
  assert.equal(requests.legacyConfirm.length, 0, "explicit manual confirmation must not call the legacy endpoint");
  assert.equal(requests.directDispense.length, 0, "explicit manual confirmation must not call direct dispense");
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("分类柜指示灯已亮");
  }, "confirmed cabinet-light result");
  const litCabinetView = await evaluate(`(() => ({
    text: document.querySelector('.dispense-modal')?.innerText || '',
    action: document.querySelector('.biometric-confirm-action:not([disabled])')?.textContent || ''
  }))()`);
  assert.match(litCabinetView.text, /请自行打开亮灯的分类柜取药/);
  assert.match(litCabinetView.action, /我已取药，关闭指示灯/);
  assert.equal(requests.lightOff.length, 0, "cabinet light must remain on until the user confirms taking the medicine");
  await evaluate(`document.querySelector('.biometric-confirm-action:not([disabled])').click()`);
  await waitForNodeState(() => requests.lightOff.length === 1, "explicit cabinet light OFF request");
  await waitForNodeState(async () => {
    const text = await evaluate(`document.querySelector('.dispense-modal')?.innerText || ''`);
    return text.includes("控制器未确认 OFF，请重试");
  }, "cabinet light OFF failure recovery message");
  assert.equal(
    await evaluate(`Boolean(document.querySelector('.dispense-modal .biometric-confirm-action:not([disabled])'))`),
    true,
    "failed OFF acknowledgement must remain on screen with a retry action"
  );
  await evaluate(`document.querySelector('.biometric-confirm-action:not([disabled])').click()`);
  await waitForNodeState(() => requests.lightOff.length === 2, "retried cabinet light OFF request");
  await waitForNodeState(
    async () => evaluate(`!document.querySelector('.dispense-modal')`),
    "dispense modal closing after cabinet light OFF"
  );

  confirmationMode = "server_error";
  Object.values(requests).forEach((items) => { items.length = 0; });
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=confirm-503`
  });
  await startFingerprintFlow();
  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "passed";
  }, "PASSED assessment before uncertain confirmation");
  await evaluate(`document.querySelector('.biometric-confirm-action:not([disabled])').click()`);
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
  Object.values(requests).forEach((items) => { items.length = 0; });
  await cdp("Page.navigate", {
    url: `${baseUrl}?page=medicines&awake=1&touchKeyboard=0&medicineId=${medicine.id}&dispenseModal=1&scenario=confirm-network-error`
  });
  await startFingerprintFlow();
  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "passed";
  }, "PASSED assessment before network-failed confirmation");
  await evaluate(`document.querySelector('.biometric-confirm-action:not([disabled])').click()`);
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
  await waitForNodeState(async () => {
    const status = await evaluate(`document.querySelector('.manual-access-result')?.getAttribute('data-status') || ''`);
    return status === "passed";
  }, "PASSED assessment before rejected confirmation");
  await evaluate(`document.querySelector('.biometric-confirm-action:not([disabled])').click()`);
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
