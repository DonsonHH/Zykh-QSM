const MAX_SPEECH_LENGTH = 260;

export function buildRecommendationSpeech(result, selectedOption) {
  if (!result) return "";
  if (["high", "emergency"].includes(result.risk_level)) {
    return result.reply || "当前存在需要优先处理的风险信号，请尽快联系医生或现场协助人员。";
  }
  const medicines = selectedOption?.medicines || [];
  if (!medicines.length) return result.reply || "当前没有通过安全核验的候选方案。";

  const evidence = Object.values(result.extracted_information?.dimension_evidence || {})
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .join("、");
  const medicineNames = medicines.map((medicine) => medicine.name).join("和");
  const dosage = medicines
    .map((medicine) => medicine.dosage ? `${medicine.name}说明用法为${medicine.dosage}` : "")
    .filter(Boolean)
    .join("；");
  const opening = evidence
    ? `根据你描述的${evidence}和本次安全核验，目前信息更接近轻症对症处理范围。`
    : "本次用药安全核验已经完成。";
  const instruction = dosage || "具体用法请核对屏幕和药品实物说明。";
  return `${opening}优先方案是${medicineNames}。${instruction}。请核对过敏禁忌并只选择一个方案，确认后系统才会打开对应药柜。`
    .slice(0, MAX_SPEECH_LENGTH);
}

export function buildActionSpeech(actionMessage) {
  const message = String(actionMessage || "").trim();
  return message ? `${message}请按屏幕提示取药，并再次核对药品名称。` : "";
}
