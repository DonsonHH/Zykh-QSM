import React from "react";
import brandMarkUrl from "../assets/brand-mark-original.png";

export function BrandLogoImage({ size = 52, className = "", alt = "", ...props }) {
  return (
    <img
      {...props}
      className={`brand-logo-image ${className}`.trim()}
      src={brandMarkUrl}
      width={size}
      height={size}
      alt={alt}
      draggable="false"
    />
  );
}
