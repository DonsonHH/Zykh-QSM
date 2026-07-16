import React, { useEffect, useState } from "react";
import {
  loadRecentRecords,
  loadRecordsSummary,
  loadServiceUsers,
  loadSyncStatus,
  loadTodayPlans,
  runSync
} from "../api/records.js";
import { RecentRecordList } from "../components/RecentRecordList.jsx";
import { RecordSummaryCards } from "../components/RecordSummaryCards.jsx";
import { ServiceUserList } from "../components/ServiceUserList.jsx";
import { SyncStatusCard } from "../components/SyncStatusCard.jsx";
import { TodayPlanList } from "../components/TodayPlanList.jsx";

const defaultSummary = {
  today_service_users: 0,
  pending_sync_count: 0,
  local_record_count: 0,
  today_plan_count: 0
};

export function Records({ notify, networkStatus }) {
  const [summary, setSummary] = useState(defaultSummary);
  const [records, setRecords] = useState([]);
  const [syncStatus, setSyncStatus] = useState(null);
  const [serviceUsers, setServiceUsers] = useState([]);
  const [todayPlans, setTodayPlans] = useState([]);
  const [syncing, setSyncing] = useState(false);

  function refreshRecords({ silent = false } = {}) {
    return Promise.all([loadRecordsSummary(), loadRecentRecords(), loadSyncStatus(), loadServiceUsers(), loadTodayPlans()])
      .then(([summaryResponse, recentResponse, syncResponse, usersResponse, plansResponse]) => {
        setSummary(summaryResponse.summary || defaultSummary);
        setRecords(recentResponse.records || []);
        setSyncStatus(syncResponse);
        setServiceUsers(usersResponse.users || []);
        setTodayPlans(plansResponse.plans || []);
      })
      .catch((error) => {
        if (!silent) notify(error.message || "记录数据加载失败");
      });
  }

  useEffect(() => {
    refreshRecords();
    const timer = window.setInterval(() => refreshRecords({ silent: true }), 3000);
    return () => window.clearInterval(timer);
  }, []);

  function handleSync() {
    setSyncing(true);
    runSync()
      .then((data) => {
        notify(data.message || "同步状态已更新");
        return refreshRecords();
      })
      .catch((error) => notify(error.message || "同步失败"))
      .finally(() => setSyncing(false));
  }

  return (
    <main className="records-page" id="main-content">
      <RecordSummaryCards summary={summary} />
      <div className="records-main-grid">
        <ServiceUserList users={serviceUsers} />
        <RecentRecordList records={records} />
        <div className="records-side-stack">
          <TodayPlanList plans={todayPlans} />
          <SyncStatusCard syncStatus={syncStatus} syncing={syncing} networkStatus={networkStatus} onSync={handleSync} />
        </div>
      </div>
    </main>
  );
}
