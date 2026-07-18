import React from "react";
import { AlertTriangle, Home, PackageSearch, RotateCcw, ShieldCheck } from "lucide-react";
import { RiskBadge } from "./RiskBadge.jsx";
import { SafetyNotice } from "./SafetyNotice.jsx";
import { aiSourceLabel } from "../utils/ai.js";

const riskLabels = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  emergency: "紧急风险"
};

export function InquiryResultStep({ result, onViewCandidates, onRestart, onHome }) {
  const canProceed = Boolean(result?.can_view_medicines && result?.primary_candidate);
  const candidates = [
    result?.primary_candidate ? { ...result.primary_candidate, optionLabel: "主候选" } : null,
    result?.alternative_candidate ? { ...result.alternative_candidate, optionLabel: "备选" } : null
  ].filter(Boolean);
  const summary = symptomSummary(result?.extracted_information);
  const categories = [...new Set(candidates.map((candidate) => candidate.category))];
  const warnings = contraindicationWarnings(result);
  const channelLabel = aiSourceLabel(result?.source);
  const highRisk = ["high", "emergency"].includes(result?.risk_level);

  return (
    <section className="inquiry-result-step">
      <div className="result-flow-head">
        <span className={`result-risk-motion ${result?.risk_level === "low" ? "low" : "warn"}`} role="img" aria-label={riskLabels[result?.risk_level] || "风险提示"}>
          {result?.risk_level === "low" ? <ShieldCheck size={42} /> : <AlertTriangle size={42} />}
        </span>
        <div className="inquiry-flow-heading compact">
          <p>问询结果</p>
          <h2>用药安全核验</h2>
          <span>{summary}</span>
          <small className="result-ai-channel">{channelLabel}</small>
        </div>
        <RiskBadge level={result.risk_level} label={riskLabels[result.risk_level] || "待核验"} />
      </div>

      <div className="result-flow-grid">
        <section className="flow-result-block">
          <h3>候选类别</h3>
          <div className="result-chip-row large">
            {categories.length ? categories.map((category) => <span key={category}>{category}</span>) : <span>本次不展示候选</span>}
          </div>
        </section>

        <section className="flow-result-block">
          <h3>候选药品</h3>
          {candidates.length ? (
            <div className="flow-candidate-list">
              {candidates.map((medicine) => (
                <article key={medicine.id}>
                  <PackageSearch size={21} aria-hidden="true" />
                  <strong><em>{medicine.optionLabel}</em>{medicine.name}</strong>
                  <span>{medicine.slot}号仓</span>
                </article>
              ))}
            </div>
          ) : <p className="muted-line">高风险、紧急风险或无合格库存时不展示候选。</p>}
        </section>

        <section className={`flow-result-block warning ${warnings.length ? "show" : ""}`}>
          <h3><AlertTriangle size={20} aria-hidden="true" />禁忌核验</h3>
          {warnings.length ? <ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : <p>取药前仍需核对实物说明和个人禁忌。</p>}
        </section>

        <section className="flow-result-block">
          <h3>核验结论</h3>
          <div className="flow-next-list">
            {(result.risk_reasons || []).slice(0, 2).map((reason) => <span key={reason}>{reason}</span>)}
          </div>
        </section>
      </div>

      <SafetyNotice tone={canProceed ? "green" : "orange"}>
        {highRisk
          ? "本次不提供候选药品，请联系医生、家人或现场协助人员。"
          : "主候选与备选是二选一的信息参考，不表示联合使用；后续仍需完成原有取药确认。"}
      </SafetyNotice>

      {canProceed ? (
        <button className="primary-action result-flow-action" type="button" onClick={onViewCandidates}>查看主候选药品</button>
      ) : (
        <div className="blocked-action result-flow-blocked">建议联系医生、家人或现场协助人员</div>
      )}

      <div className="result-bottom-actions">
        <button className="secondary-action" type="button" onClick={onRestart}><RotateCcw size={21} aria-hidden="true" />重新问询</button>
        <button className="secondary-action" type="button" onClick={onHome}><Home size={21} aria-hidden="true" />返回首页</button>
      </div>
    </section>
  );
}

function symptomSummary(extracted = {}) {
  const evidence = Object.values(extracted.dimension_evidence || {}).filter(Boolean);
  const parts = [evidence.join("、"), extracted.duration ? `持续${extracted.duration}` : ""].filter(Boolean);
  return parts.join("，") || "已完成本次信息整理";
}

function contraindicationWarnings(result) {
  const allergy = String(result?.extracted_information?.allergy_or_contraindication || "").trim();
  if (!allergy || ["无", "没有", "不确定"].includes(allergy)) return [];
  return [`已记录：${allergy}`, "候选已排除明显禁忌冲突项，取药前仍需再次核对。"];
}
