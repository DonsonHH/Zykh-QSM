import React from "react";
import { AlertTriangle, CheckCircle2, PackageSearch } from "lucide-react";
import { RiskBadge } from "./RiskBadge.jsx";
import { SafetyNotice } from "./SafetyNotice.jsx";

export function InquiryResultPanel({ result, onViewCandidates }) {
  if (!result) {
    return (
      <aside className="inquiry-result-panel empty">
        <div className="inquiry-panel-heading">
          <p>问询结果</p>
          <h2>等待提交</h2>
        </div>
        <SafetyNotice>完成问询后，这里会显示风险等级、候选药品类别、禁忌提醒和后续建议。</SafetyNotice>
      </aside>
    );
  }

  const canProceed = result.can_proceed_to_dispense;

  return (
    <aside className="inquiry-result-panel">
      <div className="result-topline">
        <div className="inquiry-panel-heading">
          <p>问询结果</p>
          <h2>用药安全核验</h2>
        </div>
        <RiskBadge level={result.risk_level} label={result.risk_label} />
      </div>

      <section className="result-section summary">
        <h3>症状摘要</h3>
        <p>{result.symptoms_summary}</p>
      </section>

      <section className="result-section">
        <h3>候选药品类别</h3>
        <div className="result-chip-row">
          {result.suggested_categories.map((category) => (
            <span key={category}>{category}</span>
          ))}
        </div>
      </section>

      <section className="result-section candidates">
        <h3>当前可匹配药品</h3>
        {result.candidate_medicines.length ? (
          <div className="candidate-list">
            {result.candidate_medicines.slice(0, 3).map((medicine) => (
              <article key={medicine.id}>
                <PackageSearch size={20} aria-hidden="true" />
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

      <section className={`result-section warnings ${result.contraindication_warnings.length ? "show" : ""}`}>
        <h3>
          <AlertTriangle size={20} aria-hidden="true" />
          禁忌提醒
        </h3>
        {result.contraindication_warnings.length ? (
          <ul>
            {result.contraindication_warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : (
          <p>未填写明显禁忌，仍需在取药确认前再次核验。</p>
        )}
      </section>

      <SafetyNotice tone={canProceed ? "green" : "orange"}>{result.safety_notice}</SafetyNotice>

      <div className="result-next-steps">
        {result.next_steps.slice(0, 2).map((step) => (
          <span key={step}>
            <CheckCircle2 size={18} aria-hidden="true" />
            {step}
          </span>
        ))}
      </div>

      {canProceed ? (
        <button className="primary-action result-action" type="button" onClick={onViewCandidates}>
          查看候选药品
        </button>
      ) : (
        <div className="blocked-action">建议联系医生、村医或值守人员</div>
      )}
    </aside>
  );
}
