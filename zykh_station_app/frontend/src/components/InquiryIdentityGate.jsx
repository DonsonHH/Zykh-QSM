import React from "react";
import { BadgeCheck, RotateCcw, ScanFace, UserCheck, UserRound } from "lucide-react";

export function InquiryIdentityGate({
  candidate,
  status,
  onConfirm,
  onRetry,
  onRequestGuest
}) {
  const identifying = status === "identifying" || status === "idle";

  return (
    <section className={`inquiry-identity-gate ${candidate ? "has-candidate" : ""}`} aria-live="polite">
      <div className="inquiry-identity-visual" aria-hidden="true">
        {candidate ? (
          <span className="inquiry-identity-match-icon">
            <BadgeCheck size={84} strokeWidth={1.8} />
          </span>
        ) : (
          <ScanFace
            className={identifying ? "inquiry-identity-scanning-icon" : ""}
            size={112}
            strokeWidth={1.8}
          />
        )}
      </div>

      {candidate ? (
        <>
          <div className="inquiry-identity-copy">
            <span>识别到使用人</span>
            <h2>{candidate.name}</h2>
            <p>{[candidate.age ? `${candidate.age}岁` : "年龄待补充", candidate.conditions].filter(Boolean).join(" · ")}</p>
          </div>
          <div className="inquiry-identity-actions">
            <button type="button" className="secondary-action" onClick={onRetry}>
              <RotateCcw size={22} aria-hidden="true" />
              不是我
            </button>
            <button type="button" className="primary-action" onClick={onConfirm}>
              <UserCheck size={23} aria-hidden="true" />
              是我，开始问询
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="inquiry-identity-copy">
            <span>AI 应急问询</span>
            <h2>{identifying ? "正在确认使用人" : "暂未识别到使用人"}</h2>
          </div>
          {identifying ? (
            <button type="button" className="secondary-action inquiry-identity-retry" onClick={onRequestGuest}>
              <UserRound size={23} aria-hidden="true" />
              不等待识别，以访客身份继续
            </button>
          ) : (
            <div className="inquiry-identity-actions">
              <button type="button" className="secondary-action" onClick={onRetry}>
                <RotateCcw size={23} aria-hidden="true" />
                重新识别
              </button>
              <button type="button" className="primary-action" onClick={onRequestGuest}>
                <UserRound size={23} aria-hidden="true" />
                以访客身份继续
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
