const MAX_SPEECH_LENGTH = 340;

export function buildInformationReviewSpeech(result) {
  const userName = String(result?.user_name || "").trim();
  const greeting = userName && userName !== "访客" ? `${userName}，` : "";
  return `${greeting}请核对问询信息。无误请确认，需要修改请点选。`;
}

export function buildRecommendationSpeech(result, selectedOption) {
  if (!result) return "";
  if (["high", "emergency"].includes(result.risk_level)) {
    return result.reply || "当前存在需要优先处理的风险信号，请尽快联系医生或现场协助人员。";
  }
  const disclaimer = "以上仅为健康信息和药仓内药品的辅助匹配，不构成诊断或处方；用药前请核对药盒说明、有效期和禁忌，并请听医嘱。";
  const firstSafetyNotice = String(result?.medication_safety_notices?.[0]?.message || "").trim();
  const safetyNoticeText = firstSafetyNotice
    ? `用药安全提醒：${firstSafetyNotice.slice(0, 100)}`
    : "";
  const medicines = selectedOption?.medicines || [];
  if (!medicines.length) {
    const body = `${safetyNoticeText}${result.reply || "当前没有通过安全核验的候选方案。"}`;
    return `${body.slice(0, Math.max(0, MAX_SPEECH_LENGTH - disclaimer.length))}${disclaimer}`;
  }

  const medicineNames = medicines.map((medicine) => medicine.name).join("、");
  const usage = medicines
    .map((medicine) => {
      const instruction = medicine.recommended_usage || medicine.dosage;
      return instruction ? `${medicine.name}：${instruction}` : "";
    })
    .filter(Boolean)
    .join("；");
  const label = selectedOption?.option_id === "A" ? "推荐方案" : "当前备选方案";
  const reason = String(selectedOption?.when || "").trim();
  const instruction = usage || "具体用法请核对屏幕和药品实物说明。";
  const optionCount = Number(result?.treatment_options?.length || 0);
  const assessment = result?.extracted_information?.final_assessment || {};
  const firstCondition = assessment?.possible_conditions?.[0]?.name;
  const conditionText = firstCondition
    ? `结合现有信息，较先考虑${firstCondition}等可能情况，但这不是诊断。`
    : "";
  const seekCareText = assessment?.seek_care_if?.[0]
    ? `如果${assessment.seek_care_if[0]}，请及时就医。`
    : "";
  const selectionGuide = optionCount > 1
    ? "屏幕上有推荐方案和备选方案，请点选其中一个，不要同时使用。"
    : "屏幕上有一个推荐方案，请核对后选择。";
  const body = `${safetyNoticeText}${conditionText}${selectionGuide}${label}包含${medicineNames}。${reason}${instruction}。${seekCareText}确认后系统会依次打开对应药柜。`;
  return `${body.slice(0, Math.max(0, MAX_SPEECH_LENGTH - disclaimer.length))}${disclaimer}`;
}

export function buildActionSpeech(actionMessage) {
  const message = String(actionMessage || "").trim();
  return message ? `${message}请按屏幕提示取药，并再次核对药品名称。` : "";
}
