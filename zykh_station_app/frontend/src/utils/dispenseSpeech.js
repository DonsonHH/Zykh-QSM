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
  const identityGuide = method === "face"
    ? "请面向摄像头完成身份确认；也可以选择指纹确认并把手指平放在传感器上。"
    : "请将手指平放在指纹传感器上；也可以选择面部确认。";
  return `${name}，${identityGuide}`;
}

export function buildDispenseSuccessSpeech(medicine) {
  const name = String(medicine?.name || "药品").trim();
  const cabinet = describeMedicineCabinet(medicine).split(" · ")[0];
  return `${name}所在的${cabinet}指示灯已亮，请自行打开亮灯的分类柜取药，并确认柜内是否还有药。确认页面结束后，指示灯会自动关闭。`;
}

export function buildDispenseFailureSpeech(message) {
  const detail = String(message || "身份确认未完成").replace(/[。！!]+$/g, "").slice(0, MAX_FAILURE_LENGTH);
  return `${detail}，请按屏幕提示重新确认。`;
}
import { describeMedicineCabinet } from "./cabinetLightPresentation.js";
