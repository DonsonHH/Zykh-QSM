import React, { useCallback, useEffect, useRef, useState } from "react";
import { KeyRound, LoaderCircle, ShieldCheck } from "lucide-react";
import { closeAdminSession, createAdminSession, getAdminToken, loadAdminOverview } from "../api/admin.js";
import { BrandLogoImage } from "../components/BrandLogoImage.jsx";
import { AdminCabinet } from "../components/admin/AdminCabinet.jsx";
import { AdminDevices } from "../components/admin/AdminDevices.jsx";
import { AdminLogs } from "../components/admin/AdminLogs.jsx";
import { AdminOverview } from "../components/admin/AdminOverview.jsx";
import { AdminPlans } from "../components/admin/AdminPlans.jsx";
import { AdminSidebar } from "../components/admin/AdminSidebar.jsx";
import { AdminUsers } from "../components/admin/AdminUsers.jsx";

export function AdminConsole({ onExit }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [checking, setChecking] = useState(Boolean(getAdminToken()));
  const [pin, setPin] = useState("");
  const [loginError, setLoginError] = useState("");
  const [section, setSection] = useState("overview");
  const [overview, setOverview] = useState(null);
  const [loadingOverview, setLoadingOverview] = useState(false);
  const [notice, setNotice] = useState("");
  const noticeTimerRef = useRef(null);

  const notify = useCallback((message) => {
    setNotice(message || "");
    window.clearTimeout(noticeTimerRef.current);
    noticeTimerRef.current = window.setTimeout(() => setNotice(""), 3200);
  }, []);

  useEffect(() => () => window.clearTimeout(noticeTimerRef.current), []);

  const expireSession = useCallback(() => {
    setAuthenticated(false);
    setChecking(false);
    setOverview(null);
    setLoginError("管理员会话已失效，请重新验证。");
  }, []);

  const refreshOverview = useCallback(() => {
    if (!getAdminToken()) return Promise.resolve();
    setLoadingOverview(true);
    return loadAdminOverview()
      .then((data) => { setOverview(data); setAuthenticated(true); return data; })
      .catch((error) => { expireSession(); throw error; })
      .finally(() => { setLoadingOverview(false); setChecking(false); });
  }, [expireSession]);

  useEffect(() => {
    if (getAdminToken()) refreshOverview().catch(() => undefined);
  }, [refreshOverview]);

  function login(event) {
    event.preventDefault();
    setChecking(true);
    setLoginError("");
    createAdminSession(pin)
      .then(() => { setPin(""); return refreshOverview(); })
      .catch((error) => { setAuthenticated(false); setLoginError(error.message || "验证失败"); setChecking(false); });
  }

  function logout() {
    closeAdminSession().catch(() => undefined).finally(() => {
      setAuthenticated(false);
      setOverview(null);
      setPin("");
    });
  }

  if (checking && getAdminToken() && !authenticated) {
    return (
      <main className="admin-login-page" id="main-content">
        <section className="admin-login-panel admin-session-check">
          <LoaderCircle className="admin-spin" size={28} />
          <strong>正在验证管理员会话</strong>
        </section>
      </main>
    );
  }

  if (!authenticated) {
    return (
      <main className="admin-login-page" id="main-content">
        <section className="admin-login-panel">
          <BrandLogoImage size={70} />
          <div className="admin-login-copy"><h1>设备调试台</h1><p>验证管理员口令后进入</p></div>
          <form onSubmit={login}>
            <label><span>管理员口令</span><div><KeyRound size={19} /><input type="password" inputMode="numeric" autoFocus value={pin} onChange={(event) => setPin(event.target.value)} placeholder="输入口令" /></div></label>
            {loginError && <p className="admin-login-error" role="alert">{loginError}</p>}
            <button type="submit" className="admin-login-submit" disabled={checking || pin.length < 4}>
              {checking ? <LoaderCircle className="admin-spin" size={20} /> : <ShieldCheck size={20} />}
              {checking ? "正在验证" : "进入调试台"}
            </button>
          </form>
          <button type="button" className="admin-login-exit" onClick={onExit}>返回终端设置</button>
        </section>
      </main>
    );
  }

  return (
    <main className="admin-console" id="main-content">
      <AdminSidebar active={section} onChange={setSection} onExit={onExit} onLogout={logout} />
      <section className="admin-workspace">
        {section === "overview" && <AdminOverview data={overview} loading={loadingOverview} onRefresh={() => refreshOverview().catch((error) => notify(error.message))} />}
        {section === "users" && <AdminUsers notify={notify} onSessionExpired={expireSession} />}
        {section === "plans" && <AdminPlans notify={notify} onSessionExpired={expireSession} />}
        {section === "cabinet" && <AdminCabinet notify={notify} onSessionExpired={expireSession} />}
        {section === "devices" && <AdminDevices overview={overview} loading={loadingOverview} onRefresh={() => refreshOverview().catch((error) => notify(error.message))} notify={notify} onSessionExpired={expireSession} />}
        {section === "logs" && <AdminLogs notify={notify} onSessionExpired={expireSession} />}
      </section>
      <div className={`admin-notice ${notice ? "show" : ""}`} role="status">{notice}</div>
    </main>
  );
}
