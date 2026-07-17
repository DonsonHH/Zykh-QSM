import React from "react";
import {
  Activity,
  Bandage,
  BicepsFlexed,
  CircleDot,
  CupSoda,
  Droplets,
  Eye,
  GlassWater,
  Hand,
  HeartPulse,
  PackageOpen,
  Pill,
  ShieldPlus,
  Soup,
  SprayCan,
  Sparkles,
  Tablets,
  TestTube2,
  Thermometer,
  Wind
} from "lucide-react";

const efficacyTypes = [
  { pattern: /感冒发热/, icon: Thermometer, tone: "orange" },
  { pattern: /营养补充/, icon: Sparkles, tone: "teal" },
  { pattern: /抗菌药/, icon: ShieldPlus, tone: "rose" },
  { pattern: /咳嗽咽喉|咽喉口腔/, icon: Wind, tone: "cyan" },
  { pattern: /肠胃/, icon: Soup, tone: "teal" },
  { pattern: /外伤护理/, icon: Bandage, tone: "rose" },
  { pattern: /眼部护理/, icon: Eye, tone: "cyan" },
  { pattern: /外用皮肤/, icon: Hand, tone: "purple" },
  { pattern: /鼻炎过敏/, icon: Wind, tone: "purple" },
  { pattern: /外用止痛/, icon: BicepsFlexed, tone: "orange" },
  { pattern: /慢病常用/, icon: HeartPulse, tone: "blue" },
  { pattern: /扫码录入/, icon: Activity, tone: "blue" }
];

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
  return efficacyTypes.find(({ pattern }) => pattern.test(medicine?.category || ""))
    || medicineTypes.find(({ pattern }) => pattern.test(text))
    || { icon: PackageOpen, tone: "blue" };
}

export function MedicineIcon({ medicine, size = 30, className = "" }) {
  const { icon: Icon, tone } = getMedicineIconDescriptor(medicine);
  return (
    <span className={`medicine-type-icon ${tone} ${className}`.trim()} aria-hidden="true">
      <Icon size={size} strokeWidth={2.05} />
    </span>
  );
}
