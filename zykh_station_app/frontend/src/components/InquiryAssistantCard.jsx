import React from "react";
import { ClipboardCheck, MessageCircleHeart } from "lucide-react";
import { SafetyNotice } from "./SafetyNotice.jsx";

export function InquiryAssistantCard({ result, assistantState }) {
  const channelLabel =
    assistantState?.source === "cloud"
      ? "云通道"
      : assistantState?.source === "local_fallback"
        ? "本地兜底"
        : assistantState?.loading
          ? "检查中"
          : "待提交";

  return (
    <section className="inquiry-assistant-panel" aria-label="问询说明">
      <div className="inquiry-panel-heading">
        <p>规则兜底</p>
        <h2>AI应急问询</h2>
      </div>

      <SafetyNotice>本系统仅提供用药与健康辅助建议，不能替代医生诊断或处方。</SafetyNotice>

      <div className="assistant-message">
        <MessageCircleHeart size={28} aria-hidden="true" />
        <p>请填写症状、持续时间、已用药和过敏禁忌信息，系统将进行风险提示与药品信息匹配。</p>
      </div>

      <div className="analysis-summary">
        <div className="analysis-title">
          <ClipboardCheck size={23} aria-hidden="true" />
          <strong>{result ? "规则分析摘要" : "等待问询"}</strong>
        </div>
        {result ? (
          <ul>
            <li>识别风险等级：{result.risk_label}</li>
            <li>问询通道：{channelLabel}</li>
            <li>候选类别：{result.suggested_categories.join(" / ") || "暂无"}</li>
            <li>{result.can_proceed_to_dispense ? "可查看候选药品并继续安全核验" : "暂不进入取药确认"}</li>
          </ul>
        ) : (
          <p>提交后会展示症状摘要和规则命中结果，不生成长篇聊天内容。</p>
        )}
      </div>
    </section>
  );
}
