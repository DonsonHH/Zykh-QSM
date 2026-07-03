import React, { useState } from "react";
import { evaluateInquiry } from "../api/inquiry.js";
import { InquiryAssistantCard } from "../components/InquiryAssistantCard.jsx";
import { InquiryForm } from "../components/InquiryForm.jsx";
import { InquiryResultPanel } from "../components/InquiryResultPanel.jsx";

const initialForm = {
  symptoms_text: "",
  duration: "",
  used_medicines: "",
  allergy_or_contraindication: "",
  scene_type: "村镇",
  include_vitals: false
};

export function Inquiry({ notify, onViewCandidates }) {
  const [form, setForm] = useState(initialForm);
  const [result, setResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  function handleSubmit(event) {
    event.preventDefault();
    if (!form.symptoms_text.trim()) {
      notify("请先填写症状信息");
      return;
    }

    setSubmitting(true);
    evaluateInquiry({
      ...form,
      symptoms_text: form.symptoms_text.trim(),
      duration: form.duration.trim(),
      used_medicines: form.used_medicines.trim(),
      allergy_or_contraindication: form.allergy_or_contraindication.trim()
    })
      .then((data) => {
        setResult(data);
        notify("问询结果已生成");
      })
      .catch((error) => notify(error.message || "问询失败，请重试"))
      .finally(() => setSubmitting(false));
  }

  function handleViewCandidates() {
    if (!result?.can_proceed_to_dispense) {
      return;
    }
    const firstMedicine = result.candidate_medicines[0];
    onViewCandidates({
      category: firstMedicine?.category || result.suggested_categories[0] || "全部",
      medicineId: firstMedicine?.id || null
    });
  }

  return (
    <main className="inquiry-page" id="main-content">
      <InquiryForm
        form={form}
        submitting={submitting}
        onChange={setForm}
        onSubmit={handleSubmit}
        onPlaceholder={notify}
      />
      <InquiryAssistantCard result={result} />
      <InquiryResultPanel result={result} onViewCandidates={handleViewCandidates} />
    </main>
  );
}
