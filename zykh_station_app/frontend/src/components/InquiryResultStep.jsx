import React from "react";
import { AlertTriangle, Home, PackageSearch, RotateCcw } from "lucide-react";
import { RiskBadge } from "./RiskBadge.jsx";
import { SafetyNotice } from "./SafetyNotice.jsx";

export function InquiryResultStep({ result, blockedReason, onViewCandidates, onRestart, onHome }) {
  const canProceed = Boolean(result?.can_proceed_to_dispense) && !blockedReason;
  const categories = result?.suggested_categories || [];
  const medicines = result?.candidate_medicines || [];
  const warnings = result?.contraindication_warnings || [];
  const nextSteps = blockedReason ? [blockedReason] : result?.next_steps || [];

  return (
    <section className="inquiry-result-step">
      <div className="result-flow-head">
        <div className="inquiry-flow-heading compact">
          <p>问询结果</p>
          <h2>结构化风险提示</h2>
          <span>{result.symptoms_summary}</span>
        </div>
        <RiskBadge level={result.risk_level} label={result.risk_label} />
      </div>

      <div className="result-flow-grid">
        <section className="flow-result-block">
          <h3>候选药品类别</h3>
          <div className="result-chip-row large">
            {categories.length ? categories.map((category) => <span key={category}>{category}</span>) : <span>暂无匹配类别</span>}
          </div>
        </section>

        <section className="flow-result-block">
          <h3>当前可匹配药品</h3>
          {medicines.length ? (
            <div className="flow-candidate-list">
              {medicines.slice(0, 2).map((medicine) => (
                <article key={medicine.id}>
                  <PackageSearch size={21} aria-hidden="true" />
                  <strong>{medicine.name}</strong>
                  <span>
                    {medicine.stock}
                    {medicine.unit}
                  </span>
                </article>
              ))}
            </div>
          ) : (
            <p className="muted-line">暂无可匹配库存，请联系现场人员。</p>
          )}
        </section>

        <section className={`flow-result-block warning ${warnings.length || blockedReason ? "show" : ""}`}>
          <h3>
            <AlertTriangle size={20} aria-hidden="true" />
            禁忌提醒
          </h3>
          {warnings.length || blockedReason ? (
            <ul>
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
              {blockedReason ? <li>{blockedReason}</li> : null}
            </ul>
          ) : (
            <p>未填写明显禁忌，取药前仍需再次核验。</p>
          )}
        </section>

        <section className="flow-result-block">
          <h3>后续建议</h3>
          <div className="flow-next-list">
            {nextSteps.slice(0, 2).map((step) => (
              <span key={step}>{step}</span>
            ))}
          </div>
        </section>
      </div>

      <SafetyNotice tone={canProceed ? "green" : "orange"}>{result.safety_notice}</SafetyNotice>

      {canProceed ? (
        <button className="primary-action result-flow-action" type="button" onClick={onViewCandidates}>
          查看候选药品
        </button>
      ) : (
        <div className="blocked-action result-flow-blocked">建议联系医生、村医或现场值守人员</div>
      )}

      <div className="result-bottom-actions">
        <button className="secondary-action" type="button" onClick={onRestart}>
          <RotateCcw size={21} aria-hidden="true" />
          重新问询
        </button>
        <button className="secondary-action" type="button" onClick={onHome}>
          <Home size={21} aria-hidden="true" />
          返回首页
        </button>
      </div>
    </section>
  );
}
