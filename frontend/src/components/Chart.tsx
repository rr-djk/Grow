import { useId, useState } from "react";
import { fullDate, fullDateTime } from "../lib/format";

export default function Chart({
  values,
  timestamps,
  format,
  axisLabel,
  dim = false,
  intraday = false,
  baseline,
  trend,
}: {
  values: number[];
  timestamps: number[];
  format: (v: number) => string;
  axisLabel: (ts: number) => string;
  dim?: boolean;
  intraday?: boolean;
  baseline?: number | null;
  trend?: "up" | "down";
}) {
  const [hover, setHover] = useState<number | null>(null);
  const all = baseline != null ? [...values, baseline] : values;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const pad = (max - min) * 0.15 || 1;
  const lo = min - pad;
  const hi = max + pad;
  const n = values.length;
  const xp = (i: number) => (n > 1 ? (i / (n - 1)) * 100 : 50);
  const yp = (v: number) => 100 - ((v - lo) / (hi - lo)) * 100;
  const line = values.map((v, i) => `${i ? "L" : "M"}${(xp(i) * 10).toFixed(1)} ${(yp(v) * 3).toFixed(1)}`).join(" ");
  const ref = baseline ?? values[0];
  const up = trend ? trend === "up" : values[n - 1] >= ref;
  const color = up ? "#1F7A4D" : "#B4433A";
  const gradientId = `area-${useId().replace(/:/g, "")}`;
  const labels = [0, 0.33, 0.66, 1].map((f) => timestamps[Math.round(f * (n - 1))]);

  return (
    <>
      <div
        className={`plot${dim ? " dim" : ""}`}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const i = Math.round(((e.clientX - rect.left) / rect.width) * (n - 1));
          setHover(Math.max(0, Math.min(n - 1, i)));
        }}
        onMouseLeave={() => setHover(null)}
      >
        <svg viewBox="0 0 1000 300" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={color} stopOpacity=".12" />
              <stop offset="1" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`${line} L1000 300 L0 300 Z`} fill={`url(#${gradientId})`} />
          {baseline != null && (
            <line x1="0" x2="1000" y1={yp(baseline) * 3} y2={yp(baseline) * 3} stroke="#c4c8cf" strokeDasharray="4 6" vectorEffect="non-scaling-stroke" />
          )}
          <path d={line} fill="none" stroke={color} strokeWidth="2.25" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>
        {hover !== null && (
          <>
            <div className="crosshair" style={{ left: `${xp(hover)}%` }} />
            <div className="point" style={{ left: `${xp(hover)}%`, top: `${yp(values[hover])}%`, background: color }} />
            <div
              className="tooltip"
              style={{ left: `${xp(hover)}%`, transform: `translateX(${xp(hover) > 75 ? "-100%" : xp(hover) < 25 ? "0" : "-50%"})` }}
            >
              <strong>{format(values[hover])}</strong>
              <span>{intraday ? fullDateTime(timestamps[hover]) : fullDate(timestamps[hover])}</span>
            </div>
          </>
        )}
      </div>
      <div className="axis">
        {labels.map((t, i) => (
          <span key={i}>{axisLabel(t)}</span>
        ))}
      </div>
    </>
  );
}
