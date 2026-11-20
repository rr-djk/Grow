import { useId, useState } from "react";
import type { PointerEvent } from "react";
import { fullDate, shortDate } from "../lib/format";
import { useT } from "../lib/i18n";

type P = { date: string; close: number };
const W = 640, H = 240, PAD = 14;
const ts = (d: string) => Date.parse(`${d}T12:00:00Z`) / 1000;

export default function PriceChart({ points, up, format }: { points: P[]; up: boolean; format: (v: number) => string }) {
  const gid = useId();
  const { L } = useT();
  const [hover, setHover] = useState<number | null>(null);
  const n = points.length;
  if (n < 2) return <div className="pc-empty">{L("Historique insuffisant pour tracer la courbe.", "Not enough history to plot the curve.")}</div>;
  const vals = points.map((p) => p.close);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const x = (i: number) => (i / (n - 1)) * W;
  const y = (v: number) => PAD + (1 - (v - min) / span) * (H - PAD * 2);
  const line = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const color = up ? "#1F9D63" : "#D14D4D";
  const long = ts(points[n - 1].date) - ts(points[0].date) > 400 * 86400;
  const ticks = [0, 0.5, 1].map((f) => points[Math.round(f * (n - 1))].date);

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setHover(Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1)))));
  };
  const h = hover;
  return (
    <div className="pc">
      <div className="pc-plot" onPointerMove={onMove} onPointerLeave={() => setHover(null)} role="img"
        aria-label={`Courbe de prix du ${points[0].date} au ${points[n - 1].date}`}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={color} stopOpacity=".22" />
              <stop offset="1" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`${line} L${W} ${H} L0 ${H} Z`} fill={`url(#${gid})`} />
          <path d={line} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        </svg>
        {h !== null && (
          <>
            <div className="pc-cross" style={{ left: `${(h / (n - 1)) * 100}%` }} />
            <div className="pc-dot" style={{ left: `${(h / (n - 1)) * 100}%`, top: `${(y(vals[h]) / H) * 100}%`, borderColor: color }} />
            <div className="pc-tip" style={{ left: `${(h / (n - 1)) * 100}%`, transform: `translateX(${h / (n - 1) > 0.75 ? "-100%" : h / (n - 1) < 0.25 ? "0" : "-50%"})` }}>
              <strong>{format(vals[h])}</strong>
              <span>{fullDate(ts(points[h].date))}</span>
            </div>
          </>
        )}
      </div>
      <div className="pc-axis">
        {ticks.map((d, i) => <span key={i}>{shortDate(ts(d), long)}</span>)}
      </div>
    </div>
  );
}
