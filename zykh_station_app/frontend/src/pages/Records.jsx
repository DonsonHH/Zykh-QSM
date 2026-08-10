import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  loadRecentRecords,
  loadRecordsSummary,
  loadServiceUserInquiries,
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
import { UserInquiryHistoryDrawer } from "../components/UserInquiryHistoryDrawer.jsx";

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
  const [historyUser, setHistoryUser] = useState(null);
  const [historyState, setHistoryState] = useState({
    loading: false,
    loadingMore: false,
    inquiries: [],
    nextCursor: null,
    error: ""
  });
  const snapshotRef = useRef("");
  const historyRequestRef = useRef(0);
  const historyTriggerRef = useRef(null);

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
      historyRequestRef.current += 1;
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

  function loadHistoryPage(user, { cursor = "", append = false } = {}) {
    const requestId = ++historyRequestRef.current;
    setHistoryState((current) => append
      ? { ...current, loadingMore: true, error: "" }
      : { loading: true, loadingMore: false, inquiries: [], nextCursor: null, error: "" });
    loadServiceUserInquiries(user.id, { limit: 20, cursor })
      .then((data) => {
        if (historyRequestRef.current !== requestId) return;
        const incoming = Array.isArray(data.inquiries) ? data.inquiries : [];
        setHistoryState((current) => {
          const combined = append ? [...current.inquiries, ...incoming] : incoming;
          const inquiries = [...new Map(combined.map((inquiry) => [inquiry.session_id, inquiry])).values()];
          return {
            loading: false,
            loadingMore: false,
            inquiries,
            nextCursor: data.next_cursor || null,
            error: ""
          };
        });
      })
      .catch((error) => {
        if (historyRequestRef.current !== requestId) return;
        setHistoryState((current) => ({
          loading: false,
          loadingMore: false,
          inquiries: append ? current.inquiries : [],
          nextCursor: append ? current.nextCursor : null,
          error: error.message || "历史问询加载失败"
        }));
      });
  }

  function handleOpenHistory(user, trigger) {
    historyTriggerRef.current = trigger instanceof HTMLElement
      ? trigger
      : document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setHistoryUser(user);
    loadHistoryPage(user);
  }

  function handleCloseHistory() {
    const trigger = historyTriggerRef.current;
    historyRequestRef.current += 1;
    setHistoryUser(null);
    window.requestAnimationFrame(() => trigger?.focus());
  }

  function handleRefreshHistory() {
    if (historyUser) loadHistoryPage(historyUser);
  }

  function handleLoadMoreHistory() {
    if (!historyUser || !historyState.nextCursor || historyState.loadingMore) return;
    loadHistoryPage(historyUser, { cursor: historyState.nextCursor, append: true });
  }

  return (
    <main className="records-page" id="main-content" aria-busy={initialLoading}>
      <RecordSummaryCards summary={summary} loading={initialLoading} />
      <div className="records-main-grid">
        <ServiceUserList users={serviceUsers} onSelectUser={handleOpenHistory} />
        <RecentRecordList records={records} />
        <div className="records-side-stack">
          <TodayPlanList plans={todayPlans} />
          <SyncStatusCard syncStatus={syncStatus} syncing={syncing} networkStatus={networkStatus} onSync={handleSync} />
        </div>
      </div>
      {historyUser ? (
        <UserInquiryHistoryDrawer
          user={historyUser}
          state={historyState}
          onClose={handleCloseHistory}
          onRefresh={handleRefreshHistory}
          onLoadMore={handleLoadMoreHistory}
        />
      ) : null}
    </main>
  );
}
