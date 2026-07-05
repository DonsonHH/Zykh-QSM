import React, { useEffect, useMemo, useState } from "react";
import { ArrowLeft, DoorOpen, Mic, PackageCheck, Save, Signal, Trash2, UserRound, Volume2, WifiOff } from "lucide-react";
import { openCabinet } from "../api/dispense.js";
import { loadMedicines, updateMedicine } from "../api/medicines.js";
import { loadNetworkStatus, setNetworkMode } from "../api/network.js";
import { setHostMicVolume, testAudioRelay } from "../api/audio.js";
import { deleteServiceUser, loadServiceUsers, updateServiceUser } from "../api/records.js";

function toEditForm(medicine) {
  return {
    name: medicine?.name || "",
    manufacturer: medicine?.manufacturer || "",
    barcode: medicine?.barcode || "",
    stock: medicine?.stock ?? 0,
    unit: medicine?.unit || "盒",
    expire_date: medicine?.expire_date || "",
    category: medicine?.category || "",
    safety_note: medicine?.safety_note || ""
  };
}

function toUserForm(user) {
  return {
    name: user?.name || "",
    age: user?.age ?? 0,
    profile: user?.profile || "",
    allergies: user?.allergies || "",
    status: user?.status || "",
    note: user?.note || ""
  };
}

