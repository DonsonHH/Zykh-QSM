import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = fileURLToPath(new URL("../", import.meta.url));
const vite = await createServer({
  root,
  logLevel: "silent",
  server: { middlewareMode: true },
  appType: "custom"
});

try {
  const { describeVitals } = await vite.ssrLoadModule("/src/pages/Vitals.jsx");
  const { normalizeVitalsStartFailure } = await vite.ssrLoadModule(
    "/src/adapters/vitalsSessionAdapter.js"
  );
  const cases = [
    ["no_protocol_frames", "设备通信无数据", "请检查串口连接和模块供电"],
    ["no_finger", "未检测到手指", "请用指腹完整覆盖传感器"],
    ["core_not_stable", "手指信号未稳定", "请保持手指完整覆盖并尽量不动"],
    ["spo2_not_stable", "血氧仍未稳定", "请保持手指不动后重试"],
    ["heart_rate_not_stable", "心率仍未稳定", "请保持手指不动后重试"],
    ["temperature_unavailable", "额温未读取", "请重新对准额温传感器"],
    ["hardware_start_timeout", "设备启动超时", "请检查设备连接后重试"],
    ["uart_device_missing", "串口设备未连接", "请检查体征模块连接和供电"],
    ["uart_busy", "体征设备正忙", "请等待上一轮测量结束"],
    ["session_busy", "上一轮测量未结束", "请稍候再开始新的测量"],
    ["worker_start_failed", "测量服务启动失败", "请联系值守员检查板端服务"],
    ["hardware_start_failed", "设备启动失败", "请检查设备连接后重试"],
    ["uart_lock_error", "串口通信失败", "请联系值守员检查串口服务"],
    ["uart_config_error", "串口通信失败", "请联系值守员检查串口服务"],
    ["uart_open_error", "串口通信失败", "请联系值守员检查串口服务"],
    ["uart_write_error", "串口通信失败", "请联系值守员检查串口服务"],
    ["uart_stop_failed", "设备停止失败", "请联系值守员检查体征模块"],
    ["invalid_session_id", "测量会话无效", "请重新开始测量"],
    ["session_not_found", "测量会话已失效", "请重新开始测量"],
    ["gateway_error", "测量服务异常", "请稍后重试或联系值守员"],
    ["transport_error", "通信连接中断", "请检查主机与板端连接后重试"]
  ];

  for (const [failureReason, title, summary] of cases) {
    const presentation = describeVitals(
      {
        ok: false,
        status: "failed",
        hardware_started: failureReason !== "hardware_start_timeout",
        failure_reason: failureReason,
        error_message: `diagnostic:${failureReason}`
      },
      "",
      "failed"
    );
    assert.equal(presentation.title, title, `${failureReason} title is inaccurate`);
    assert.equal(presentation.summary, summary, `${failureReason} guidance is inaccurate`);
    assert.equal(
      presentation.detail,
      `diagnostic:${failureReason}`,
      `${failureReason} must retain the concrete diagnostic detail`
    );
  }

  assert.deepEqual(
    describeVitals(
      {
        status: "failed",
        failure_reason: "transport_error",
        transport_retrying: true,
        error_message: "status connection reset"
      },
      "",
      "stabilizing"
    ),
    {
      tone: "active",
      title: "通信短暂中断",
      summary: "正在恢复当前测量",
      detail: "status connection reset"
    },
    "an in-progress transport retry must not look like a finger or warmup problem"
  );

  const hardwareStartFailure = normalizeVitalsStartFailure({
    ok: false,
    status: "failed",
    hardware_started: false,
    communication_status: "gateway_available",
    failure_reason: "uart_device_missing",
    error_message: "UART8 is missing"
  });
  assert.equal(hardwareStartFailure.failure_reason, "uart_device_missing");
  assert.equal(hardwareStartFailure.error_message, "UART8 is missing");
  assert.equal(
    describeVitals(hardwareStartFailure, "", hardwareStartFailure.status).title,
    "串口设备未连接",
    "a structured start rejection must retain its concrete failure reason"
  );

  const unreachableStart = normalizeVitalsStartFailure(null, "host connection refused");
  assert.equal(unreachableStart.failure_reason, "transport_error");
  assert.equal(unreachableStart.communication_status, "gateway_unreachable");
  assert.equal(unreachableStart.error_message, "host connection refused");
  assert.equal(
    describeVitals(unreachableStart, "", unreachableStart.status).title,
    "通信连接中断",
    "a browser-to-host start failure must be presented as a communication error"
  );
} finally {
  await vite.close();
}

console.log("vitals failure reason presentation: ok");
