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

function collectionQuery(name, deviceId) {
  let query = wx.cloud.database().collection(name).where({ deviceId });
  if (name === "devices") query = wx.cloud.database().collection(name).where({ _id: deviceId });
  if (name === "medicines") return query.limit(100);
  if (["vitals", "records"].includes(name)) return query.orderBy("createdAt", "desc").limit(1);
  if (name === "commands") return query.orderBy("updatedAt", "desc").limit(1);
  return query.limit(100);
}

function subscribeStationSnapshot(onSnapshot, onError, intervalMs = 5000) {
  let active = true;
  let refreshTimer = null;
  let fallbackTimer = null;
  let refreshing = false;
  let refreshAgain = false;
  const watchers = [];

  const refresh = async () => {
    if (!active) return;
    if (refreshing) {
      refreshAgain = true;
      return;
    }
    refreshing = true;
    try {
      const snapshot = await loadStationSnapshot();
      if (active) onSnapshot(snapshot);
    } catch (error) {
      if (active && onError) onError(error);
    } finally {
      refreshing = false;
      if (active && refreshAgain) {
        refreshAgain = false;
        queueRefresh(80);
      }
    }
  };

  const queueRefresh = (delay = 120) => {
    if (!active) return;
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      refresh();
    }, delay);
  };

  const attachWatchers = async () => {
    let schemaVersion = 1;
    try {
      const ping = await cloudAction("PING");
      schemaVersion = Number((ping && ping.schemaVersion) || 1);
    } catch (error) {
      // Periodic refresh remains active when realtime watch setup is unavailable.
    }
    if (!active) return;
    const names = ["devices", "medicines", "vitals", "records", "commands"];
    if (schemaVersion >= 2) names.push("service_users", "today_plans", "inquiries");
    names.forEach(name => {
      try {
        const watcher = collectionQuery(name, currentDeviceId()).watch({
          onChange: () => queueRefresh(),
          onError: error => {
            if (active && onError) onError(error);
          },
        });
        watchers.push(watcher);
      } catch (error) {
        if (active && onError) onError(error);
      }
    });
  };

  refresh();
  attachWatchers();
  fallbackTimer = setInterval(refresh, Math.max(3000, Number(intervalMs) || 5000));
  return () => {
    active = false;
    if (refreshTimer) clearTimeout(refreshTimer);
    if (fallbackTimer) clearInterval(fallbackTimer);
    watchers.forEach(watcher => {
      try { watcher.close(); } catch (error) { /* already closed */ }
    });
  };
}

module.exports = { loadStationSnapshot, subscribeStationSnapshot };
