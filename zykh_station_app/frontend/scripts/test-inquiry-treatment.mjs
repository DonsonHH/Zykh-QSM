import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const TEST_SCOPE = "问诊算法与结果页 UI（不执行摄像头身份识别）";
const root = process.cwd();
const api = fs.readFileSync(path.join(root, "src/api/inquiry.js"), "utf8");
const medicinesApi = fs.readFileSync(path.join(root, "src/api/medicines.js"), "utf8");
const page = fs.readFileSync(path.join(root, "src/pages/Inquiry.jsx"), "utf8");
const result = fs.readFileSync(path.join(root, "src/components/InquiryResultStep.jsx"), "utf8");
const styles = fs.readFileSync(path.join(root, "src/styles/inquiry-actions.css"), "utf8");
const appStyles = fs.readFileSync(path.join(root, "src/styles/app.css"), "utf8");
const adaptiveStyles = fs.readFileSync(path.join(root, "src/styles/adaptive-layout.css"), "utf8");
const audioApi = fs.readFileSync(path.join(root, "src/api/audio.js"), "utf8");
const chat = fs.readFileSync(path.join(root, "src/components/InquiryChatStep.jsx"), "utf8");
const review = fs.readFileSync(path.join(root, "src/components/InquiryInformationReview.jsx"), "utf8");
const vitals = fs.readFileSync(path.join(root, "src/pages/Vitals.jsx"), "utf8");
const speech = await import(pathToFileURL(path.join(root, "src/utils/inquirySpeech.js")).href);

const recommendationSpeech = speech.buildRecommendationSpeech(
  {
    risk_level: "low",
    medication_safety_notices: [
      { code: "used_medicine_duplicate", message: "因本次已经使用同成分药品，复方感冒灵颗粒未纳入候选。" },
      { code: "allergy_conflict", message: "第二条提示不应进入语音播报。" }
    ],
    treatment_options: [{ option_id: "A" }, { option_id: "B" }],
    extracted_information: {
      dimension_evidence: { "恶心暑湿": "头重胸闷" },
      final_assessment: {
        possible_conditions: [{ name: "暑热相关不适", likelihood: "more_likely" }],
        seek_care_if: ["持续高热或意识异常"]
      }
    }
  },
  {
    option_id: "A",
    when: "更贴近本次暑湿不适。",
    medicines: [{
      name: "藿香正气丸",
      dosage: "口服，一次1丸，一日2次。",
      recommended_usage: "本次口服，一次1丸，一日2次"
    }]
  }
);
const safetyOnlySpeech = speech.buildRecommendationSpeech(
  {
    risk_level: "low",
    reply: "目前没有其他通过核验的候选药品。",
    medication_safety_notices: [
      { code: "allergy_conflict", message: "布洛芬缓释胶囊与已记录过敏信息冲突。" },
      { code: "history_contraindication", message: "第二条提示不应进入语音播报。" }
    ],
    treatment_options: []
  },
  null
);
const reviewSpeech = speech.buildInformationReviewSpeech({ user_name: "张三" });

