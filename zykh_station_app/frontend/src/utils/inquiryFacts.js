export function chiefComplaint(extracted = {}) {
  const observations = (extracted.observations || [])
    .filter((item) => item?.status === "present");
  const concepts = observations.map((item) => clean(item.concept)).filter(Boolean);
  const dimensions = (extracted.symptom_dimensions || []).map(clean).filter(Boolean);
  const evidence = observations.map((item) => clean(item.evidence)).filter(Boolean);
  const summary = summaryComplaint(extracted.case_summary);
  return shorten(concepts[0] || dimensions[0] || evidence[0] || summary || "尚未说明");
}

export function fullComplaint(extracted = {}) {
  const direct = clean(extracted.symptoms_text);
  if (direct) return shortenFull(direct);
  const observations = (extracted.observations || [])
    .filter((item) => item?.status === "present");
  const concepts = observations.map((item) => clean(item.concept)).filter(Boolean);
  if (concepts.length) return shortenFull([...new Set(concepts)].join("、"));
  const evidence = observations.map((item) => clean(item.evidence)).filter(Boolean);
  return shortenFull(evidence.join("、") || clean(extracted.case_summary) || "尚未说明");
}

function summaryComplaint(value) {
  let text = clean(value);
  const marker = text.indexOf("主诉");
  if (marker >= 0) text = text.slice(marker + 2);
  text = text.split(/[、，。；,.;]/, 1)[0];
  return text
    .replace(/^(?:用户|本人|患者)/, "")
    .replace(/^(?:目前|出现|感觉|有一点|有点|有)/, "")
    .trim();
}

function shorten(value) {
  const text = clean(value).split(/[、，。；,.;]/, 1)[0];
  return text.length > 18 ? `${text.slice(0, 18)}…` : text;
}

function shortenFull(value) {
  const text = clean(value);
  return text.length > 120 ? `${text.slice(0, 120)}…` : text;
}

function clean(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}
