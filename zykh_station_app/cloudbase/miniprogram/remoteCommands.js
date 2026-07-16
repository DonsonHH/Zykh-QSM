function deviceId() {
  const app = getApp();
  return app.globalData.deviceId || wx.getStorageSync("deviceId") || "zykh-qsm-001";
}

async function createCommand(type, payload = {}, requestId = "") {
  const response = await wx.cloud.callFunction({
    name: "api",
    data: {
      action: "CREATE_COMMAND",
      data: { deviceId: deviceId(), type, payload, requestId },
    },
  });
  if (response.result && response.result.ok === false) {
    throw new Error(response.result.error || "云端命令创建失败");
  }
  return response.result;
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
