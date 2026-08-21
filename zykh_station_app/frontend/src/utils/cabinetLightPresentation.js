export function describeMedicineCabinet(medicine, fallback = "对应分类柜") {
  const cabinetId = Number(medicine?.cabinet_id);
  const cabinetLabel = String(medicine?.cabinet_label || "").trim();
  if (Number.isInteger(cabinetId) && cabinetId >= 1 && cabinetId <= 3) {
    return `${cabinetId}号柜${cabinetLabel ? ` · ${cabinetLabel}` : ""}`;
  }
  return cabinetLabel ? `${cabinetLabel}分类柜` : fallback;
}

export function normalizeCabinetLightMessage(message) {
  return String(message || "")
    .replace(/([1-3])\s*号分类柜/g, "$1号柜")
    .replace(/柜门已打开，请取出药品并关闭柜门。?/g, "分类柜指示灯已亮，请自行打开亮灯的分类柜取药。")
    .replace(/正在打开柜门/g, "正在点亮分类柜指示灯")
    .replace(/柜门未能打开/g, "分类柜指示灯未能点亮")
    .replace(/本次柜门未打开/g, "本次分类柜指示灯未亮")
    .replace(/柜门未打开/g, "分类柜指示灯未亮")
    .replace(/开柜未完成/g, "分类柜亮灯未完成")
    .replace(/开柜服务/g, "分类柜亮灯服务")
    .replace(/开柜结果/g, "分类柜亮灯结果")
    .replace(/开柜失败/g, "分类柜亮灯失败")
    .replace(/柜门结果/g, "亮灯结果")
    .replace(/柜门状态/g, "指示灯状态")
    .replace(/柜门已打开/g, "分类柜指示灯已亮")
    .replace(/成功开柜/g, "成功点亮分类柜指示灯")
    .replace(/对应药柜已处理/g, "对应分类柜亮灯引导已处理")
    .replace(/依次打开对应药柜/g, "依次点亮对应分类柜指示灯")
    .replace(/打开对应药柜/g, "点亮对应分类柜指示灯");
}
