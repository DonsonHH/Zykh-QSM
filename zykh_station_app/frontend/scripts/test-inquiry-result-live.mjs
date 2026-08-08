import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { mockDashboard } from "../src/api/mockData.js";

const baseUrl = process.env.QA_BASE_URL;
if (!baseUrl) throw new Error("test-inquiry-result-live requires QA_BASE_URL");
const parsedBaseUrl = new URL(baseUrl);
if (!["127.0.0.1", "localhost"].includes(parsedBaseUrl.hostname)) {
  throw new Error("test-inquiry-result-live only accepts a loopback frontend URL");
}
const screenshotPath = process.env.QA_SCREENSHOT_PATH
  ? resolve(process.env.QA_SCREENSHOT_PATH)
  : "";

const profileDir = await mkdtemp(join(tmpdir(), "zykh-inquiry-result-live-"));
const debuggingPort = 10100 + Math.floor(Math.random() * 300);
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

const sessionFixture = {
  session_id: "qa-inquiry-result",
  user_id: "",
  user_name: "访客",
  user_age: 0,
  user_profile: "身份未登记",
  user_allergies: "无",
  stage: "result",
  next_action: "show_recommendation",
  reply: "结合这些信息，我整理了一个主方案和一个备选。",
  source: "cloud_responses",
  risk_level: "low",
  risk_reasons: ["未触发硬性危险信号"],
  medication_safety_notices: [
    {
      code: "used_medicine_duplicate",
      message: "因本次已使用同成分药品，复方感冒灵颗粒未纳入本次候选。"
    }
  ],
  can_view_medicines: true,
  action_status: "ready",
  action_progress_index: 0,
  action_total_items: 1,
  action_items: [],
  selected_option_id: "",
  messages: [],
  vitals: {
    status: "complete",
    temperature: 36.7,
    heart_rate: 74,
    spo2: 98
  },
  extracted_information: {
    symptoms_text: "咽喉疼痛并伴有轻微头痛",
    case_summary: "咽喉疼痛并伴轻微头痛，今天早上开始。",
    observations: [
      { concept: "咽喉疼痛", status: "present", evidence: "吞咽时明显", source_turn: 1, confidence: 0.9 },
      { concept: "轻微头痛", status: "present", evidence: "太阳穴轻微胀痛", source_turn: 1, confidence: 0.86 }
    ],
    symptom_dimensions: ["咽喉疼痛", "轻微头痛"],
    duration: "今天早上开始",
    used_medicines: "未使用",
    allergy_or_contraindication: "无",
    final_assessment: {
      summary: "结合现有信息仍需观察。",
      possible_conditions: [
        {
          name: "急性上呼吸道感染",
          likelihood: "more_likely",
          supporting_evidence: ["咽喉疼痛：存在（吞咽时明显）"],
          non_supporting_evidence: []
        },
        {
          name: "环境刺激相关咽部不适",
          likelihood: "possible",
          supporting_evidence: ["轻微头痛：存在（太阳穴轻微胀痛）"],
          non_supporting_evidence: ["本次额温：36.7℃"]
        }
      ],
      next_steps: ["少量多次饮水并观察体温与症状变化"],
      seek_care_if: ["出现高热、呼吸困难或意识变化"]
    }
  },
  treatment_options: [
    {
      option_id: "A",
      label: "主方案",
      when: "当前以咽喉疼痛为主，可优先核对这一方案。",
      medicines: [
        {
          id: "slot-07-yinhuang",
          name: "银黄颗粒",
          category: "咽喉口腔",
          slot: "7",
          stock: 1,
          unit: "盒",
          safety_note: "高热或症状持续时联系医生",
          indications: "用于咽干、咽痛",
          dosage: "开水冲服，一次1至2袋，一日2次",
          recommended_usage: "开水冲服，一次1至2袋，一日2次",
          match_reason: "针对你吞咽时明显的咽喉疼痛",
          requires_existing_direction: false
        }
      ]
    },
    {
      option_id: "B",
      label: "备选方案",
      when: "如果局部咽喉肿痛更明显，可核对这一备选。",
      medicines: [
        {
          id: "slot-11-guilin-xiguashuang",
          name: "桂林西瓜霜",
          category: "咽喉口腔",
          slot: "11",
          stock: 1,
          unit: "瓶",
          safety_note: "喷敷时避免吸入气道",
          indications: "用于咽喉肿痛",
          dosage: "外用，喷、吹或敷于患处",
          recommended_usage: "外用，喷、吹或敷于患处",
          match_reason: "作为局部咽喉肿痛更明显时的备选",
          requires_existing_direction: false
        }
      ]
    }
  ],
  created_at: "2026-08-08T12:00:00+08:00",
  updated_at: "2026-08-08T12:00:00+08:00"
};

