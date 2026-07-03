import React, { useEffect, useState } from "react";
import { loadRecentRecords, loadRecordsSummary, loadSyncStatus, runMockSync } from "../api/records.js";
import { RecentRecordList } from "../components/RecentRecordList.jsx";
import { RecordSummaryCards } from "../components/RecordSummaryCards.jsx";
import { ServiceUserList } from "../components/ServiceUserList.jsx";
import { SyncStatusCard } from "../components/SyncStatusCard.jsx";
import { TodayPlanList } from "../components/TodayPlanList.jsx";

const defaultSummary = {
  today_service_users: 3,
  pending_sync_count: 12,
  local_record_count: 387,
  today_plan_count: 3
};

export function Records({ notify }) {
  const [summary, setSummary] = useState(defaultSummary);
  const [records, setRecords] = useState([]);
  const [syncStatus, setSyncStatus] = useState(null);
  const [syncing, setSyncing] = useState(false);

  function refreshRecords() {
    return Promise.all([loadRecordsSummary(), loadRecentRecords(), loadSyncStatus()])
      .then(([summaryResponse, recentResponse, syncResponse]) => {
        setSummary(summaryResponse.summary || defaultSummary);
        setRecords(recentResponse.records || []);
        setSyncStatus(syncResponse);
      })
      .catch((error) => notify(error.message || "记录数据加载失败"));
  }

  useEffect(() => {
    refreshRecords();
  }, []);

  function handleMockSync() {
    setSyncing(true);
    runMockSync()
      .then((data) => {
        notify(data.message || "模拟同步完成");
        return refreshRecords();
      })
      .catch((error) => notify(error.message || "模拟同步失败"))
      .finally(() => setSyncing(false));
  }

  return (
    <main className="records-page" id="main-content">
      <RecordSummaryCards summary={summary} />
      <div className="records-main-grid">
        <ServiceUserList />
        <RecentRecordList records={records} />
        <div className="records-side-stack">
          <TodayPlanList />
          <SyncStatusCard syncStatus={syncStatus} syncing={syncing} onSync={handleMockSync} />
        </div>
      </div>
    </main>
  );
}
