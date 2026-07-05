import React, { useEffect, useMemo, useState } from "react";
import { HeartPulse, History, UserRound } from "lucide-react";
import { openCabinet } from "../api/dispense.js";
import { evaluateInquiry, loadInquiryRecords } from "../api/inquiry.js";
import { createServiceUser, loadServiceUsers } from "../api/records.js";
import { InquiryAnalyzingStep } from "../components/InquiryAnalyzingStep.jsx";
import { InquiryChatStep } from "../components/InquiryChatStep.jsx";
import { InquiryResultStep } from "../components/InquiryResultStep.jsx";

const initialForm = {
  symptoms_text: "",
  duration: "",
  used_medicines: "",
  allergy_or_contraindication: "",
  scene_type: "家庭",
  include_vitals: false
};

const draftKey = "zykh-inquiry-draft";

function readDraft() {
  try {
    const raw = window.sessionStorage.getItem(draftKey);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function normalizeUser(user) {
  if (!user) {
    return null;
  }
  return {
    id: user.id,
    name: user.name || "待确认",
    age: Number(user.age || 0),
    role: user.status || "家庭成员",
    conditions: user.profile || "待补充",
    allergies: user.allergies || "待补充",
    note: user.note || "请通过语音补充基础病、过敏禁忌和近期用药。"
  };
}

function inferHistoryPerson(record) {
  const text = `${record.symptoms_summary || ""} ${record.description || ""} ${record.title || ""}`;
  const matched = text.match(/张三|李四|王五/);
  return matched?.[0] || "家庭成员";
}

function historyTitle(record) {
  const text = record.symptoms_summary || record.description || record.title || "";
  if (/中暑|头晕|头昏/.test(text)) {
    return "中暑头晕问询";
  }
  if (/发热|头痛/.test(text)) {
    return "发热头痛问询";
  }
  if (/咳嗽|流涕|感冒/.test(text)) {
    return "咳嗽流涕问询";
  }
  if (/腹泻|胃痛|肠胃/.test(text)) {
    return "肠胃不适问询";
  }
  if (/过敏|瘙痒/.test(text)) {
    return "皮肤过敏问询";
  }
  const compact = text.replace(/\s+/g, "").slice(0, 10);
  return compact ? `${compact}问询` : "健康问询";
}

function formatHistoryTime(value) {
  if (!value || value === "--:--") {
    return "--:--";
  }
  const date = new Date(value.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function summarizeRecord(record) {
  return {
    id: record.inquiry_id || record.id,
    person: inferHistoryPerson(record),
    title: historyTitle(record),
    time: record.created_at || record.time || "--:--",
    summary: record.symptoms_summary || record.description || "可继续补充当前症状变化。",
    seed: [
      { role: "user", content: record.symptoms_summary || record.description || "" },
      { role: "assistant", content: "已打开历史问询。请继续说出现在的症状变化。" }
    ].filter((message) => message.content)
  };
}

export function Inquiry({ notify, onViewCandidates, onNavigate }) {
  const initialDraft = readDraft();
  const [step, setStep] = useState(initialDraft?.step || "start");
  const [form, setForm] = useState(initialDraft?.form || initialForm);
  const [result, setResult] = useState(null);
  const [blockedReason, setBlockedReason] = useState("");
  const [serviceUsers, setServiceUsers] = useState([]);
  const [historyItems, setHistoryItems] = useState([]);
  const [selectedUserId, setSelectedUserId] = useState(initialDraft?.selectedUserId || "");
  const [selectedHistoryId, setSelectedHistoryId] = useState("");
  const [chatSessionId, setChatSessionId] = useState(0);
  const [pendingCabinetAction, setPendingCabinetAction] = useState(null);
  const [cabinetCountdown, setCabinetCountdown] = useState(0);

  const selectedUser = useMemo(
    () => normalizeUser(serviceUsers.find((user) => user.id === selectedUserId)),
    [selectedUserId, serviceUsers]
  );
  const selectedHistory = useMemo(
    () => historyItems.find((item) => item.id === selectedHistoryId) || null,
    [historyItems, selectedHistoryId]
  );

  useEffect(() => {
    refreshUsers();
    loadInquiryRecords()
      .then((data) => setHistoryItems((data.records || []).map(summarizeRecord).slice(0, 6)))
      .catch(() => setHistoryItems([]));
  }, []);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(draftKey, JSON.stringify({ step, form, selectedUserId }));
    } catch {
      // Draft storage is optional.
    }
  }, [step, form, selectedUserId]);

  useEffect(() => {
    if (!pendingCabinetAction || cabinetCountdown <= 0) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setCabinetCountdown((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [cabinetCountdown, pendingCabinetAction]);

  function refreshUsers() {
    return loadServiceUsers()
      .then((data) => setServiceUsers(data.users || []))
      .catch(() => setServiceUsers([]));
  }

  function handleProfileResolved(user) {
    setSelectedUserId(user.id);
    refreshUsers();
  }

  function handleCreateProfile(payload) {
    return createServiceUser(payload).then((data) => {
      const users = data.users || [];
      setServiceUsers(users);
      const created = users.find((user) => user.name === payload.name) || users[users.length - 1];
      if (created) {
        setSelectedUserId(created.id);
      }
      return normalizeUser(created);
    });
  }

  function analyzeChatTranscript(transcript, meta = {}) {
    const symptoms = transcript.trim();
    if (!symptoms) {
      notify("请先完成一轮语音问询");
      return;
    }
    const profile = meta.profile || selectedUser;
    const nextForm = {
      symptoms_text: symptoms,
      duration: "由 AI 对话问询整理",
      used_medicines: "见对话记录",
      allergy_or_contraindication: profile?.allergies && profile.allergies !== "待补充" ? profile.allergies : "",
      scene_type: "家庭",
      include_vitals: Boolean(meta.includeVitals ?? true)
    };
    setForm(nextForm);
    setBlockedReason("");
    setStep("analyzing");
    window.setTimeout(() => {
      evaluateInquiry(nextForm)
        .then((data) => {
          setResult(data);
          setStep("result");
        })
        .catch((error) => {
          notify(error.message || "问询失败，请重试");
          setStep("start");
        });
    }, 520);
  }

  function handleViewCandidates() {
    const riskCanProceed = result?.risk_level === "low" || result?.risk_level === "medium";
    if (!(result?.can_proceed_to_dispense || riskCanProceed) || blockedReason) {
      return;
    }
    const firstMedicine = result.candidate_medicines[0];
    onViewCandidates({
      category: firstMedicine?.category || result.suggested_categories[0] || "全部",
      medicineId: firstMedicine?.id || null
    });
  }

  function handleDemoRecommendation(payload) {
    const demoResult = {
      inquiry_id: `demo-${Date.now()}`,
      risk_level: "medium",
      risk_label: "中风险提示",
      symptoms_summary: `${payload?.profile?.name || "张三"}：中暑头晕，已完成体征测量。`,
      suggested_categories: ["肠胃"],
      candidate_medicines: [
        {
          id: "slot-08-huoxiang-zhengqi",
          name: "藿香正气丸",
          category: "肠胃",
          slot: "8",
          stock: 1,
          unit: "盒",
          safety_note: "按药品说明核验禁忌后取用。"
        }
      ],
      contraindication_warnings: ["已记录头孢过敏，当前推荐药品不属于头孢类。"],
      safety_notice: "本次为家庭康护用药安全提示，取药前请再次核对药名和说明。",
      next_steps: ["已定位家庭药柜 8 号柜。", "如头晕加重、持续高热或意识异常，请联系医生或家人。"],
      can_proceed_to_dispense: true,
      created_at: new Date().toISOString(),
      ai_source: "cloud",
      ai_message: "演示问询链路已整理。"
    };
    setResult(demoResult);
    setBlockedReason("");
    setCabinetCountdown(3);
    setPendingCabinetAction({
      slot: 8,
      medicineId: "slot-08-huoxiang-zhengqi",
      medicineName: "藿香正气丸",
      category: "肠胃",
      userName: payload?.profile?.name || "张三",
      opening: false,
      error: ""
    });
    notify("已生成候选药品，请确认后打开 8 号柜。");
  }

  function handleConfirmCabinetOpen() {
    if (!pendingCabinetAction || cabinetCountdown > 0 || pendingCabinetAction.opening) {
      return;
    }
    setPendingCabinetAction((current) => (current ? { ...current, opening: true, error: "" } : current));
    openCabinet({
      slot: pendingCabinetAction.slot,
      quantity: 1,
      reason: `${pendingCabinetAction.userName}中暑头晕演示推荐${pendingCabinetAction.medicineName}`,
      confirmed_open: true
    })
      .then((data) => {
        if (!data.ok) {
          setPendingCabinetAction((current) =>
            current ? { ...current, opening: false, error: data.message || "开柜失败，请人工处理。" } : current
          );
          return;
        }
        notify(`已打开 ${pendingCabinetAction.slot} 号柜，请核对${pendingCabinetAction.medicineName}。`);
        setPendingCabinetAction(null);
        onViewCandidates({
          category: pendingCabinetAction.category,
          medicineId: pendingCabinetAction.medicineId
        });
      })
      .catch((error) => {
        setPendingCabinetAction((current) =>
          current ? { ...current, opening: false, error: error.message || "开柜失败，请人工处理。" } : current
        );
      });
  }

  function handleCancelCabinetOpen() {
    setPendingCabinetAction(null);
    notify("已取消开柜，请在药品页继续核对。");
  }

  function resetFlow() {
    setStep("start");
    setForm(initialForm);
    setResult(null);
    setBlockedReason("");
    setPendingCabinetAction(null);
    setCabinetCountdown(0);
    setSelectedUserId("");
    setSelectedHistoryId("");
    setChatSessionId((value) => value + 1);
    try {
      window.sessionStorage.removeItem(draftKey);
      window.sessionStorage.removeItem("zykh-inquiry-chat-draft");
      window.sessionStorage.removeItem("zykh-inquiry-awaiting-vitals");
    } catch {
      // sessionStorage is optional.
    }
  }

  return (
    <main className="inquiry-page conversation-layout" id="main-content">
      <aside className="inquiry-context-panel" aria-label="使用人和问询记录">
        <section className="inquiry-user-card dynamic">
          <div className="context-heading">
            <UserRound size={26} aria-hidden="true" />
            <div>
              <p>当前使用人</p>
              <h2>{selectedUser?.name || "等待语音确认"}</h2>
            </div>
          </div>

          <div className="user-identity-status">
            <strong>{selectedUser ? "已匹配本地身份" : "请先说出姓名或家庭身份"}</strong>
            <span>{selectedUser ? "AI 将结合基础信息继续问询" : "未记录人员会自动建立本地身份"}</span>
          </div>

          <div className="user-profile-grid">
            <article>
              <span>年龄</span>
              <strong>{selectedUser?.age ? `${selectedUser.age}岁` : "待补充"}</strong>
            </article>
            <article>
              <span>身份</span>
              <strong>{selectedUser?.role || "待确认"}</strong>
            </article>
          </div>
          <div className="user-profile-note">
            <HeartPulse size={20} aria-hidden="true" />
            <p>{selectedUser?.conditions || "AI 会继续询问基础病和过敏禁忌。"}</p>
          </div>
          <p className="user-profile-muted">过敏/禁忌：{selectedUser?.allergies || "待补充"}</p>
          <p className="user-profile-muted">{selectedUser?.note || "请通过语音补充近期症状、已用药和病例信息。"}</p>
        </section>

        <section className="inquiry-history-card">
          <div className="context-heading compact">
            <History size={24} aria-hidden="true" />
            <div>
              <p>历史记录</p>
              <h2>最近问询</h2>
            </div>
          </div>
          <div className="history-list">
            {historyItems.length ? (
              historyItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={item.id === selectedHistoryId ? "active" : ""}
                  onClick={() => {
                    setSelectedHistoryId(item.id);
                    setSelectedUserId("");
                    setStep("start");
                    setResult(null);
                    setChatSessionId((value) => value + 1);
                    try {
                      window.sessionStorage.removeItem("zykh-inquiry-chat-draft");
                      window.sessionStorage.removeItem("zykh-inquiry-awaiting-vitals");
                    } catch {
                      // sessionStorage is optional.
                    }
                  }}
                >
                  <span>
                    {item.person} · {formatHistoryTime(item.time)}
                  </span>
                  <strong>{item.title}</strong>
                </button>
              ))
            ) : (
              <p className="empty-history">暂无历史问询。开始语音问询后会在这里保留记录。</p>
            )}
          </div>
        </section>
      </aside>

      <section className="inquiry-flow-card chat-only" aria-label="AI 应急问询流程">
        {step === "start" ? (
          <InquiryChatStep
            key={`${selectedHistory?.id || "new"}-${chatSessionId}`}
            notify={notify}
            onStructuredAnalyze={analyzeChatTranscript}
            onOpenVitals={() => onNavigate("vitals", { returnTo: "inquiry" })}
            onDemoRecommendation={handleDemoRecommendation}
            profile={selectedUser}
            knownUsers={serviceUsers.map(normalizeUser).filter(Boolean)}
            onProfileResolved={handleProfileResolved}
            onCreateProfile={handleCreateProfile}
            history={selectedHistory}
          />
        ) : step === "analyzing" ? (
          <InquiryAnalyzingStep />
        ) : result ? (
          <InquiryResultStep
            result={result}
            blockedReason={blockedReason}
            onViewCandidates={handleViewCandidates}
            onRestart={resetFlow}
            onHome={() => onNavigate("home")}
          />
        ) : null}
      </section>
      {pendingCabinetAction ? (
        <div className="modal-layer inquiry-cabinet-confirm" role="dialog" aria-modal="true" aria-labelledby="cabinet-confirm-title">
          <section className="dispense-modal compact-confirm">
            <div className="modal-heading">
              <span aria-hidden="true">8</span>
              <div>
                <p>推荐药品已定位</p>
                <h2 id="cabinet-confirm-title">确认打开 8 号柜</h2>
              </div>
            </div>
            <div className="modal-medicine-meta">
              <article>
                <span>使用人</span>
                <strong>{pendingCabinetAction.userName}</strong>
              </article>
              <article>
                <span>候选药品</span>
                <strong>{pendingCabinetAction.medicineName}</strong>
              </article>
              <article>
                <span>柜门</span>
                <strong>{pendingCabinetAction.slot} 号</strong>
              </article>
            </div>
            <p className="modal-safety">请先核对使用人、药名和柜门编号。确认后系统将打开对应柜门，不会自动判断服用剂量。</p>
            {cabinetCountdown > 0 ? (
              <p className="modal-message">请等待 {cabinetCountdown} 秒后确认开柜。</p>
            ) : pendingCabinetAction.error ? (
              <p className="modal-message error">{pendingCabinetAction.error}</p>
            ) : (
              <p className="modal-message success">已完成等待，请现场确认后开柜。</p>
            )}
            <div className="modal-actions">
              <button className="secondary-action" type="button" onClick={handleCancelCabinetOpen} disabled={pendingCabinetAction.opening}>
                取消
              </button>
              <button
                className="primary-action"
                type="button"
                onClick={handleConfirmCabinetOpen}
                disabled={cabinetCountdown > 0 || pendingCabinetAction.opening}
              >
                {pendingCabinetAction.opening ? "正在开柜..." : cabinetCountdown > 0 ? `${cabinetCountdown} 秒后可确认` : "确认开柜"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
