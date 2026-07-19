import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const api = fs.readFileSync(path.join(root, "src/api/inquiry.js"), "utf8");
const page = fs.readFileSync(path.join(root, "src/pages/Inquiry.jsx"), "utf8");
const result = fs.readFileSync(path.join(root, "src/components/InquiryResultStep.jsx"), "utf8");
const styles = fs.readFileSync(path.join(root, "src/styles/inquiry-actions.css"), "utf8");
const appStyles = fs.readFileSync(path.join(root, "src/styles/app.css"), "utf8");
const audioApi = fs.readFileSync(path.join(root, "src/api/audio.js"), "utf8");
const chat = fs.readFileSync(path.join(root, "src/components/InquiryChatStep.jsx"), "utf8");
const review = fs.readFileSync(path.join(root, "src/components/InquiryInformationReview.jsx"), "utf8");
const vitals = fs.readFileSync(path.join(root, "src/pages/Vitals.jsx"), "utf8");
const speech = await import(path.join(root, "src/utils/inquirySpeech.js"));

const recommendationSpeech = speech.buildRecommendationSpeech(
  {
    risk_level: "low",
    extracted_information: { dimension_evidence: { "恶心暑湿": "头重胸闷" } }
  },
  {
    medicines: [{ name: "藿香正气丸", dosage: "口服，一次1丸，一日2次。" }]
  }
);

const checks = [
  [api.includes("/treatment/confirm"), "missing treatment confirmation endpoint"],
  [api.includes("/information"), "missing reviewed-information revision endpoint"],
  [api.includes("option_id: optionId"), "frontend must submit the selected option id"],
  [api.includes("expected_item_index: expectedItemIndex"), "frontend must submit persisted cabinet progress"],
  [!api.match(/confirmInquiryTreatment[\s\S]*medicine_id/), "frontend must not submit medicine ids"],
  [!api.match(/confirmInquiryTreatment[\s\S]*\bslot\b/), "frontend must not submit cabinet slots"],
  [page.includes("onConfirmTreatment={handleTreatmentConfirm}"), "inquiry page does not wire treatment confirmation"],
  [page.includes("openingTreatmentRef.current"), "duplicate frontend confirmation guard is missing"],
  [page.includes("data.status !== \"opening\"") && page.includes("1800"), "multi-cabinet flow must advance one cabinet at a time"],
  [!page.match(/handleTreatmentConfirm[\s\S]{0,500}setResultConfirmed\(false\)/), "cabinet progress must not reopen the information review"],
  [page.includes("useCallback(async (optionId)"), "countdown callback is not stable across clock renders"],
  [!page.includes("handleViewCandidates"), "inquiry result still navigates directly to medicines"],
  [result.includes("setCountdown(3)"), "three-second cancellable countdown is missing"],
  [result.includes("confirmed_safety_notice") === false, "safety confirmation must stay in the API adapter"],
  [result.includes("treatment_options"), "result does not render backend treatment options"],
  [result.includes("取消开柜倒计时"), "countdown cancellation control is missing"],
  [result.includes("treatment-opening-progress") && result.includes("正在逐柜处理"), "cabinet progress is not visible"],
  [result.includes("resumePending") && result.includes("继续打开下一柜"), "interrupted cabinet sequence cannot be resumed safely"],
  [styles.includes("min-height: 58px"), "touch action height contract is missing"],
  [!result.includes("查看主候选药品"), "legacy medicine-page navigation remains visible"],
  [audioApi.includes("/api/audio/stream/stop"), "audio interruption endpoint is missing"],
  [chat.match(/async function startVoice\(\)\s*\{\s*interruptPlayback\(\)/), "voice input must interrupt TTS before microphone startup"],
  [result.includes("buildRecommendationSpeech"), "result does not announce the recommendation"],
  [recommendationSpeech.includes("藿香正气丸") && recommendationSpeech.includes("一次1丸"), "recommendation speech omits medicine or dosage"],
  [page.includes("主要不适") && page.includes("持续时间") && page.includes("体征信息"), "live inquiry summary wording is incomplete"],
  [page.includes("complaint: extracted.case_summary || evidence[0]"), "live complaint must show the complete case summary or primary evidence instead of an ellipsized list"],
  [page.includes("symptomDimensionLabel(value)"), "live complaint must use normalized symptom dimensions"],
  [page.includes("showReview") && page.indexOf("showReview ?") < page.indexOf("showResult ?"), "information review must appear before the recommendation result"],
  [chat.includes("onReview") && chat.includes("核对本次问询信息"), "chat header is missing the information review shortcut"],
  [review.includes("AUTO_CONFIRM_SECONDS = 10") && review.includes("confirmRef.current("), "information review must auto-confirm after ten seconds"],
  [review.includes("主要不适") && review.includes("已经用药") && review.includes("过敏与禁忌"), "information review omits key case facts"],
  [review.includes("data-touch-editable") && review.includes("main_complaint"), "review facts must be editable on the touchscreen"],
  [result.includes("medicine.dosage"), "treatment option omits medicine dosage"],
  [!result.includes("本次分析") && !result.includes("treatment-evidence-line"), "result still renders the redundant analysis strip"],
  [!result.includes("点击确认即表示已核对"), "result still exposes legalistic confirmation copy"],
  [result.includes("compact-result-action") && result.includes("aria-label=\"重新问询\"") && result.includes("aria-label=\"返回首页\""), "result footer actions are not compact icon controls"],
  [styles.includes("overflow-y: auto") && styles.includes(".option-medicine-list"), "multi-medicine options must scroll without clipping"],
  [appStyles.includes(".inquiry-chief-fact strong") && appStyles.includes("white-space: normal"), "primary complaint must wrap instead of ellipsizing"],
  [!result.includes("treatment-safety-check"), "result still requires a redundant safety checkbox"],
  [chat.includes("chat-message-line"), "assistant source icon is not aligned with its message"],
  [!result.includes("aiSourceLabel"), "result still exposes a technical AI source label"],
  [vitals.includes("const baseMeasurementSeconds = 18"), "vitals progress does not match the cold-start window"],
  [vitals.includes("传感器预热中"), "cold-start warm-up guidance is missing"]
];

const failures = checks.filter(([ok]) => !ok).map(([, message]) => message);
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("inquiry treatment contract passed");
