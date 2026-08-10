function textValue(value) {
  return String(value == null ? "" : value);
}

function textList(value) {
  return Array.isArray(value)
    ? value.map(item => textValue(item).trim()).filter(Boolean)
    : [];
}

async function cloudAction(action, data = {}) {
  const response = await wx.cloud.callFunction({
    name: "api",
    data: { action, data },
  });
  if (!response || !response.result) throw new Error("云端设备绑定返回无效数据");
  if (response.result.ok === false) {
    throw new Error(response.result.error || "云端设备绑定请求失败");
  }
  return response.result;
}

function normalizeMembership(row = {}) {
  return {
    deviceId: textValue(row.deviceId).trim(),
    role: textValue(row.role || "VIEWER").trim().toUpperCase(),
    permissions: textList(row.permissions),
    serviceUserScopes: textList(row.serviceUserScopes || row.service_user_scopes),
  };
}

function normalizeDevice(row = {}) {
  return Object.assign(normalizeMembership(row), {
    name: textValue(row.name || "家庭药箱"),
    online: row.online === true,
    lastSeenAt: textValue(row.lastSeenAt || row.updatedAt),
  });
}

async function getDevicePairingCapability() {
  const ping = await cloudAction("PING");
  const version = textValue(ping.capabilities && ping.capabilities.devicePairing);
  return {
    supported: version === "v1",
    version,
    schemaRevision: textValue(ping.schemaRevision),
  };
}

async function getMyDevices() {
  const result = await cloudAction("GET_MY_DEVICES");
  return Array.isArray(result.items) ? result.items.map(normalizeDevice) : [];
}

async function redeemDevicePairingCode(pairingCode) {
  const code = textValue(pairingCode).trim();
  if (!code) throw new Error("pairingCode required");
  const result = await cloudAction("REDEEM_DEVICE_PAIRING_CODE", { pairingCode: code });
  return normalizeMembership(result);
}

module.exports = {
  getDevicePairingCapability,
  getMyDevices,
  redeemDevicePairingCode,
};