const checks = [
  [api.includes("/treatment/confirm"), "missing treatment confirmation endpoint"],
  [api.includes("/api/inquiry/sessions") && api.includes("/turn") && api.includes("/vitals"), "frontend inquiry adapter no longer uses the original session, turn, and vitals routes"],
  [api.includes("/information"), "missing reviewed-information revision endpoint"],
  [api.includes("option_id: optionId"), "frontend must submit the selected option id"],
  [api.includes("expected_item_index: expectedItemIndex"), "frontend must submit persisted cabinet progress"],
  [!api.match(/confirmInquiryTreatment[\s\S]*medicine_id/), "frontend must not submit medicine ids"],
  [!api.match(/confirmInquiryTreatment[\s\S]*\bslot\b/), "frontend must not submit cabinet slots"],
  [page.includes("onConfirmTreatment={handleTreatmentConfirm}"), "inquiry page does not wire treatment confirmation"],
  [page.includes("sendInquiryTurn") && page.includes("attachInquiryVitals") && page.includes("reviseInquiryInformation") && page.includes("confirmInquiryTreatment"), "Inquiry.jsx no longer preserves the original inquiry workflow"],
  [!page.includes("api.deepseek.com") && !page.includes("/chat/completions") && !page.includes("/responses"), "Inquiry.jsx must not bypass the backend safety chain by calling DeepSeek directly"],
  [page.includes("openingTreatmentRef.current"), "duplicate frontend confirmation guard is missing"],
  [page.includes("data.status !== \"opening\"") && page.includes("1800"), "multi-cabinet flow must advance one cabinet at a time"],
  [page.includes("inventory_confirmation_required") && page.includes("record_id"), "real inquiry dispense does not pause for explicit inventory confirmation"],
  [page.includes("confirmMedicineInventory") && medicinesApi.includes("/inventory-confirmation"), "inquiry inventory confirmation does not use the medicine inventory API"],
  [page.includes("buildInquiryInventoryRequestId") && page.includes("dispense_record_id") && page.includes("observation"), "inquiry inventory confirmation request is incomplete or unstable"],
  [page.includes("setInventoryConfirmationError") && page.includes("await runTreatmentSequence"), "failed inventory confirmation cannot stay put and safely resume the next cabinet"],
  [result.includes("<MedicineRemainingPrompt") && result.includes("onInventoryHasStock") && result.includes("onInventoryDepleted"), "result step does not require an explicit has-stock or depleted choice"],
  [!page.match(/handleTreatmentConfirm[\s\S]{0,500}setResultConfirmed\(false\)/), "cabinet progress must not reopen the information review"],
  [page.includes("useCallback(async (optionId)"), "countdown callback is not stable across clock renders"],
  [!page.includes("handleViewCandidates"), "inquiry result still navigates directly to medicines"],
  [result.includes("setCountdown(3)"), "three-second cancellable countdown is missing"],
  [result.includes("confirmed_safety_notice") === false, "safety confirmation must stay in the API adapter"],
  [result.includes("treatment_options"), "result does not render backend treatment options"],
  [!result.includes('low: "低风险"'), "normal inquiry results must not expose an internal low-risk label"],
  [result.includes('canProceed ? "可取药" : "核验完成"'), "normal inquiry results must state whether a medicine plan is available"],
  [result.includes("取消亮灯倒计时"), "cabinet-light countdown cancellation control is missing"],
  [result.includes("treatment-opening-progress") && result.includes("正在逐项点亮分类柜指示灯"), "cabinet-light progress is not visible"],
  [result.includes("resumePending") && result.includes("继续下一项亮灯"), "interrupted cabinet-light sequence cannot be resumed safely"],
  [styles.includes("min-height: 58px"), "touch action height contract is missing"],
  [styles.match(/\.treatment-result-body\s*\{[\s\S]{0,320}overflow-y:\s*auto/), "stacked result content must support vertical scrolling on short screens"],
  [!result.includes("查看主候选药品"), "legacy medicine-page navigation remains visible"],
  [audioApi.includes("/api/audio/stream/stop"), "audio interruption endpoint is missing"],
  [chat.match(/async function startVoice\(\)\s*\{\s*interruptPlayback\(\)/), "voice input must interrupt TTS before microphone startup"],
  [result.includes("buildRecommendationSpeech"), "result does not announce the recommendation"],
  [recommendationSpeech.includes("藿香正气丸") && recommendationSpeech.includes("一次1丸"), "recommendation speech omits medicine or dosage"],
  [recommendationSpeech.includes("更贴近本次暑湿不适"), "recommendation speech omits the selected option reason"],
  [recommendationSpeech.includes("暑热相关不适") && recommendationSpeech.includes("持续高热或意识异常"), "recommendation speech omits possible cause or care trigger"],
  [recommendationSpeech.includes("复方感冒灵颗粒未纳入候选") && !recommendationSpeech.includes("第二条提示不应进入语音播报"), "recommendation speech must announce at most the first deterministic safety notice"],
  [safetyOnlySpeech.includes("布洛芬缓释胶囊") && !safetyOnlySpeech.includes("第二条提示不应进入语音播报"), "safety-only speech must announce at most the first deterministic safety notice"],
  [safetyOnlySpeech.includes("不构成诊断或处方") && safetyOnlySpeech.endsWith("并请听医嘱。"), "safety-only speech must retain the complete medical disclaimer"],
  [reviewSpeech.includes("张三") && reviewSpeech.includes("请核对"), "information review speech is incomplete"],
  [reviewSpeech.length <= 30, "information review speech must fit comfortably within the review window"],
  [review.includes("buildInformationReviewSpeech") && review.includes("speakText("), "information review does not trigger TTS"],
  [review.includes("[session?.session_id]"), "information review speech must run once per review state"],
  [!review.includes("networkStatus"), "information review must not receive the hidden display mode"],
  [!page.match(/InquiryInformationReview[\s\S]{0,300}networkStatus=\{networkStatus\}/), "information review still receives the hidden display mode"],
  [result.includes("[result?.session_id, selectedOption?.option_id]"), "switching treatment options does not trigger exactly one selected-plan speech"],
  [!result.includes("networkStatus"), "recommendation speech must not receive the hidden display mode"],
  [recommendationSpeech.includes("请点选其中一个") && recommendationSpeech.includes("不要同时使用"), "recommendation speech does not explain how to choose"],
  [recommendationSpeech.includes("不构成诊断或处方") && recommendationSpeech.includes("请听医嘱"), "recommendation speech omits the medical disclaimer"],
  [recommendationSpeech.endsWith("并请听医嘱。"), "medical disclaimer can be truncated from recommendation speech"],
  [!result.includes("reasoning_summary"), "result header still repeats the model summary"],
  [result.includes("ClinicalAssessmentCard") && result.includes("病因分析") && result.includes("非诊断"), "structured cause assessment is not visible"],
  [result.indexOf("treatment-option-grid") < result.indexOf("<ClinicalAssessmentCard"), "treatment options must appear before the cause analysis"],
  [result.includes("compactActionSummary") && !result.includes("assessment.summary"), "next-step summary must stay concise and avoid repeating the condition analysis"],
  [!result.includes("medicine.match_reason") && !result.includes("适合点：") && result.includes("用法："), "treatment option cards still render the removed suitability copy"],
  [!result.includes("medicine.safety_note") && !result.includes("medicine-safety-note") && !result.includes("慎用与指导提醒"), "treatment option cards still render the removed medicine-level caution block"],
  [result.includes('className="option-medicine-cabinet-number"') && result.includes('role="img"') && result.includes("aria-label={describeMedicineCabinet(medicine)}"), "medicine option cards are missing the number-only accessible cabinet badge"],
  [!result.includes("<em>{describeMedicineCabinet(medicine)}</em>"), "medicine option cards still expose the full blue cabinet label"],
  [!result.includes("title={describeMedicineCabinet(medicine)}"), "the removed full cabinet label is still exposed as a visual tooltip"],
  [styles.match(/\.option-heading small\s*\{[\s\S]{0,260}overflow:\s*visible[\s\S]{0,180}white-space:\s*normal/) && !styles.match(/\.option-heading small\s*\{[\s\S]{0,260}-webkit-line-clamp/), "treatment option rationale is still visually truncated"],
  [result.includes("medication_safety_notices") && result.includes("medication-safety-notices"), "deterministic medication safety notices are not independently visible on the active result page"],
  [result.includes("不构成诊断或处方") && result.includes("请听医嘱"), "result page omits the user-facing medical disclaimer"],
  [page.includes("主要不适") && page.includes("持续时间") && page.includes("体征信息"), "live inquiry summary wording is incomplete"],
  [page.includes("chiefComplaint({"), "live complaint must use the concise chief complaint formatter"],
  [page.includes("symptomDimensionLabel(value)"), "live complaint must use normalized symptom dimensions"],
  [page.includes("showReview") && page.indexOf("showReview ?") < page.indexOf("showResult ?"), "information review must appear before the recommendation result"],
  [chat.includes("onReview") && chat.includes("核对本次问询信息"), "chat header is missing the information review shortcut"],
  [review.includes("AUTO_CONFIRM_SECONDS = 15") && review.includes("confirmRef.current("), "information review must auto-confirm after fifteen seconds"],
  [appStyles.match(/\.review-auto-progress span[\s\S]{0,300}reviewAutoProgress 15s/), "information review progress must match the fifteen-second timer"],
  [review.includes("主要不适") && review.includes("已经用药") && review.includes("过敏与禁忌"), "information review omits key case facts"],
  [review.includes("fullComplaint(extracted)"), "information review must preserve every present symptom instead of only the first concept"],
  [review.includes("data-touch-editable") && review.includes("main_complaint"), "review facts must be editable on the touchscreen"],
  [result.includes("medicine.recommended_usage || medicine.dosage"), "treatment option omits contextual usage or label fallback"],
  [!result.includes("本次分析") && !result.includes("treatment-evidence-line"), "result still renders the redundant analysis strip"],
  [!result.includes("点击确认即表示已核对"), "result still exposes legalistic confirmation copy"],
  [result.includes("compact-result-action") && result.includes("aria-label=\"重新问询\"") && result.includes("aria-label=\"返回首页\""), "result footer actions are not compact icon controls"],
  [styles.match(/\.treatment-result-body\s*\{[\s\S]{0,320}overflow-y:\s*auto/), "the result body must be the single vertical scroll container"],
  [styles.match(/\.option-medicine-list\s*\{[\s\S]{0,240}overflow:\s*visible/), "medicine rows must expand into the result-body scroll instead of using a nested scrollbar"],
  [styles.match(/\.option-heading strong\s*\{[\s\S]{0,100}font-size:\s*19px/) && styles.match(/\.option-heading small\s*\{[\s\S]{0,220}font-size:\s*15px/), "treatment option text is too small"],
  [styles.match(/\.option-medicine-row strong\s*\{[\s\S]{0,100}font-size:\s*17px/) && styles.match(/\.option-medicine-row small\s*\{[\s\S]{0,160}font-size:\s*14px/), "medicine name or usage text is too small"],
  [styles.match(/\.clinical-assessment-card h3\s*\{[\s\S]{0,220}font-size:\s*19px/) && styles.match(/\.condition-chip strong\s*\{[\s\S]{0,220}font-size:\s*16px/), "cause analysis heading or condition text is too small"],
  [appStyles.includes(".inquiry-chief-fact strong") && appStyles.includes("white-space: normal"), "primary complaint must wrap instead of ellipsizing"],
  [(page.match(/className="inquiry-fact-card/g) || []).length === 4, "live inquiry facts are not four equal card peers"],
  [!page.includes("inquiry-fact-pair"), "duration and medicine remain nested in a differently-sized wrapper"],
  [appStyles.match(/\.inquiry-fact-list\s*\{[\s\S]{0,220}grid-template-columns:\s*repeat\(2,[^;]+;[\s\S]{0,120}grid-template-rows:\s*repeat\(2,/), "live inquiry facts are not arranged as an equal 2 by 2 grid"],
  [adaptiveStyles.match(/\.inquiry-fact-list\s*\{[\s\S]{0,180}grid-template-rows:\s*repeat\(2,/), "compact inquiry layout restores unequal fact rows"],
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

console.log(`[${TEST_SCOPE}] contract passed; production identity is covered separately.`);
