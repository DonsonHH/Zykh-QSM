import React, { useEffect, useMemo, useState } from "react";
import { CalendarClock, Plus, Save, Trash2 } from "lucide-react";
import {
  createAdminTodayPlan,
  deleteAdminTodayPlan,
  loadAdminTodayPlans,
  updateAdminTodayPlan
} from "../../api/admin.js";
import { AdminConfirmDialog } from "./AdminConfirmDialog.jsx";

const todayText = () => new Date().toLocaleDateString("sv-SE");
const EMPTY_PLAN = {
  time: "08:00",
  service_user_id: "",
  medicine_id: "",
  dose: "1片",
  status: "待执行",
  schedule_type: "daily",
  interval_days: 2,
  weekdays: [],
  start_date: todayText()
};
const WEEKDAYS = [
  [1, "一"], [2, "二"], [3, "三"], [4, "四"], [5, "五"], [6, "六"], [7, "日"]
];

export function AdminPlans({ notify, onSessionExpired }) {
  const [data, setData] = useState({ plans: [], users: [], medicines: [] });
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState(EMPTY_PLAN);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const selected = useMemo(() => data.plans.find((plan) => plan.id === selectedId) || null, [data.plans, selectedId]);

  function handleError(error) {
    if (/会话/.test(error.message || "")) onSessionExpired();
    notify(error.message || "计划操作失败");
  }

  function applyData(next, preferredId = "") {
    setData(next);
    setSelectedId(preferredId || next.plans?.[0]?.id || "");
  }

  useEffect(() => {
    loadAdminTodayPlans()
      .then((next) => applyData(next))
      .catch(handleError);
  }, []);

  useEffect(() => {
    if (creating) return;
    setForm(selected ? {
      time: selected.time,
      service_user_id: selected.service_user_id,
      medicine_id: selected.medicine_id,
      dose: selected.dose || "按说明",
      status: selected.status === "未到期" ? "待执行" : selected.status,
      schedule_type: selected.schedule_type || "daily",
      interval_days: selected.interval_days || 2,
      weekdays: selected.weekdays || [],
      start_date: selected.start_date || todayText()
    } : EMPTY_PLAN);
  }, [selected?.id, selected?.updated_at, creating]);

  function startCreate() {
    setCreating(true);
    setSelectedId("");
    setForm({
      ...EMPTY_PLAN,
      service_user_id: data.users[0]?.id || "",
      medicine_id: data.medicines[0]?.id || ""
    });
  }

  function toggleWeekday(value) {
    const selectedDays = new Set(form.weekdays || []);
    if (selectedDays.has(value)) selectedDays.delete(value);
    else selectedDays.add(value);
    setForm({ ...form, weekdays: [...selectedDays].sort((a, b) => a - b) });
  }

  function save() {
    if (!form.service_user_id || !form.medicine_id) return;
    if (form.schedule_type === "weekly" && !(form.weekdays || []).length) {
      notify("请至少选择一个每周执行日");
      return;
    }
    setBusy(true);
    const action = creating ? createAdminTodayPlan(form) : updateAdminTodayPlan(selected.id, form);
    action
      .then((next) => {
        const match = next.plans.find((plan) => (
          plan.time === form.time &&
          plan.service_user_id === form.service_user_id &&
          plan.medicine_id === form.medicine_id
        ));
        applyData(next, match?.id || selected?.id || "");
        setCreating(false);
        notify("今日用药计划已保存");
      })
      .catch(handleError)
      .finally(() => setBusy(false));
  }

  function remove() {
    if (!selected) return;
    setBusy(true);
    deleteAdminTodayPlan(selected.id)
      .then((next) => {
        applyData(next);
        setConfirmDelete(false);
        notify("今日用药计划已删除");
      })
      .catch(handleError)
      .finally(() => setBusy(false));
  }

  return (
    <div className="admin-view admin-plans-view">
      <div className="admin-page-heading">
        <div className="admin-section-entry-cue"><h2>用药计划</h2><p>设置每天、间隔天数或每周固定日期</p></div>
        <button type="button" className="admin-button primary compact" onClick={startCreate}><Plus size={17} />新增计划</button>
      </div>
      <div className="admin-split-view plans-split-view">
        <section className="admin-list-panel admin-plan-list-panel">
          <div className="admin-plan-list-header"><span>时间</span><span>服务对象</span><span>药品</span><span>周期</span></div>
          <div className="admin-plan-list-scroll">
            {data.plans.map((plan) => (
              <button key={plan.id} type="button" className={plan.id === selectedId && !creating ? "active" : ""} onClick={() => { setCreating(false); setSelectedId(plan.id); }}>
                <time>{plan.time}</time><strong>{plan.target_user}</strong><span>{plan.medicine}</span><small>{plan.frequency_label}</small>
              </button>
            ))}
            {!data.plans.length ? <p className="admin-empty-state">暂无计划，可点击右上角新增。</p> : null}
          </div>
        </section>
        <section className="admin-editor-panel plan-editor-panel">
          <header><div><h3>{creating ? "新增今日计划" : selected ? `${selected.target_user} · ${selected.time}` : "选择计划"}</h3><span>{selected?.id || "计划保存后立即同步到首页与记录页"}</span></div><CalendarClock size={22} /></header>
          {(creating || selected) ? (
            <>
              <div className="admin-form-grid plan-editor-grid">
                <label><span>用药时间</span><input type="time" value={form.time} onChange={(event) => setForm({ ...form, time: event.target.value })} /></label>
                <label><span>今日状态</span><select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option>待执行</option><option>已执行</option><option>已跳过</option></select></label>
                <label><span>计划周期</span><select value={form.schedule_type} onChange={(event) => setForm({ ...form, schedule_type: event.target.value })}><option value="daily">每天</option><option value="interval">每隔几天</option><option value="weekly">每周指定日</option></select></label>
                <label><span>开始日期</span><input type="date" value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} /></label>
                {form.schedule_type === "interval" ? <label className="span-two"><span>间隔天数</span><input type="number" min="2" max="30" value={form.interval_days} onChange={(event) => setForm({ ...form, interval_days: Math.max(2, Number(event.target.value) || 2) })} /></label> : null}
                {form.schedule_type === "weekly" ? (
                  <fieldset className="admin-weekday-picker span-two">
                    <legend>每周执行日</legend>
                    {WEEKDAYS.map(([value, label]) => (
                      <button key={value} type="button" className={(form.weekdays || []).includes(value) ? "active" : ""} onClick={() => toggleWeekday(value)}>{label}</button>
                    ))}
                  </fieldset>
                ) : null}
                <label className="span-two"><span>服务对象</span><select value={form.service_user_id} onChange={(event) => setForm({ ...form, service_user_id: event.target.value })}>{data.users.map((user) => <option key={user.id} value={user.id}>{user.name} · {user.age || "年龄未填"}</option>)}</select></label>
                <label className="span-two"><span>药柜药品</span><select value={form.medicine_id} onChange={(event) => setForm({ ...form, medicine_id: event.target.value })}>{data.medicines.map((medicine) => <option key={medicine.id} value={medicine.id}>{medicine.hardware_slot} 号仓 · {medicine.name}</option>)}</select></label>
                <label className="span-two"><span>单次用量</span><input value={form.dose} maxLength={40} onChange={(event) => setForm({ ...form, dose: event.target.value })} /></label>
              </div>
              <footer className="admin-editor-actions">
                {!creating ? <button type="button" className="admin-button danger ghost" onClick={() => setConfirmDelete(true)}><Trash2 size={17} />删除</button> : null}
                {creating ? <button type="button" className="admin-button secondary" onClick={() => { setCreating(false); setSelectedId(data.plans[0]?.id || ""); }}>取消</button> : null}
                <button type="button" className="admin-button primary" onClick={save} disabled={busy || !form.service_user_id || !form.medicine_id || (form.schedule_type === "weekly" && !(form.weekdays || []).length)}><Save size={17} />{busy ? "保存中" : "保存计划"}</button>
              </footer>
            </>
          ) : <p className="admin-empty-state">请选择或新增一条今日用药计划。</p>}
        </section>
      </div>
      <AdminConfirmDialog open={confirmDelete} title="删除今日用药计划" description={selected ? `${selected.target_user} · ${selected.time} · ${selected.medicine}` : ""} expected="DELETE PLAN" confirmLabel="确认删除" busy={busy} onCancel={() => setConfirmDelete(false)} onConfirm={remove} />
    </div>
  );
}