let socket;
let nextMessageId = 0;
let interceptionError = null;
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
  } else if (url.pathname === "/api/identity/resolve") {
    payload = { ok: false, status: "unavailable", message: "隔离测试不执行摄像头识别" };
  } else if (url.pathname === "/api/inquiry/sessions" && request.method === "POST") {
    payload = sessionFixture;
  } else if (url.pathname === "/api/inquiry/sessions/qa-inquiry-result/information") {
    payload = { ...sessionFixture, updated_at: "2026-08-08T12:00:01+08:00" };
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

  await evaluate(`(async () => {
    const waitFor = async (predicate, label) => {
      const deadline = performance.now() + 6000;
      while (performance.now() < deadline) {
        const value = predicate();
        if (value) return value;
        await new Promise(requestAnimationFrame);
      }
      throw new Error('Timed out waiting for ' + label);
    };
    const inquiryButton = await waitFor(
      () => [...document.querySelectorAll('.bottom-nav button')].find((button) => button.textContent.includes('问询')),
      'inquiry navigation'
    );
    inquiryButton.click();
    const guestButton = await waitFor(
      () => [...document.querySelectorAll('.inquiry-identity-gate button')].find((button) => button.textContent.includes('访客身份继续')),
      'explicit guest confirmation'
    );
    guestButton.click();
    const review = await waitFor(() => document.querySelector('.inquiry-information-review'), 'information review');
    const confirm = await waitFor(
      () => review.querySelector('.review-actions .primary-action:not(:disabled)'),
      'review confirmation'
    );
    confirm.click();
    await waitFor(() => document.querySelector('.inquiry-treatment-result'), 'treatment result');
    return true;
  })()`);

  const measurements = [];
  for (const viewport of [
    { width: 960, height: 600 },
    { width: 1024, height: 600 },
    { width: 1280, height: 720 }
  ]) {
    await cdp("Emulation.setDeviceMetricsOverride", {
      ...viewport,
      deviceScaleFactor: 2,
      mobile: false
    });
    await delay(120);
    measurements.push(await evaluate(`(() => {
      const result = document.querySelector('.inquiry-treatment-result');
      const flow = document.querySelector('.inquiry-flow-card');
      const body = document.querySelector('.treatment-result-body');
      const options = document.querySelector('.treatment-option-grid');
      const assessment = document.querySelector('.clinical-assessment-card');
      const footer = document.querySelector('.treatment-result-footer-row');
      const openButton = document.querySelector('.treatment-open-button');
      const medicineList = document.querySelector('.option-medicine-list');
      const optionCard = document.querySelector('.treatment-option-card');
      const medicineRow = optionCard.querySelector('.option-medicine-row:last-child');
      const confirmNotice = document.querySelector('.treatment-confirm-notice');
      const medicationSafetyNotices = document.querySelector('.medication-safety-notices');
      const rect = (element) => {
        const value = element.getBoundingClientRect();
        return { top: value.top, right: value.right, bottom: value.bottom, left: value.left, width: value.width, height: value.height };
      };
      return {
        viewport: { width: innerWidth, height: innerHeight },
        result: rect(result),
        flow: rect(flow),
        body: rect(body),
        options: rect(options),
        assessment: rect(assessment),
        footer: rect(footer),
        optionCard: rect(optionCard),
        medicineRow: rect(medicineRow),
        confirmNotice: rect(confirmNotice),
        medicationSafetyNotices: rect(medicationSafetyNotices),
        resultHorizontalOverflow: result.scrollWidth - result.clientWidth,
        bodyHorizontalOverflow: body.scrollWidth - body.clientWidth,
        bodyScrollable: body.scrollHeight > body.clientHeight,
        bodyOverflowY: getComputedStyle(body).overflowY,
        medicineListOverflow: getComputedStyle(medicineList).overflow,
        openButtonHeight: openButton.getBoundingClientRect().height,
        hasCauseHeading: assessment.textContent.includes('病因分析'),
        hasMedicationSafetyNotice: medicationSafetyNotices.textContent.includes('复方感冒灵颗粒未纳入本次候选'),
        hasDisclaimer: footer.textContent.includes('不构成诊断或处方') && footer.textContent.includes('请听医嘱')
      };
    })()`));
    if (screenshotPath && viewport.width === 960 && viewport.height === 600) {
      const screenshot = await cdp("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: false
      });
      await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
    }
  }

  if (interceptionError) throw interceptionError;
  for (const result of measurements) {
    assert.ok(result.flow.left >= 0 && result.flow.right <= result.viewport.width + 1, "inquiry flow exceeds the viewport horizontally");
    assert.ok(result.flow.top >= 0 && result.flow.bottom <= result.viewport.height + 1, "inquiry flow exceeds the viewport vertically");
    assert.ok(result.resultHorizontalOverflow <= 1, "result shell has horizontal overflow");
    assert.ok(result.bodyHorizontalOverflow <= 1, "result body has horizontal overflow");
    assert.equal(result.bodyOverflowY, "auto", "result body is not the vertical scroll owner");
    assert.equal(result.medicineListOverflow, "visible", "medicine list created a nested scroll container");
    assert.ok(
      result.medicineRow.bottom <= result.optionCard.bottom + 1,
      `medicine details overflow the option card: ${JSON.stringify({ viewport: result.viewport, optionCard: result.optionCard, medicineRow: result.medicineRow })}`
    );
    assert.ok(result.assessment.top >= result.options.top, "assessment appears before treatment options");
    assert.equal(result.hasMedicationSafetyNotice, true, "deterministic medication safety notice is not visible");
    assert.ok(result.medicationSafetyNotices.left >= result.body.left - 1 && result.medicationSafetyNotices.right <= result.body.right + 1, "medication safety notice overflows the result body");
    assert.ok(result.medicationSafetyNotices.bottom <= result.options.top + 1, "medication safety notice must appear before treatment options");
    assert.ok(result.confirmNotice.width >= 200, "medical disclaimer is squeezed into an unreadable column");
    assert.ok(result.openButtonHeight >= 48, "confirm action is below the touch target height");
    assert.equal(result.hasCauseHeading, true, "structured cause assessment is missing");
    assert.equal(result.hasDisclaimer, true, "fixed medical disclaimer is missing");
  }

  console.log("isolated inquiry result live layout: ok", measurements.map((item) => ({
    viewport: item.viewport,
    bodyScrollable: item.bodyScrollable,
    resultHorizontalOverflow: item.resultHorizontalOverflow
  })));
} finally {
  await stopBrowser();
}
