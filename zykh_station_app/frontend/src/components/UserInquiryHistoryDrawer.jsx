import React, { useEffect, useRef } from "react";
import { RefreshCw, X } from "lucide-react";

export function UserInquiryHistoryDrawer({ user, state, onClose, onRefresh, onLoadMore }) {
  const closeButtonRef = useRef(null);
  const closeHandlerRef = useRef(onClose);
  closeHandlerRef.current = onClose;

  useEffect(() => {
    closeButtonRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeHandlerRef.current?.();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [user?.id]);

  if (!user) return null;

  return (
    <div className="user-inquiry-history-overlay">
      <aside
        className="user-inquiry-history-drawer"
        role="dialog"
        aria-modal="true"
        aria-busy={state.loading || state.loadingMore}
        aria-labelledby="user-inquiry-history-title"
      >
        <header>
          <div>
            <span>{user.name}</span>
            <h2 id="user-inquiry-history-title">历史问询</h2>
          </div>
          <div className="user-inquiry-history-actions">
            <button
              type="button"
              className="user-inquiry-history-refresh"
              aria-label={`刷新${user.name}的历史问询`}
              disabled={state.loading}
              onClick={onRefresh}
            >
              <RefreshCw aria-hidden="true" />
            </button>
            <button ref={closeButtonRef} type="button" aria-label="关闭历史问询" onClick={onClose}>
              <X aria-hidden="true" />
            </button>
          </div>
        </header>

        {state.loading ? (
          <p role="status">正在加载{user.name}的历史问询…</p>
        ) : state.error ? (
          <div className="user-inquiry-history-error" role="alert">
            <strong>历史问询加载失败</strong>
            <p>{state.error}</p>
          </div>
        ) : state.inquiries.length === 0 ? (
          <div className="user-inquiry-history-empty" role="status">
            <strong>{user.name}暂无历史问询</strong>
            <p>完成问询后，摘要会按时间显示在这里。</p>
          </div>
        ) : (
          <div className="user-inquiry-history-list">
            {state.inquiries.map((inquiry) => {
              const {
                session_id: sessionId,
                happened_at: happenedAt,
                title,
                case_summary: caseSummary,
                risk_level: riskLevel,
                risk_label: riskLabel,
                risk_reasons: riskReasons = [],
                outcome,
                no_medicine_reason: noMedicineReason,
                final_medicine_summary: finalMedicineSummary
              } = inquiry;
              return (
                <article
                  key={sessionId}
                  className="user-inquiry-history-item"
                  data-inquiry-session-id={sessionId}
                  data-risk-level={riskLevel || "unknown"}
                >
                  <div className="user-inquiry-history-meta">
                    <time>{happenedAt}</time>
                    <span>{riskLabel}</span>
                  </div>
                  <h3>{title}</h3>
                  <p>{caseSummary}</p>
                  <dl>
                    <div>
                      <dt>问询结果</dt>
                      <dd>{outcome}</dd>
                    </div>
                    {riskReasons.length ? (
                      <div>
                        <dt>风险依据</dt>
                        <dd>
                          <ul className="user-inquiry-history-reasons">
                            {riskReasons.map((reason) => <li key={reason}>{reason}</li>)}
                          </ul>
                        </dd>
                      </div>
                    ) : null}
                    {noMedicineReason ? (
                      <div>
                        <dt>未提供药品原因</dt>
                        <dd>{noMedicineReason}</dd>
                      </div>
                    ) : null}
                    {finalMedicineSummary ? (
                      <div>
                        <dt>最终药品</dt>
                        <dd>{finalMedicineSummary}</dd>
                      </div>
                    ) : null}
                  </dl>
                </article>
              );
            })}
            {state.nextCursor ? (
              <button
                type="button"
                className="user-inquiry-history-load-more"
                disabled={state.loadingMore}
                aria-busy={state.loadingMore}
                onClick={onLoadMore}
              >
                {state.loadingMore ? "正在加载更多…" : "继续加载"}
              </button>
            ) : null}
          </div>
        )}
      </aside>
    </div>
  );
}
