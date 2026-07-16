function currentDeviceId() {
  const app = getApp();
  return app.globalData.deviceId || wx.getStorageSync("deviceId") || "zykh-qsm-001";
}

async function cloudAction(action, data = {}) {
  const response = await wx.cloud.callFunction({
    name: "api",
    data: { action, data: Object.assign({ deviceId: currentDeviceId() }, data) },
  });
  if (response.result && response.result.ok === false) {
    throw new Error(response.result.error || "cloud action failed");
  }
  return response.result;
}

async function loadStationSnapshot() {
  try {
    const snapshot = await cloudAction("GET_SNAPSHOT");
    const [device, medicines, latestVitals, records] = await Promise.all([
      cloudAction("GET_DEVICE"),
      cloudAction("LIST_MEDICINES", { limit: 100 }),
      cloudAction("GET_LATEST_VITALS"),
      cloudAction("LIST_RECORDS", { limit: 50 }),
    ]);
    return Object.assign({ device, medicines, latestVitals, records }, snapshot || {});
  } catch (error) {
    const [device, medicines, latestVitals, records] = await Promise.all([
      cloudAction("GET_DEVICE"),
      cloudAction("LIST_MEDICINES", { limit: 100 }),
      cloudAction("GET_LATEST_VITALS"),
      cloudAction("LIST_RECORDS", { limit: 50 }),
    ]);
    const summary = (device && device.syncSummary) || {};
    return {
      device,
      medicines,
      latestVitals,
      records,
      serviceUsers: summary.serviceUsers || [],
      plans: summary.plans || [],
      inquiries: summary.recentInquiries || [],
      compatibilityMode: true,
    };
  }
}

function subscribeStationSnapshot(onSnapshot, onError, intervalMs = 3000) {
  let active = true;
  let timer = null;
  const refresh = async () => {
    try {
      const snapshot = await loadStationSnapshot();
      if (active) onSnapshot(snapshot);
    } catch (error) {
      if (active && onError) onError(error);
    } finally {
      if (active) timer = setTimeout(refresh, Math.max(2000, intervalMs));
    }
  };
  refresh();
  return () => {
    active = false;
    if (timer) clearTimeout(timer);
  };
}

module.exports = { loadStationSnapshot, subscribeStationSnapshot };
