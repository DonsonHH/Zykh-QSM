export const mockDashboard = {
  ok: true,
  site: {
    station_name: "偏远社区康护站",
    service_name: "村镇智慧用药服务点"
  },
  chips: [
    { id: "network", label: "网络", value: "未连接", tone: "warn" },
    { id: "ai", label: "AI模式", value: "本地兜底", tone: "warn" },
    { id: "device", label: "设备", value: "未检查", tone: "soft" },
    { id: "sync", label: "同步", value: "未配置", tone: "warn" }
  ],
  medication: {
    pending_people: 0,
    pending_plans: 0,
    next_time: "--:--",
    featured_subject: "站点",
    featured_medicine: "等待后端数据"
  },
  inquiry: {
    title: "AI应急问询",
    description: "整理症状和禁忌信息，给出风险提示与药品信息匹配。",
    action_label: "开始问询"
  },
  quick_actions: [
    { id: "scan", title: "扫码识别", subtitle: "药盒 / 条码 / 站点码", tone: "green" },
    { id: "medicines", title: "站点药品", subtitle: "查看库存与说明", tone: "blue" },
    { id: "records", title: "服务记录", subtitle: "本地记录与同步", tone: "purple" }
  ],
  stats: [
    { id: "cabinet", label: "药柜", value: "0/23", tone: "blue" },
    { id: "temperature", label: "体温", value: "未测量", unit: "", tone: "cyan" },
    { id: "device", label: "设备", value: "未检查", tone: "soft" }
  ],
  safety_notice: "本系统仅提供应急问询、风险提示、药品信息匹配和禁忌核验。",
  updated_at: ""
};
