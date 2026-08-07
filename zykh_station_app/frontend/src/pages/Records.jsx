import React, { useCallback, useEffect, useRef, useState } from "react";
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
const RECORDS_REFRESH_INTERVAL_MS = 3000;

export function Records({ notify, networkStatus }) {
  const [summary, setSummary] = useState(defaultSummary);
  const [records, setRecords] = useState([]);
  const [syncStatus, setSyncStatus] = useState(null);
  const [serviceUsers, setServiceUsers] = useState([]);
  const [todayPlans, setTodayPlans] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const snapshotRef = useRef("");

  const refreshRecords = useCallback(({ silent = false } = {}) => {
    return Promise.all([loadRecordsSummary(), loadRecentRecords(), loadSyncStatus(), loadServiceUsers(), loadTodayPlans()])
      .then(([summaryResponse, recentResponse, syncResponse, usersResponse, plansResponse]) => {
        const nextSnapshot = {
          summary: summaryResponse.summary || defaultSummary,
          records: recentResponse.records || [],
          syncStatus: syncResponse,
          serviceUsers: usersResponse.users || [],
          todayPlans: plansResponse.plans || []
        };
        const signature = JSON.stringify(nextSnapshot);
        if (signature === snapshotRef.current) return;
        snapshotRef.current = signature;
        setSummary(nextSnapshot.summary);
        setRecords(nextSnapshot.records);
        setSyncStatus(nextSnapshot.syncStatus);
        setServiceUsers(nextSnapshot.serviceUsers);
        setTodayPlans(nextSnapshot.todayPlans);
      })
      .catch((error) => {
        if (!silent) notify(error.message || "记录数据加载失败");
      });
  }, [notify]);

  useEffect(() => {
    let active = true;
    refreshRecords().finally(() => {
      if (active) setInitialLoading(false);
    });
    const timer = window.setInterval(() => refreshRecords({ silent: true }), RECORDS_REFRESH_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshRecords]);

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
    <main className="records-page" id="main-content" aria-busy={initialLoading}>
      <RecordSummaryCards summary={summary} loading={initialLoading} />
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
