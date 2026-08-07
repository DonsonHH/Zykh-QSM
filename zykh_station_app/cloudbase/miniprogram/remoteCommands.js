function deviceId() {
  const app = getApp();
  return app.globalData.deviceId || wx.getStorageSync("deviceId") || "zykh-qsm-001";
}

function nowText() {
  const date = new Date();
  const pad = value => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function safeId(value) {
  return String(value || "unknown").replace(/[^A-Za-z0-9_.-]/g, "-");
}

async function createLegacyCommand(type, payload, requestId) {
  const currentDeviceId = deviceId();
  const row = {
    deviceId: currentDeviceId,
    type,
    payload,
    status: "pending",
    source: "miniprogram",
    createdAt: nowText(),
    updatedAt: nowText(),
  };
  const collection = wx.cloud.database().collection("commands");
  if (requestId) {
    const documentId = `${currentDeviceId}-request-${safeId(requestId)}`;
    try {
      const existing = await collection.doc(documentId).get();
      if (existing && existing.data) return existing.data;
    } catch (error) {
      // A missing document is created below. CloudBase adds _openid itself.
    }
    await collection.doc(documentId).set({ data: row });
    return Object.assign({ _id: documentId, compatibilityMode: true }, row);
  }
  const result = await collection.add({ data: row });
  return Object.assign({ _id: result._id, compatibilityMode: true }, row);
}

function isMissingCreateCommandAction(error) {
  const message = String(error && error.message ? error.message : error || "");
  return /unknown action\s*:\s*CREATE_COMMAND\b/i.test(message);
}

async function createCommand(type, payload = {}, requestId = "") {
  try {
    const response = await wx.cloud.callFunction({
      name: "api",
      data: {
        action: "CREATE_COMMAND",
        data: { deviceId: deviceId(), type, payload, requestId },
      },
    });
    if (!response || !response.result) {
      throw new Error("云端命令创建返回无效数据");
    }
    if (response.result.ok === false) {
      throw new Error(response.result.error || "云端命令创建失败");
    }
    return response.result;
  } catch (error) {
    if (isMissingCreateCommandAction(error)) {
      // Only a confirmed v1 API compatibility miss may use the legacy write.
      // Timeouts, permission errors and payload validation failures must remain
      // visible to the caller instead of being presented as successful submits.
      return createLegacyCommand(type, payload, requestId);
    }
    throw error;
  }
}

let pendingCabinetOpen = null;

function requestCabinetOpen({ slot, medicineId = "", targetUserId = "", targetUserName = "", reason = "家属端远程开柜" }) {
  if (pendingCabinetOpen) return pendingCabinetOpen;
  const requestId = `open-${Date.now()}-${Number(slot)}`;
  pendingCabinetOpen = createCommand("OPEN_CABINET", {
      slot: Number(slot),
      quantity: 1,
      medicine_id: medicineId,
      target_user_id: targetUserId,
      target_user_name: targetUserName,
      actor_name: targetUserName || "家属端",
      reason,
      remote_confirmed: true,
      request_id: requestId,
    }, requestId)
    .finally(() => { pendingCabinetOpen = null; });
  return pendingCabinetOpen;
}

function requestVitals() {
  return createCommand("READ_VITALS_ALL", {});
}

function requestBeep(volume) {
  return createCommand("AUDIO_BEEP", volume == null ? {} : { volume: Number(volume) });
}

module.exports = { createCommand, requestCabinetOpen, requestVitals, requestBeep };
