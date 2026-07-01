import { useCallback, useEffect, useState } from "react";
import { loadSnapshot } from "../api/client.js";

export function useQsmData() {
  const [status, setStatus] = useState(null);
  const [medicines, setMedicines] = useState([]);
  const [plans, setPlans] = useState([]);
  const [records, setRecords] = useState([]);
  const [vitals, setVitals] = useState([]);
  const [profile, setProfile] = useState({});
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState(true);

  const notify = useCallback((message) => {
    setToast(message);
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => setToast(""), 2800);
  }, []);

  const refresh = useCallback(async () => {
    const snapshot = await loadSnapshot();
    setStatus(snapshot.status);
    setMedicines(snapshot.medicines);
    setPlans(snapshot.plans);
    setRecords(snapshot.records);
    setVitals(snapshot.vitals);
    setProfile(snapshot.profile);
    setLoading(false);
    return snapshot;
  }, []);

  useEffect(() => {
    refresh().catch((err) => {
      setLoading(false);
      notify(err.message);
    });
    const timer = window.setInterval(() => refresh().catch(() => {}), 15000);
    return () => window.clearInterval(timer);
  }, [notify, refresh]);

  return {
    status,
    medicines,
    plans,
    records,
    vitals,
    profile,
    loading,
    toast,
    notify,
    refresh
  };
}
