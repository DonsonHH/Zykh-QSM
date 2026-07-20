const MAX_FAILURE_LENGTH = 54;

export function resolveDispenseUsage(medicine, plan = null) {
  return String(
    plan?.dose
      || medicine?.recommended_usage
      || medicine?.dosage
      || medicine?.safety_note
      || "请按药品实物说明使用"
  ).trim();
}

export function buildDispenseGuidanceSpeech(medicine, plan = null, method = "fingerprint") {
  const name = String(medicine?.name || "本次药品").trim();
  const usage = resolveDispenseUsage(medicine, plan);
  const identityGuide = method === "face"
    ? "请面向摄像头完成身份确认；也可以选择指纹确认并把手指平放在传感器上。"
    : "请将手指平放在指纹传感器上；也可以选择面部确认。";
  return `${name}，本次用法：${usage}。${identityGuide}`;
}

export function buildDispenseSuccessSpeech(medicine) {
  const name = String(medicine?.name || "药品").trim();
  return `${name}已弹出，请取出药品并关闭柜门。`;
}

export function buildDispenseFailureSpeech(message) {
  const detail = String(message || "身份确认未完成").replace(/[。！!]+$/g, "").slice(0, MAX_FAILURE_LENGTH);
  return `${detail}，请按屏幕提示重新确认。`;
}
