function parseExpiry(value) {
  const match = String(value || "").trim().match(/^(\d{4})[-./](\d{1,2})(?:[-./](\d{1,2}))?$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (!Number.isInteger(year) || month < 1 || month > 12) return null;
  if (!match[3]) return { year, month, day: null };
  const day = Number(match[3]);
  const parsed = new Date(year, month - 1, day);
  if (
    !Number.isInteger(day)
    || parsed.getFullYear() !== year
    || parsed.getMonth() !== month - 1
    || parsed.getDate() !== day
  ) return null;
  return { year, month, day };
}

export function isMedicineExpired(value, referenceDate = new Date()) {
  const expiry = parseExpiry(value);
  if (!expiry) return true;
  if (expiry.day !== null) {
    const expiresOn = new Date(expiry.year, expiry.month - 1, expiry.day);
    const today = new Date(
      referenceDate.getFullYear(),
      referenceDate.getMonth(),
      referenceDate.getDate()
    );
    return expiresOn < today;
  }
  return expiry.year < referenceDate.getFullYear()
    || (expiry.year === referenceDate.getFullYear() && expiry.month < referenceDate.getMonth() + 1);
}

export function manualDispenseBlockReason(medicine, referenceDate = new Date()) {
  if (!medicine) return "请先选择药品";
  if (medicine.package_verified === false) {
    return "包装规格待人工核验，暂不可取药";
  }
  if (medicine.guidance_source === "pending" || !parseExpiry(medicine.expire_date)) {
    return "资料待补录，暂不可取药";
  }
  if (isMedicineExpired(medicine.expire_date, referenceDate)) {
    return "药品已过有效期，暂不可取药";
  }
  if (!medicine.is_otc) {
    return "处方药请通过既往用药计划或医生审核取药";
  }
  return "";
}

export function manualDispenseButtonLabel(medicine, referenceDate = new Date()) {
  const reason = manualDispenseBlockReason(medicine, referenceDate);
  if (!reason) return "取药";
  if (medicine?.package_verified === false) return "待包装核验";
  if (medicine?.guidance_source === "pending" || !parseExpiry(medicine?.expire_date)) return "待资料补录";
  if (isMedicineExpired(medicine?.expire_date, referenceDate)) return "已过有效期";
  if (medicine?.is_otc === false) return "需审核后取药";
  return "暂不可取";
}

export function manualDispenseBlockHint(medicine, referenceDate = new Date()) {
  const reason = manualDispenseBlockReason(medicine, referenceDate);
  if (!reason) return "";
  if (medicine?.package_verified === false) return "需管理员核验实物包装规格";
  if (medicine?.guidance_source === "pending" || !parseExpiry(medicine?.expire_date)) return "需补全药品资料与有效期";
  if (isMedicineExpired(medicine?.expire_date, referenceDate)) return "药品已过期，请联系管理员";
  if (medicine?.is_otc === false) return "需既往用药计划或医生审核";
  return reason;
}
