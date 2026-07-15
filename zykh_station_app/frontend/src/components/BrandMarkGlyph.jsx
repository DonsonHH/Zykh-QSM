import React, { useId } from "react";

export function BrandMarkGlyph({ size = 48, strokeWidth = 2.4, ...props }) {
  const id = useId().replace(/:/g, "");
  const mainGradient = `brand-main-${id}`;
  const blueGradient = `brand-blue-${id}`;
  const greenGradient = `brand-green-${id}`;
  const detailStroke = Math.max(2.6, Number(strokeWidth) || 2.4);

  return (
    <svg
      {...props}
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={mainGradient} x1="8" y1="18" x2="89" y2="91" gradientUnits="userSpaceOnUse">
          <stop stopColor="#1b80e9" />
          <stop offset="0.5" stopColor="#159ed0" />
          <stop offset="1" stopColor="#20b974" />
        </linearGradient>
        <linearGradient id={blueGradient} x1="37" y1="22" x2="65" y2="77" gradientUnits="userSpaceOnUse">
          <stop stopColor="#2589e7" />
          <stop offset="1" stopColor="#12a2c8" />
        </linearGradient>
        <linearGradient id={greenGradient} x1="46" y1="47" x2="91" y2="93" gradientUnits="userSpaceOnUse">
          <stop stopColor="#14a89a" />
          <stop offset="1" stopColor="#21bb70" />
        </linearGradient>
      </defs>

      <path
        d="M8.5 25.2 49.3 3.4c.8-.5 1.8-.5 2.7 0l19.5 10.4V9.3c0-.7.6-1.3 1.3-1.3h6.6c.7 0 1.3.6 1.3 1.3v9.5l16.8 9c.8.4 1.3 1.3 1.3 2.2v1.5c0 .7-.6 1.3-1.3 1.3h-6.2c-1.4 0-2.8-.4-4-1.1L51.2 12.4c-.5-.3-1.1-.3-1.6 0L15.8 30.5v18.3c0 7.3 1.8 14.4 5.2 20.8h-8.3C9.4 63 7.8 56 7.8 48.7V27.1c0-.8.2-1.4.7-1.9Z"
        fill={`url(#${mainGradient})`}
        stroke={`url(#${mainGradient})`}
        strokeWidth="0.55"
        strokeLinejoin="round"
      />
      <path
        d="M88.3 35.7h7.2v17.8c0 9.2-2.8 17.6-8.8 25.5l-10.8 7c8.1-10.2 12.4-20.9 12.4-32.4Z"
        fill={`url(#${greenGradient})`}
        stroke={`url(#${greenGradient})`}
        strokeWidth="0.5"
        strokeLinejoin="round"
      />
      <path
        d="M17.2 81.7h10.2l23.1 13.4c15.8-3.8 31.3-12.9 41.8-27.4 2-2.8 2.7-5.5.8-6.2-1.7-.6-3.5 2.4-5.8 4.8-4.6 4.8-9.8 8.5-15.7 11.3l9.3-10.1c1.8-2 1.1-4.8-.9-5.3-1.4-.4-2.8.8-4.3 2.1L64.6 73c-6.1 4.7-10.6 10.2-14.3 16.5L28.8 76.8h-5.2Z"
        fill={`url(#${mainGradient})`}
        stroke={`url(#${mainGradient})`}
        strokeWidth="0.6"
        strokeLinejoin="round"
      />
      <path
        d="M50.7 20.5c-8.2 0-14.2 6.4-14.2 15v27.3c0 8.8 6.1 15.4 14.4 15.4s14.2-6.6 14.2-15.4V35.5c0-8.6-6.1-15-14.4-15Z"
        fill={`url(#${blueGradient})`}
        stroke={`url(#${blueGradient})`}
        strokeWidth="0.6"
        strokeLinejoin="round"
      />
      <path d="M43.6 47.8H58v15c0 4.8-3 8.4-7.2 8.4s-7.2-3.5-7.2-8.3Z" fill="#fff" />
      <path
        d="M42.7 38.8v-5.5c0-4.5 2.4-7.9 6.6-9.6"
        stroke="#fff"
        strokeWidth="3.5"
        strokeLinecap="round"
        opacity="0.95"
      />
      <path
        d="M59.1 79.2C51.5 73.8 42.5 67 42.5 57.6c0-6.8 4.7-11.6 10.8-11.6 3.8 0 7 2.1 9.6 6.4 2.5-4.3 5.8-6.4 9.8-6.4 6.2 0 10.9 4.8 10.9 11.6 0 9.1-9.4 16-21 24Z"
        fill={`url(#${greenGradient})`}
        stroke="#fff"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path
        d="M44.4 62.8h9.2l2.3-6.1 4.1 13.6 3.1-10.1 2.5 5h10.5"
        stroke="#fff"
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g stroke={`url(#${mainGradient})`} strokeWidth={detailStroke} strokeLinecap="round" strokeLinejoin="round">
        <path d="M7.4 74h3.2l3.3-3.4h14.2" />
        <path d="M16.3 78.8h16.5" />
        <circle cx="7.4" cy="74" r="3.8" fill="#fff" />
        <circle cx="31.8" cy="70.6" r="3.8" fill="#fff" />
        <circle cx="36.6" cy="78.8" r="3.8" fill="#fff" />
      </g>
      <g stroke={`url(#${greenGradient})`} strokeWidth={detailStroke + 0.7} strokeLinecap="round">
        <path d="M85.4 7.8c7.2 0 13 5.8 13 13" />
        <path d="M85.6 13.9c3.7 0 6.8 3 6.8 6.8" />
        <path d="M85.8 20c.8 0 1.4.6 1.4 1.4" />
      </g>
    </svg>
  );
}
