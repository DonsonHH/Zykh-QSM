function deviceId() {
  const app = getApp();
  return app.globalData.deviceId || wx.getStorageSync("deviceId") || "zykh-qsm-001";
}

function isMissingCreateCommandAction(error) {
  const message = String(error && error.message ? error.message : error || "");
  return /unknown action\s*:\s*CREATE_COMMAND\b/i.test(message);
}

async function createCommand(type, payload = {}, requestId = "") {
  if (type === "OPEN_CABINET") {
    throw new Error("远程开柜已禁用，请在终端现场完成操作。");
  }
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
      throw new Error("云端版本过旧，无法安全校验家属权限，请升级后重试。");
    }
    throw error;
  }
}

function requestVitals() {
  return createCommand("READ_VITALS_ALL", {});
}

function requestBeep(volume) {
  return createCommand("AUDIO_BEEP", volume == null ? {} : { volume: Number(volume) });
}

module.exports = { createCommand, requestVitals, requestBeep };
