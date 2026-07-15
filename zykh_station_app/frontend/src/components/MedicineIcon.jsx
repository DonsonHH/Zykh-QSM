import React from "react";
import {
  Bandage,
  CircleDot,
  CupSoda,
  Droplets,
  Eye,
  GlassWater,
  PackageOpen,
  Pill,
  SprayCan,
  Tablets,
  TestTube2
} from "lucide-react";

const medicineTypes = [
  { pattern: /滴眼|眼液/, icon: Eye, tone: "cyan" },
  { pattern: /鼻喷|喷雾|西瓜霜/, icon: SprayCan, tone: "purple" },
  { pattern: /创口贴|纱布|棉签|敷料/, icon: Bandage, tone: "rose" },
  { pattern: /碘伏|消毒液/, icon: Droplets, tone: "orange" },
  { pattern: /软膏|乳膏|凝胶/, icon: TestTube2, tone: "teal" },
  { pattern: /口服液|枇杷膏|糖浆/, icon: GlassWater, tone: "orange" },
  { pattern: /颗粒/, icon: CupSoda, tone: "teal" },
  { pattern: /胶囊/, icon: Pill, tone: "purple" },
  { pattern: /丸/, icon: CircleDot, tone: "orange" },
  { pattern: /片|维元素/, icon: Tablets, tone: "blue" }
];

export function getMedicineIconDescriptor(medicine) {
  const text = `${medicine?.name || ""} ${medicine?.category || ""}`;
  return medicineTypes.find(({ pattern }) => pattern.test(text)) || { icon: PackageOpen, tone: "blue" };
}

export function MedicineIcon({ medicine, size = 30, className = "" }) {
  const { icon: Icon, tone } = getMedicineIconDescriptor(medicine);
  return (
    <span className={`medicine-type-icon ${tone} ${className}`.trim()} aria-hidden="true">
      <Icon size={size} strokeWidth={2.05} />
    </span>
  );
}
