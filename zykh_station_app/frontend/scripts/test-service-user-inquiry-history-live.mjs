import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

import { mockDashboard } from "../src/api/mockData.js";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const profileDir = await mkdtemp(join(tmpdir(), "zykh-user-inquiry-history-"));
const vite = await createServer({
  root: frontendRoot,
  logLevel: "silent",
  server: { host: "127.0.0.1", port: 0, strictPort: false }
});
await vite.listen();
const baseUrl = vite.resolvedUrls?.local?.[0];
if (!baseUrl) throw new Error("isolated Vite server did not expose a loopback URL");

const debuggingPort = 11100 + Math.floor(Math.random() * 300);
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

const serviceUsers = [
  {
    id: "wang-nainai",
    name: "王奶奶",
    age: 72,
    profile: "高血压；既往胃溃疡",
    allergies: "青霉素类药物过敏",
    note: "女儿为绑定家属",
    status: "重点照护"
  },
  {
    id: "li-yeye",
    name: "李爷爷",
    age: 69,
    profile: "2 型糖尿病",
    allergies: "无已知药物过敏",
    note: "儿子为绑定家属",
    status: "日常照护"
  }
];

let socket;
let nextMessageId = 0;
let interceptionError = null;
const pending = new Map();
const runtimeErrors = [];
const consoleMessages = [];
const historyRequests = [];
let liHistoryAttempts = 0;

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

async function fulfillJson(requestId, payload, responseCode = 200) {
  await cdp("Fetch.fulfillRequest", {
    requestId,
    responseCode,
    responseHeaders: [{ name: "Content-Type", value: "application/json; charset=utf-8" }],
    body: Buffer.from(JSON.stringify(payload)).toString("base64")
  });
}

