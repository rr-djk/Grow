import { useState } from "react";
import DOMAINS from "../lib/logoDomains.json";
const map = DOMAINS as Record<string, string>;
const PALETTE = ["#1B5E45", "#2F6F8F", "#7A5C2E", "#6B4E8A", "#8A3F3A", "#3E6B3A"];
export const logoDomain = (ticker: string) => map[ticker.toUpperCase()];
function initials(ticker: string) {
  return ticker.replace(/\.(TO|V)$|-USD$/i, "").replace(/[^A-Za-z0-9]/g, "").slice(0, 3).toUpperCase() || "?";
}
export default function TickerLogo({ ticker, size = 28 }: { ticker: string; size?: number }) {
  const domain = logoDomain(ticker);
  const [failed, setFailed] = useState(false);
  const style = { width: size, height: size, borderRadius: Math.round(size * 0.3) };
  if (!domain || failed) {
    const color = PALETTE[[...ticker].reduce((s, c) => s + c.charCodeAt(0), 0) % PALETTE.length];
    return (
      <span className="ticker-logo mono" style={{ ...style, background: color, fontSize: Math.round(size * 0.34) }} aria-hidden="true">
        {initials(ticker)}
      </span>
    );
  }
  return (
    <span className="ticker-logo" style={style} aria-hidden="true">
      <img src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`} alt="" loading="lazy"
        width={Math.round(size * 0.7)} height={Math.round(size * 0.7)} onError={() => setFailed(true)} referrerPolicy="no-referrer" />
    </span>
  );
}
export function TickerLabel({ ticker, name, size }: { ticker: string; name?: string | null; size?: number }) {
  return (
    <span className="ticker-label">
      <TickerLogo ticker={ticker} size={size} />
      <span className="ticker-text"><strong>{ticker}</strong>{name ? <span className="muted small">{name}</span> : null}</span>
    </span>
  );
}
