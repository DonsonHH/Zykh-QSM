import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const api = fs.readFileSync(path.join(root, "src/api/inquiry.js"), "utf8");
const page = fs.readFileSync(path.join(root, "src/pages/Inquiry.jsx"), "utf8");
const result = fs.readFileSync(path.join(root, "src/components/InquiryResultStep.jsx"), "utf8");
const styles = fs.readFileSync(path.join(root, "src/styles/inquiry-actions.css"), "utf8");

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
  [!result.includes("查看主候选药品"), "legacy medicine-page navigation remains visible"]
];

const failures = checks.filter(([ok]) => !ok).map(([, message]) => message);
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("inquiry treatment contract passed");
