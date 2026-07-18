import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const api = fs.readFileSync(path.join(root, "src/api/inquiry.js"), "utf8");
const page = fs.readFileSync(path.join(root, "src/pages/Inquiry.jsx"), "utf8");
const result = fs.readFileSync(path.join(root, "src/components/InquiryResultStep.jsx"), "utf8");
const styles = fs.readFileSync(path.join(root, "src/styles/inquiry-actions.css"), "utf8");
const audioApi = fs.readFileSync(path.join(root, "src/api/audio.js"), "utf8");
const chat = fs.readFileSync(path.join(root, "src/components/InquiryChatStep.jsx"), "utf8");
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
  [api.includes("option_id: optionId"), "frontend must submit the selected option id"],
  [!api.match(/confirmInquiryTreatment[\s\S]*medicine_id/), "frontend must not submit medicine ids"],
  [!api.match(/confirmInquiryTreatment[\s\S]*\bslot\b/), "frontend must not submit cabinet slots"],
  [page.includes("onConfirmTreatment={handleTreatmentConfirm}"), "inquiry page does not wire treatment confirmation"],
  [page.includes("openingTreatmentRef.current"), "duplicate frontend confirmation guard is missing"],
  [page.includes("useCallback(async (optionId)"), "countdown callback is not stable across clock renders"],
  [!page.includes("handleViewCandidates"), "inquiry result still navigates directly to medicines"],
  [result.includes("setCountdown(3)"), "three-second cancellable countdown is missing"],
  [result.includes("confirmed_safety_notice") === false, "safety confirmation must stay in the API adapter"],
  [result.includes("treatment_options"), "result does not render backend treatment options"],
  [result.includes("取消开柜倒计时"), "countdown cancellation control is missing"],
  [styles.includes("min-height: 58px"), "touch action height contract is missing"],
  [!result.includes("查看主候选药品"), "legacy medicine-page navigation remains visible"],
  [audioApi.includes("/api/audio/stream/stop"), "audio interruption endpoint is missing"],
  [chat.match(/async function startVoice\(\)\s*\{\s*interruptPlayback\(\)/), "voice input must interrupt TTS before microphone startup"],
  [result.includes("buildRecommendationSpeech"), "result does not announce the recommendation"],
  [recommendationSpeech.includes("藿香正气丸") && recommendationSpeech.includes("一次1丸"), "recommendation speech omits medicine or dosage"],
  [page.includes("本次情况") && page.includes("开始时间") && page.includes("核心体征"), "live inquiry summary wording is incomplete"]
];

const failures = checks.filter(([ok]) => !ok).map(([, message]) => message);
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("inquiry treatment contract passed");
