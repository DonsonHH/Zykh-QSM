import React, { useEffect, useMemo, useState } from "react";
import { Fingerprint, Plus, Save, ScanFace, Trash2, UserRound, XCircle } from "lucide-react";
import {
  createAdminUser,
  deleteAdminUser,
  enrollAdminFace,
  enrollAdminFingerprint,
  loadAdminFingerprintEnrollment,
  loadAdminUsers,
  removeAdminFace,
  removeAdminFingerprint,
  updateAdminUser
} from "../../api/admin.js";
import { AdminConfirmDialog } from "./AdminConfirmDialog.jsx";
import { AdminBiometricDialog } from "./AdminBiometricDialog.jsx";

const EMPTY_USER = { name: "", age: 0, profile: "", allergies: "", status: "家庭成员", note: "" };

function formatLastSeen(value) {
  if (!value) return "尚未用于确认";
  const [, month = "", day = "", time = ""] = value.match(/^\d{4}-(\d{2})-(\d{2})\s+(\d{2}:\d{2})/) || [];
  return month ? `${month}-${day} ${time}` : value;
}

export function AdminUsers({ notify, onSessionExpired }) {
  const [data, setData] = useState({ users: [], biometrics: {} });
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState(EMPTY_USER);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [biometricMode, setBiometricMode] = useState("");
  const selected = useMemo(() => data.users.find((user) => user.id === selectedId) || null, [data.users, selectedId]);
  const biometric = selected ? data.biometrics?.[selected.id] || {} : {};

  function handleError(error) {
    if (/会话/.test(error.message || "")) onSessionExpired();
    notify(error.message || "操作失败");
  }

  function refresh(preferredId) {
    return loadAdminUsers().then((next) => {
      setData(next);
      setSelectedId((current) => preferredId || current || next.users?.[0]?.id || "");
      return next;
    }).catch(handleError);
  }

  useEffect(() => { refresh(); }, []);

  useEffect(() => {
    if (creating) return;
    setForm(selected ? { ...selected } : EMPTY_USER);
  }, [selected?.id, creating]);

  function save() {
    setBusy(true);
    const action = creating ? createAdminUser(form) : updateAdminUser(selected.id, form);
    action
      .then((next) => {
        setData(next);
        const matched = next.users.find((user) => user.name === form.name);
        setSelectedId(matched?.id || selected?.id || next.users[0]?.id || "");
        setCreating(false);
        notify("服务对象信息已保存");
      })
      .catch(handleError)
      .finally(() => setBusy(false));
  }

  function submitConfirm(value) {
    const pending = confirm;
    if (!pending) return;
    setBusy(true);
    pending.action(value)
      .then((result) => {
        if (result?.ok === false) {
          notify(result.message || "生物识别操作未完成");
          return refresh(selected?.id);
        }
        notify(result.message || pending.success);
        setConfirm(null);
        setCreating(false);
        return refresh(pending.kind === "delete-user" ? undefined : selected?.id);
      })
      .catch(handleError)
      .finally(() => setBusy(false));
  }

  return (
    <div className="admin-view admin-users-view">
      <div className="admin-page-heading">
        <div className="admin-section-entry-cue"><h2>服务对象</h2><p>维护基础信息和本机生物识别绑定</p></div>
        <button type="button" className="admin-button primary compact" onClick={() => { setCreating(true); setSelectedId(""); setForm(EMPTY_USER); }}>
          <Plus size={17} aria-hidden="true" />新增对象
        </button>
      </div>
      <div className="admin-split-view users-split-view">
        <section className="admin-list-panel">
          <div className="admin-list-header"><span>姓名</span><span>年龄</span><span>状态</span></div>
          <div className="admin-list-scroll">
            {data.users.map((user) => (
              <button key={user.id} type="button" className={user.id === selectedId && !creating ? "active" : ""} onClick={() => { setCreating(false); setSelectedId(user.id); }}>
                <span className="admin-avatar"><UserRound size={18} aria-hidden="true" /></span>
                <strong>{user.name}</strong><span>{user.age || "--"}</span><small>{user.status || "--"}</small>
              </button>
            ))}
          </div>
        </section>
        <section className="admin-editor-panel">
          <header><div><h3>{creating ? "新增服务对象" : selected?.name || "选择服务对象"}</h3><span>{creating ? "建立本机服务档案" : selected?.id || ""}</span></div></header>
          {(creating || selected) ? (
            <>
              <div className="admin-form-grid user-editor-grid">
                <label><span>姓名</span><input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
                <label><span>年龄</span><input type="number" min="0" max="120" value={form.age} onChange={(event) => setForm({ ...form, age: Number(event.target.value) })} /></label>
                <label><span>身份 / 状态</span><input value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })} /></label>
                <label><span>基础病</span><input value={form.profile} onChange={(event) => setForm({ ...form, profile: event.target.value })} /></label>
                <label className="span-two"><span>过敏 / 禁忌</span><input value={form.allergies} onChange={(event) => setForm({ ...form, allergies: event.target.value })} /></label>
                <label className="span-two"><span>备注</span><textarea value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} /></label>
              </div>
              {!creating && (
                <div className="admin-biometric-block">
                  <div className="admin-biometric-row">
                    <button type="button" className={biometric.face_enrolled ? "bound" : ""} onClick={() => setBiometricMode("face")} disabled={busy}>
                      <ScanFace size={18} aria-hidden="true" /><span>人脸</span><strong>{biometric.face_enrolled ? "已绑定" : "录入"}</strong>
                    </button>
                    {biometric.face_enrolled && <button type="button" className="admin-biometric-remove" onClick={() => setConfirm({ title: "解除人脸绑定", expected: "REMOVE FACE", description: "仅解除本机服务对象绑定，板端样本保留供维护。", action: (value) => removeAdminFace(selected.id, value), success: "人脸绑定已解除" })} aria-label="解除人脸绑定"><XCircle size={18} /></button>}
                    <button type="button" className={biometric.fingerprint_enrolled ? "bound" : ""} onClick={() => setBiometricMode("fingerprint")} disabled={busy}>
                      <Fingerprint size={18} aria-hidden="true" /><span>指纹</span><strong>{biometric.fingerprint_enrolled ? `模板 ${biometric.fingerprint_template_id}` : "录入"}</strong>
                    </button>
                    {biometric.fingerprint_enrolled && <button type="button" className="admin-biometric-remove" onClick={() => setConfirm({ title: "删除指纹", expected: "REMOVE FINGERPRINT", description: "该操作会同时删除外设模板和本机绑定。", action: (value) => removeAdminFingerprint(selected.id, value), success: "指纹已删除" })} aria-label="删除指纹"><XCircle size={18} /></button>}
                  </div>
                  {(biometric.face_enrolled || biometric.fingerprint_enrolled) && (
                    <div className="admin-biometric-stats" aria-label="生物识别使用统计">
                      {biometric.face_enrolled && <span>面部确认 {biometric.face_match_count || 0} 次 · {formatLastSeen(biometric.face_last_seen_at)}</span>}
                      {biometric.fingerprint_enrolled && <span>指纹确认 {biometric.fingerprint_match_count || 0} 次 · {formatLastSeen(biometric.fingerprint_last_seen_at)}</span>}
                    </div>
                  )}
                </div>
              )}
              <footer className="admin-editor-actions">
                {!creating && <button type="button" className="admin-button danger ghost" onClick={() => setConfirm({ kind: "delete-user", title: "删除服务对象", expected: `DELETE ${selected.name}`, description: "基础资料和生物识别绑定将被删除，既有取药记录保留。", action: (value) => deleteAdminUser(selected.id, value), success: "服务对象已删除" })}><Trash2 size={17} />删除</button>}
                {creating && <button type="button" className="admin-button secondary" onClick={() => { setCreating(false); setSelectedId(data.users[0]?.id || ""); }}>取消</button>}
                <button type="button" className="admin-button primary" onClick={save} disabled={busy || !form.name.trim()}><Save size={17} />{busy ? "保存中" : "保存资料"}</button>
              </footer>
            </>
          ) : <p className="admin-empty-state">请从左侧选择服务对象</p>}
        </section>
      </div>
      <AdminConfirmDialog open={Boolean(confirm)} title={confirm?.title} description={confirm?.description} expected={confirm?.expected || ""} confirmLabel="确认执行" busy={busy} onCancel={() => setConfirm(null)} onConfirm={submitConfirm} />
      <AdminBiometricDialog
        open={Boolean(biometricMode)}
        mode={biometricMode}
        user={selected}
        onEnroll={async (userId) => {
          try {
            return await (biometricMode === "face" ? enrollAdminFace(userId) : enrollAdminFingerprint(userId));
          } catch (error) {
            if (/会话/.test(error.message || "")) onSessionExpired();
            throw error;
          }
        }}
        onProgress={async (userId, jobId) => {
          try {
            return await loadAdminFingerprintEnrollment(userId, jobId);
          } catch (error) {
            if (/会话/.test(error.message || "")) onSessionExpired();
            throw error;
          }
        }}
        onClose={() => setBiometricMode("")}
        onComplete={(result) => {
          notify(result?.message || `${biometricMode === "face" ? "人脸" : "指纹"}录入完成`);
          refresh(selected?.id);
        }}
      />
    </div>
  );
}