export function Settings({ notify, onNavigate, networkStatus, onNetworkStatusChange }) {
  const [medicines, setMedicines] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState(toEditForm(null));
  const [serviceUsers, setServiceUsers] = useState([]);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [userForm, setUserForm] = useState(toUserForm(null));
  const [saving, setSaving] = useState(false);
  const [savingUser, setSavingUser] = useState(false);
  const [deletingUser, setDeletingUser] = useState(false);
  const [opening, setOpening] = useState(false);
  const [speakerVolume, setSpeakerVolume] = useState(230);
  const [micVolume, setMicVolume] = useState(70);
  const [networkMode, setNetworkModeState] = useState(networkStatus?.mode || "sim");
  const localNetworkMode = networkMode === "local";
  const selectedMedicine = useMemo(
    () => medicines.find((medicine) => medicine.id === selectedId) || medicines[0] || null,
    [medicines, selectedId]
  );
  const selectedUser = useMemo(
    () => serviceUsers.find((user) => user.id === selectedUserId) || serviceUsers[0] || null,
    [serviceUsers, selectedUserId]
  );

  useEffect(() => {
    loadMedicines()
      .then((data) => {
        const rows = data.medicines || [];
        setMedicines(rows);
        setSelectedId((current) => current || rows[0]?.id || "");
      })
      .catch((error) => notify(error.message || "药柜数据加载失败"));
  }, [notify]);

  useEffect(() => {
    loadServiceUsers()
      .then((data) => {
        const rows = data.users || [];
        setServiceUsers(rows);
        setSelectedUserId((current) => current || rows[0]?.id || "");
      })
      .catch((error) => notify(error.message || "服务对象加载失败"));
  }, [notify]);

  useEffect(() => {
    setForm(toEditForm(selectedMedicine));
  }, [selectedMedicine?.id]);

  useEffect(() => {
    setUserForm(toUserForm(selectedUser));
  }, [selectedUser?.id]);

  useEffect(() => {
    if (networkStatus?.mode) {
      setNetworkModeState(networkStatus.mode);
    }
  }, [networkStatus?.mode]);

  function updateForm(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updateUserForm(key, value) {
    setUserForm((current) => ({ ...current, [key]: value }));
  }

  function saveMedicine() {
    if (!selectedMedicine || saving) {
      return;
    }
    setSaving(true);
    updateMedicine(selectedMedicine.id, {
      ...form,
      stock: Number(form.stock) || 0
    })
      .then((data) => {
        setMedicines((current) => current.map((item) => (item.id === data.medicine.id ? data.medicine : item)));
        notify(data.message || "药品信息已保存");
      })
      .catch((error) => notify(error.message || "保存失败"))
      .finally(() => setSaving(false));
  }

  function saveServiceUser() {
    if (!selectedUser || savingUser) {
      return;
    }
    setSavingUser(true);
    updateServiceUser(selectedUser.id, {
      ...userForm,
      age: Number(userForm.age) || 0
    })
      .then((data) => {
        const rows = data.users || [];
        setServiceUsers(rows);
        const updated = rows.find((user) => user.id === selectedUser.id);
        if (updated) {
          setSelectedUserId(updated.id);
        }
        notify("服务对象信息已保存");
      })
      .catch((error) => notify(error.message || "服务对象保存失败"))
      .finally(() => setSavingUser(false));
  }

  function removeServiceUser() {
    if (!selectedUser || deletingUser) {
      return;
    }
    const confirmed = window.confirm(`确认删除服务对象「${selectedUser.name}」吗？删除后不会影响已经生成的本地取药记录。`);
    if (!confirmed) {
      return;
    }
    setDeletingUser(true);
    deleteServiceUser(selectedUser.id)
      .then((data) => {
        const rows = data.users || [];
        setServiceUsers(rows);
        setSelectedUserId(rows[0]?.id || "");
        setUserForm(toUserForm(rows[0] || null));
        notify("服务对象已删除");
      })
      .catch((error) => notify(error.message || "服务对象删除失败"))
      .finally(() => setDeletingUser(false));
  }

  function openSelectedCabinet() {
    if (!selectedMedicine || opening) {
      return;
    }
    setOpening(true);
    openCabinet({
      slot: selectedMedicine.hardware_slot,
      medicine_id: selectedMedicine.id,
      quantity: 1,
      confirmed_open: true,
      reason: "设置页柜门测试"
    })
      .then((data) => notify(data.message || `${selectedMedicine.hardware_slot}号柜门已请求打开`))
      .catch((error) => notify(error.message || "开柜失败"))
      .finally(() => setOpening(false));
  }

  function testSpeaker() {
    testAudioRelay({ volume: speakerVolume, text: "声音测试完成。" })
      .then((data) => notify(data.ok ? "外放测试已发送" : data.message || "外放测试失败"))
      .catch((error) => notify(error.message || "外放测试失败"));
  }

  function applyMicVolume() {
    setHostMicVolume(micVolume)
      .then((data) => notify(data.ok ? data.message : data.message || "麦克风音量调整失败"))
      .catch((error) => notify(error.message || "麦克风音量调整失败"));
  }

  function switchNetworkMode(mode) {
    setNetworkModeState(mode);
    setNetworkMode(mode)
      .then((data) => {
        onNetworkStatusChange?.(data);
        notify(mode === "sim" ? "已切换为外设 SIM 状态读取" : "已切换为本地离线显示");
      })
      .catch((error) => notify(error.message || "网络模式切换失败"));
  }

  function refreshNetwork() {
    loadNetworkStatus()
      .then((data) => {
        onNetworkStatusChange?.(data);
        notify("网络状态已刷新");
      })
      .catch((error) => notify(error.message || "网络状态读取失败"));
  }

  return (
    <main className="settings-page" id="main-content">
      <section className="settings-header-card">
        <button className="icon-action" type="button" onClick={() => onNavigate("home")} aria-label="返回首页">
          <ArrowLeft size={24} aria-hidden="true" />
        </button>
        <div>
          <p>后台设置</p>
          <h2>药柜、服务对象、声音与网络状态</h2>
        </div>
      </section>

      <section className="settings-grid">
        <article className="settings-card medicine-admin-card">
          <header>
            <PackageCheck size={28} aria-hidden="true" />
            <div>
              <p>药柜维护</p>
              <h3>药品信息与柜门</h3>
            </div>
          </header>

          <div className="settings-medicine-picker">
            {medicines.map((medicine) => (
              <button
                key={medicine.id}
                type="button"
                className={medicine.id === selectedMedicine?.id ? "active" : ""}
                onClick={() => setSelectedId(medicine.id)}
              >
                <strong>{medicine.hardware_slot}</strong>
                <span>{medicine.name}</span>
              </button>
            ))}
          </div>

          <div className="settings-form-grid">
            <label>
              <span>名称</span>
              <input value={form.name} onChange={(event) => updateForm("name", event.target.value)} />
            </label>
            <label>
              <span>厂家</span>
              <input value={form.manufacturer} onChange={(event) => updateForm("manufacturer", event.target.value)} />
            </label>
            <label>
              <span>库存</span>
              <input type="number" min="0" value={form.stock} onChange={(event) => updateForm("stock", event.target.value)} />
            </label>
            <label>
              <span>单位</span>
              <input value={form.unit} onChange={(event) => updateForm("unit", event.target.value)} />
            </label>
            <label>
              <span>保质期</span>
              <input value={form.expire_date} onChange={(event) => updateForm("expire_date", event.target.value)} />
            </label>
            <label>
              <span>条码</span>
              <input value={form.barcode} onChange={(event) => updateForm("barcode", event.target.value)} />
            </label>
          </div>

          <div className="settings-action-row">
            <button className="secondary-action" type="button" onClick={openSelectedCabinet} disabled={!selectedMedicine || opening}>
              <DoorOpen size={22} aria-hidden="true" />
              {opening ? "开柜中..." : "打开柜门"}
            </button>
            <button className="primary-action" type="button" onClick={saveMedicine} disabled={!selectedMedicine || saving}>
              <Save size={22} aria-hidden="true" />
              {saving ? "保存中..." : "保存信息"}
            </button>
          </div>
        </article>

        <article className="settings-card service-user-admin-card">
          <header>
            <UserRound size={28} aria-hidden="true" />
            <div>
              <p>服务对象</p>
              <h3>姓名、年龄与病症</h3>
            </div>
          </header>

          <div className="settings-user-picker">
            {serviceUsers.map((user) => (
              <button
                key={user.id}
                type="button"
                className={user.id === selectedUser?.id ? "active" : ""}
                onClick={() => setSelectedUserId(user.id)}
              >
                <strong>{user.name}</strong>
                <span>{user.age ? `${user.age}岁` : "年龄待补充"}</span>
                <small>{user.profile || "病症待补充"}</small>
              </button>
            ))}
          </div>

          <div className="settings-form-grid user-form-grid">
            <label>
              <span>姓名</span>
              <input value={userForm.name} onChange={(event) => updateUserForm("name", event.target.value)} />
            </label>
            <label>
              <span>年龄</span>
              <input
                type="number"
                min="0"
                max="120"
                value={userForm.age}
                onChange={(event) => updateUserForm("age", event.target.value)}
              />
            </label>
            <label>
              <span>身份 / 状态</span>
              <input value={userForm.status} onChange={(event) => updateUserForm("status", event.target.value)} />
            </label>
            <label>
              <span>主要病症</span>
              <input value={userForm.profile} onChange={(event) => updateUserForm("profile", event.target.value)} />
            </label>
            <label>
              <span>过敏 / 禁忌</span>
              <input value={userForm.allergies} onChange={(event) => updateUserForm("allergies", event.target.value)} />
            </label>
            <label className="wide-field">
              <span>病例备注</span>
              <textarea value={userForm.note} onChange={(event) => updateUserForm("note", event.target.value)} />
            </label>
          </div>

          <div className="settings-action-row service-user-actions">
            <button
              className="secondary-action danger-action"
              type="button"
              onClick={removeServiceUser}
              disabled={!selectedUser || deletingUser || savingUser}
            >
              <Trash2 size={22} aria-hidden="true" />
              {deletingUser ? "删除中..." : "删除对象"}
            </button>
            <button className="primary-action" type="button" onClick={saveServiceUser} disabled={!selectedUser || savingUser || deletingUser}>
              <Save size={22} aria-hidden="true" />
              {savingUser ? "保存中..." : "保存修改"}
            </button>
          </div>
        </article>

        <article className="settings-card device-admin-card">
          <header>
            <Volume2 size={28} aria-hidden="true" />
            <div>
              <p>声音设备</p>
              <h3>外放与麦克风</h3>
            </div>
          </header>

          <label className="settings-range-row">
            <span>外放音量</span>
            <input
              type="range"
              min="0"
              max="255"
              value={speakerVolume}
              onChange={(event) => setSpeakerVolume(Number(event.target.value))}
            />
            <strong>{speakerVolume}</strong>
          </label>
          <button className="settings-wide-button" type="button" onClick={testSpeaker}>
            <Volume2 size={22} aria-hidden="true" />
            外放测试
          </button>

          <label className="settings-range-row">
            <span>麦克风音量</span>
            <input
              type="range"
              min="0"
              max="100"
              value={micVolume}
              onChange={(event) => setMicVolume(Number(event.target.value))}
            />
            <strong>{micVolume}%</strong>
          </label>
          <button className="settings-wide-button subtle" type="button" onClick={applyMicVolume}>
            <Mic size={22} aria-hidden="true" />
            应用麦克风音量
          </button>
        </article>

        <article className="settings-card network-admin-card">
          <header>
            {localNetworkMode ? <WifiOff size={28} aria-hidden="true" /> : <Signal size={28} aria-hidden="true" />}
            <div>
              <p>网络状态</p>
              <h3>{localNetworkMode ? "本地化运行" : "外设 SIM 状态"}</h3>
            </div>
          </header>

          <div className="settings-network-mode">
            <button type="button" className={!localNetworkMode ? "active" : ""} onClick={() => switchNetworkMode("sim")}>
              SIM 状态
            </button>
            <button type="button" className={localNetworkMode ? "active" : ""} onClick={() => switchNetworkMode("local")}>
              本地离线
            </button>
          </div>

          <div className="settings-network-state">
            <span>当前显示</span>
            <strong>{localNetworkMode ? "本地兜底" : networkStatus?.label || "SIM网络"}</strong>
            <p>
              {localNetworkMode
                ? "本地化显示已启用，问询说明切换为本地兜底；不修改系统网络和外设链路。"
                : "读取外设 SIM 卡状态；本机仍可保持当前 Wi-Fi 或有线网络。"}
            </p>
          </div>

          <div className="settings-network-details">
            {localNetworkMode ? (
              <>
                <span>状态：本地化运行</span>
                <span>AI：本地规则兜底</span>
                <span>外部网络：未使用</span>
              </>
            ) : (
              <>
                <span>信号：{networkStatus?.signal || "--"}</span>
                <span>接口：{networkStatus?.sim_interface || "--"}</span>
                <span>地址：{networkStatus?.sim_ip || "--"}</span>
              </>
            )}
          </div>

          <button className="settings-wide-button" type="button" onClick={refreshNetwork}>
            {localNetworkMode ? "刷新本地状态" : "刷新网络状态"}
          </button>
        </article>
      </section>
    </main>
  );
}