async function fulfillApiRequest({ requestId, request }) {
  const url = new URL(request.url);
  let payload = { ok: true };

  if (url.pathname === "/api/dashboard") {
    payload = mockDashboard;
  } else if (url.pathname === "/api/network/status") {
    payload = { label: "联网模式", wifi_connected: true, sim_connected: true };
  } else if (url.pathname === "/api/settings/basic") {
    payload = { settings: { idle_timeout_seconds: 0 }, warnings: [] };
  } else if (url.pathname === "/api/records/summary") {
    payload = { summary: { today_service_users: 2, pending_sync_count: 0, local_record_count: 1, today_plan_count: 2 } };
  } else if (url.pathname === "/api/records/recent") {
    payload = { records: [] };
  } else if (url.pathname === "/api/records/service-users") {
    payload = { users: serviceUsers };
  } else if (url.pathname === "/api/records/today-plans") {
    payload = { plans: [] };
  } else if (url.pathname === "/api/sync/status") {
    payload = { status: "已同步", pending_count: 0 };
  } else if (url.pathname === "/api/records/service-users/wang-nainai/inquiries") {
    historyRequests.push({ method: request.method, path: url.pathname, search: url.search });
    if (url.searchParams.get("cursor") === "cursor-wang-2") {
      await delay(220);
      payload = {
        ok: true,
        user_id: "wang-nainai",
        inquiries: [{
          session_id: "history-wang-002",
          happened_at: "2026-07-28 14:30:00",
          title: "头晕问询",
          case_summary: "午后短暂头晕，休息后缓解",
          risk_level: "low",
          risk_label: "低风险",
          outcome: "问询已记录",
          final_medicine_summary: ""
        }],
        next_cursor: null
      };
    } else {
      await delay(650);
      payload = {
        ok: true,
        user_id: "wang-nainai",
        inquiries: [{
          session_id: "history-wang-001",
          happened_at: "2026-08-10 09:05:00",
          title: "咳嗽复查",
          case_summary: "咳嗽两天，未见高热",
          risk_level: "medium",
          risk_label: "中风险",
          outcome: "已展示候选药品信息",
          final_medicine_summary: "蜜炼川贝枇杷膏",
          system_prompt: "SECRET SYSTEM PROMPT",
          reasoning_summary: "SECRET REASONING",
          messages: ["SECRET FULL CONVERSATION"],
          admin_debug: "SECRET DEBUG SOURCE"
        }],
        next_cursor: "cursor-wang-2"
      };
    }
  } else if (url.pathname === "/api/records/service-users/li-yeye/inquiries") {
    historyRequests.push({ method: request.method, path: url.pathname, search: url.search });
    liHistoryAttempts += 1;
    await delay(180);
    if (liHistoryAttempts === 1) {
      await fulfillJson(requestId, { detail: "历史问询暂时不可用，请稍后重试" }, 503);
      return;
    }
    payload = {
      ok: true,
      user_id: "li-yeye",
      inquiries: [],
      next_cursor: null
    };
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
          if (!String(error.message || error).includes("Invalid InterceptionId")) interceptionError = error;
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

async function waitFor(predicate, label, timeoutMs = 8_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await delay(25);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function stop() {
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
  await cdp("Fetch.enable", {
    patterns: [{ urlPattern: `${new URL(baseUrl).origin}/api/*`, requestStage: "Request" }]
  });
  await cdp("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 720,
    deviceScaleFactor: 1,
    mobile: false
  });
  await cdp("Page.navigate", { url: `${baseUrl}?page=records&awake=1&touchKeyboard=0` });

  await waitFor(
    async () => evaluate(`Boolean(document.querySelector('[aria-label="查看王奶奶的历史问询"]'))`),
    "accessible Wang service-user card"
  );
  const cardSemantics = await evaluate(`(() => {
    const card = document.querySelector('[aria-label="查看王奶奶的历史问询"]');
    return { tagName: card?.tagName || '', tabIndex: card?.tabIndex, type: card?.type || '' };
  })()`);
  assert.deepEqual(cardSemantics, { tagName: "BUTTON", tabIndex: 0, type: "button" });
  await evaluate(`document.querySelector('[aria-label="查看王奶奶的历史问询"]').click()`);
  await waitFor(() => historyRequests.length === 1, "Wang inquiry-history request");

  assert.deepEqual(historyRequests[0], {
    method: "GET",
    path: "/api/records/service-users/wang-nainai/inquiries",
    search: "?limit=20&cursor="
  });
  const loading = await evaluate(`(() => ({
    dialog: document.querySelector('[role="dialog"]')?.getAttribute('aria-modal') || '',
    status: document.querySelector('[role="dialog"] [role="status"]')?.textContent || ''
  }))()`);
  assert.equal(loading.dialog, "true", "history did not open in a modal drawer");
  assert.match(loading.status, /正在加载王奶奶的历史问询/, "drawer has no announced loading state");
  assert.equal(
    await evaluate(`document.querySelector('[role="dialog"]')?.contains(document.activeElement) || false`),
    true,
    "opening the drawer did not move keyboard focus into the dialog"
  );

  await waitFor(
    async () => evaluate(`Boolean(document.querySelector('[data-inquiry-session-id="history-wang-001"]'))`),
    "Wang inquiry summary"
  );
  const summary = await evaluate(`document.querySelector('[role="dialog"]')?.innerText || ''`);
  assert.match(summary, /2026-08-10 09:05/, "summary does not show when the inquiry happened");
  assert.match(summary, /咳嗽复查/, "summary does not show the title");
  assert.match(summary, /咳嗽两天，未见高热/, "summary does not show the case summary");
  assert.match(summary, /中风险/, "summary does not show the backend risk label");
  assert.match(summary, /已展示候选药品信息/, "summary does not show the outcome");
  assert.match(summary, /蜜炼川贝枇杷膏/, "summary does not show the final medicine summary");
  assert.doesNotMatch(
    summary,
    /SECRET SYSTEM PROMPT|SECRET REASONING|SECRET FULL CONVERSATION|SECRET DEBUG SOURCE/,
    "drawer exposed an admin or conversation debug field"
  );

  const loadMoreButton = await evaluate(`document.querySelector('.user-inquiry-history-load-more')?.textContent || ''`);
  assert.match(loadMoreButton, /继续加载/, "cursor response has no load-more action");
  await evaluate(`document.querySelector('.user-inquiry-history-load-more').click()`);
  await waitFor(
    () => historyRequests.some((request) => request.search === "?limit=20&cursor=cursor-wang-2"),
    "second Wang inquiry-history page"
  );
  await waitFor(
    async () => evaluate(`document.querySelectorAll('[data-inquiry-session-id]').length === 2`),
    "second Wang inquiry summary to append"
  );
  const pagedSummary = await evaluate(`document.querySelector('[role="dialog"]')?.innerText || ''`);
  assert.match(pagedSummary, /咳嗽复查/, "load more replaced the first page");
  assert.match(pagedSummary, /头晕问询/, "load more did not append the second page");
  assert.equal(
    await evaluate(`document.querySelectorAll('[data-inquiry-session-id="history-wang-001"]').length`),
    1,
    "pagination duplicated an existing inquiry summary"
  );
  assert.equal(
    await evaluate(`document.querySelector('.user-inquiry-history-load-more') === null`),
    true,
    "load-more action remained after the final page"
  );
  const drawerLayout = await evaluate(`(() => {
    const overlay = document.querySelector('.user-inquiry-history-overlay');
    const drawer = document.querySelector('.user-inquiry-history-drawer');
    const list = document.querySelector('.user-inquiry-history-list');
    const card = document.querySelector('[aria-label="查看王奶奶的历史问询"]');
    const bounds = drawer.getBoundingClientRect();
    return {
      overlayPosition: getComputedStyle(overlay).position,
      overlayBackdropFilter: getComputedStyle(overlay).backdropFilter,
      drawerWidth: Math.round(bounds.width),
      drawerTop: Math.round(bounds.top),
      drawerRight: Math.round(bounds.right),
      drawerBottom: Math.round(bounds.bottom),
      listOverflowY: getComputedStyle(list).overflowY,
      cardCursor: getComputedStyle(card).cursor
    };
  })()`);
  assert.equal(drawerLayout.overlayPosition, "fixed", "history drawer is not pinned to the kiosk viewport");
  assert.equal(drawerLayout.overlayBackdropFilter, "none", "history overlay uses an expensive blur filter");
  assert.ok(drawerLayout.drawerWidth >= 480 && drawerLayout.drawerWidth <= 640, `unexpected drawer width: ${drawerLayout.drawerWidth}`);
  assert.deepEqual(
    { top: drawerLayout.drawerTop, right: drawerLayout.drawerRight, bottom: drawerLayout.drawerBottom },
    { top: 0, right: 1280, bottom: 720 },
    "history drawer is clipped outside the 1280x720 kiosk viewport"
  );
  assert.equal(drawerLayout.listOverflowY, "auto", "history timeline cannot scroll independently");
  assert.equal(drawerLayout.cardCursor, "pointer", "clickable service-user card has no interaction affordance");

  await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`);
  await waitFor(
    async () => evaluate(`!document.querySelector('[role="dialog"]')`),
    "Wang history drawer to close"
  );
  await waitFor(
    async () => evaluate(`document.activeElement?.getAttribute('aria-label') === '查看王奶奶的历史问询'`),
    "focus to return to Wang service-user card"
  );
  assert.equal(
    await evaluate(`document.activeElement?.getAttribute('aria-label') || ''`),
    "查看王奶奶的历史问询",
    "closing the drawer did not restore focus to its service-user card"
  );
  await evaluate(`document.querySelector('[aria-label="查看李爷爷的历史问询"]').focus()`);
  const focusedCard = await evaluate(`document.activeElement?.getAttribute('aria-label') || ''`);
  assert.equal(focusedCard, "查看李爷爷的历史问询", "service-user card cannot receive keyboard focus");
  await evaluate(`document.activeElement.click()`);
  await waitFor(
    () => historyRequests.some((request) => request.path.endsWith("/li-yeye/inquiries")),
    "keyboard-opened Li inquiry history"
  );
  await waitFor(
    async () => evaluate(`Boolean(document.querySelector('.user-inquiry-history-error[role="alert"]'))`),
    "Li inquiry-history error state"
  );
  const errorText = await evaluate(`document.querySelector('.user-inquiry-history-error')?.innerText || ''`);
  assert.match(errorText, /历史问询暂时不可用，请稍后重试/);
  await evaluate(`document.querySelector('.user-inquiry-history-refresh').click()`);
  await waitFor(() => liHistoryAttempts === 2, "Li inquiry-history refresh request");
  await waitFor(
    async () => evaluate(`Boolean(document.querySelector('.user-inquiry-history-empty'))`),
    "Li empty inquiry-history state"
  );
  const emptyText = await evaluate(`document.querySelector('.user-inquiry-history-empty')?.innerText || ''`);
  assert.match(emptyText, /李爷爷暂无历史问询/);

  const liRequests = historyRequests.filter((request) => request.path.endsWith("/li-yeye/inquiries"));
  assert.deepEqual(liRequests, [
    { method: "GET", path: "/api/records/service-users/li-yeye/inquiries", search: "?limit=20&cursor=" },
    { method: "GET", path: "/api/records/service-users/li-yeye/inquiries", search: "?limit=20&cursor=" }
  ]);

  if (interceptionError) throw interceptionError;
  assert.deepEqual(runtimeErrors, [], "browser emitted runtime exceptions");
  console.log("service-user inquiry history tracer: ok");
} catch (error) {
  const diagnostics = await evaluate(`(() => ({
    url: location.href,
    body: document.body?.innerText?.slice(0, 1800) || '',
    html: document.body?.innerHTML?.slice(0, 1800) || '',
    readyState: document.readyState
  }))()`).catch(() => null);
  throw new Error(`${error.message}\nBrowser diagnostics: ${JSON.stringify(diagnostics)}\nHistory requests: ${JSON.stringify(historyRequests)}\nRuntime errors: ${JSON.stringify(runtimeErrors)}\nConsole: ${JSON.stringify(consoleMessages.slice(-12))}`);
} finally {
  await stop();
}
