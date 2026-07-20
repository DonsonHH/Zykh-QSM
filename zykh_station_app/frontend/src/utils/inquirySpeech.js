const MAX_SPEECH_LENGTH = 260;

export function buildInformationReviewSpeech(result) {
  const userName = String(result?.user_name || "").trim();
  const greeting = userName && userName !== "访客" ? `${userName}，` : "";
  return `${greeting}请核对屏幕上的主要不适、持续时间、本次用药和过敏禁忌。信息无误请点击确认，需要修改可直接点选对应内容。`;
}

export function buildRecommendationSpeech(result, selectedOption) {
  if (!result) return "";
  if (["high", "emergency"].includes(result.risk_level)) {
    return result.reply || "当前存在需要优先处理的风险信号，请尽快联系医生或现场协助人员。";
  }
  const medicines = selectedOption?.medicines || [];
  if (!medicines.length) return result.reply || "当前没有通过安全核验的候选方案。";

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
  const selectionGuide = optionCount > 1
    ? "屏幕上有推荐方案和备选方案，请点选其中一个，不要同时使用。"
    : "屏幕上有一个推荐方案，请核对后选择。";
  return `${selectionGuide}${label}包含${medicineNames}。${reason}${instruction}。确认后系统会依次打开对应药柜。`
    .slice(0, MAX_SPEECH_LENGTH);
}

export function buildActionSpeech(actionMessage) {
  const message = String(actionMessage || "").trim();
  return message ? `${message}请按屏幕提示取药，并再次核对药品名称。` : "";
}
