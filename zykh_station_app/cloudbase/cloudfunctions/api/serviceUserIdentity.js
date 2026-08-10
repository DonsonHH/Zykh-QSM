const crypto = require("crypto");

function firstText(...values) {
  for (const value of values) {
    const text = String(value === undefined || value === null ? "" : value).trim();
    if (text) return text;
  }
  return "";
}

function safeDocumentId(value) {
  return String(value || "unknown").replace(/[^A-Za-z0-9_.-]/g, "-");
}

function serviceUserIdentity(row = {}) {
  const personId = firstText(row.id, row.user_id, row.userId);
  const generation = firstText(row.persona_generation, row.personaGeneration);
  if (!personId) throw new Error("service user id required");
  return { personId, generation };
}

function serviceUserDocumentId(deviceId, row = {}) {
  const normalizedDeviceId = firstText(deviceId);
  if (!normalizedDeviceId) throw new Error("device id required");
  const { personId, generation } = serviceUserIdentity(row);
  if (!generation) return `${normalizedDeviceId}-user-${safeDocumentId(personId)}`;
  const generationDigest = crypto.createHash("sha256").update(generation, "utf8").digest("hex").slice(0, 16);
  return `${normalizedDeviceId}-user-${safeDocumentId(personId)}-generation-${generationDigest}`;
}

function legacyServiceUserDocumentId(deviceId, row = {}) {
  const normalizedDeviceId = firstText(deviceId);
  if (!normalizedDeviceId) throw new Error("device id required");
  const { personId } = serviceUserIdentity(row);
  return `${normalizedDeviceId}-user-${safeDocumentId(personId)}`;
}

module.exports = {
  legacyServiceUserDocumentId,
  serviceUserDocumentId,
  serviceUserIdentity,
};
