import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const root = fileURLToPath(new URL("../", import.meta.url));
const vite = await createServer({
  root,
  logLevel: "silent",
  server: { middlewareMode: true },
  appType: "custom"
});

try {
  const module = await vite.ssrLoadModule("/src/pages/Vitals.jsx");
  assert.equal(
    typeof module.describeVitals,
    "function",
    "Vitals must expose its runtime status presentation for data-truth checks"
  );
  const demoStatus = module.describeVitals(
    {
      ok: true,
      status: "complete",
      temperature: 36.6,
      heart_rate: 72,
      spo2: 97,
      spo2_source: "demo_fallback",
      spo2_demo_fallback: true
    },
    "",
    "complete"
  );
  assert.equal(demoStatus.title, "测量完成");
  assert.match(demoStatus.summary, /已记录/, "classified fallback result must use the normal completed presentation");
  const approximateStatus = module.describeVitals(
    {
      ok: true,
      status: "complete",
      temperature: 36.5,
      heart_rate: 78,
      spo2: 96,
      quality: "approximate",
      heart_rate_source: "uart8_sensor",
      spo2_source: "uart8_sensor"
    },
    "",
    "complete"
  );
  assert.equal(approximateStatus.title, "测量完成");
  assert.match(approximateStatus.summary, /已记录/);
  assert.equal(
    typeof module.inquiryVitalsDisposition,
    "function",
    "embedded inquiry must classify demo vitals before persistence"
  );
  assert.deepEqual(
    module.inquiryVitalsDisposition({
      session_id: "vitals-demo-session",
      status: "complete",
      temperature: 36.6,
      heart_rate: 72,
      spo2: 97,
      spo2_source: "demo_fallback",
      spo2_demo_fallback: true
    }),
    {
      kind: "exit",
      outcome: {
        vitals_session_id: "vitals-demo-session",
        status: "demo_complete",
        error_message: ""
      }
    },
    "demo SpO2 must not enter inquiry persistence as a complete measurement"
  );
  assert.deepEqual(
    module.inquiryVitalsDisposition({
      session_id: "vitals-demo-heart-rate",
      status: "complete",
      temperature: 36.6,
      heart_rate: 70,
      spo2: 98,
      heart_rate_source: "demo_fallback",
      spo2_source: "uart8_sensor"
    }),
    {
      kind: "exit",
      outcome: {
        vitals_session_id: "vitals-demo-heart-rate",
        status: "demo_complete",
        error_message: ""
      }
    },
    "demo heart rate must remain isolated from inquiry persistence"
  );
  assert.deepEqual(
    module.inquiryVitalsDisposition({
      session_id: "vitals-approximate",
      status: "complete",
      temperature: 36.5,
      heart_rate: 78,
      spo2: 96,
      quality: "approximate",
      heart_rate_source: "uart8_sensor",
      spo2_source: "uart8_sensor"
    }),
    {
      kind: "exit",
      outcome: {
        vitals_session_id: "vitals-approximate",
        status: "demo_complete",
        error_message: ""
      }
    },
    "approximate sensor readings must finish the UI without entering inquiry reasoning"
  );
  assert.deepEqual(
    module.inquiryVitalsDisposition({
      session_id: "vitals-failed-session",
      status: "failed",
      historical_fallback: true,
      historical_temperature: 36.4,
      historical_heart_rate: 75,
      historical_spo2: 98,
      error_message: "手指信号未稳定。"
    }),
    {
      kind: "exit",
      outcome: {
        vitals_session_id: "vitals-failed-session",
        status: "failed",
        error_message: "手指信号未稳定。"
      }
    },
    "historical reference values must not complete an embedded inquiry measurement"
  );
  const inquiryModule = await vite.ssrLoadModule("/src/pages/Inquiry.jsx");
  assert.equal(
    typeof inquiryModule.buildInquiryVitalsPayload,
    "function",
    "inquiry must preserve metric provenance at its persistence boundary"
  );
  const inquiryPayload = inquiryModule.buildInquiryVitalsPayload({
    session_id: "vitals-live-session",
    temperature: 36.6,
    heart_rate: 72,
    spo2: 97,
    temperature_source: "gy614_sensor",
    heart_rate_source: "uart8_sensor",
    spo2_source: "demo_fallback",
    spo2_demo_fallback: true,
    measured_at: "2026-08-05T00:15:00+08:00"
  });
  assert.equal(inquiryPayload.spo2_source, "demo_fallback");
  assert.equal(inquiryPayload.vitals_session_id, "vitals-live-session");
  assert.equal(inquiryPayload.spo2_demo_fallback, true);
  assert.equal(
    Object.keys(inquiryPayload).some((key) => key.startsWith("historical_")),
    false,
    "historical reference fields must never enter the Inquiry payload"
  );

  assert.equal(
    typeof module.HistoricalVitalsReference,
    "function",
    "Vitals must expose a runtime-rendered historical reference block"
  );

  const html = renderToStaticMarkup(
    React.createElement(module.HistoricalVitalsReference, {
      result: {
        historical_fallback: true,
        temperature: 39.9,
        heart_rate: null,
        spo2: null,
        historical_temperature: 36.4,
        historical_heart_rate: 75,
        historical_spo2: 98,
        historical_measured_at: "2026-07-20T10:20:00+08:00"
      }
    })
  );

  assert.match(html, /历史体征参考/, "history must be labelled separately from this measurement");
  assert.match(html, /上次完整测量 · 仅供参考/, "history must not be presented as a current result");
  assert.match(html, /75次\/分/, "historical heart rate is missing");
  assert.match(html, /98%/, "historical SpO2 is missing");
  assert.match(html, /36\.4℃/, "historical temperature is missing");
  assert.doesNotMatch(html, /39\.9℃/, "current temperature leaked into the historical block");
} finally {
  await vite.close();
}

console.log("vitals historical reference display: ok");
