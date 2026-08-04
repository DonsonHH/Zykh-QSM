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
  assert.equal(demoStatus.title, "演示结果");
  assert.match(demoStatus.summary, /未保存/, "demo SpO2 must not be presented as recorded data");
  assert.equal(
    typeof module.inquiryVitalsDisposition,
    "function",
    "embedded inquiry must classify demo vitals before persistence"
  );
  assert.deepEqual(
    module.inquiryVitalsDisposition({
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
        status: "failed",
        error_message: "血氧为演示值，本次体征未写入问询。"
      }
    },
    "demo SpO2 must not enter inquiry persistence as a complete measurement"
  );
  assert.deepEqual(
    module.inquiryVitalsDisposition({
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
