import { useState } from "react";
import type { Mandate, MandateCreateRequest, PortfolioSummary } from "../../api/types";
import { t, type Lang } from "../../lib/i18n";
import { cad, plainPct } from "../../lib/format";
import InfoTip from "../InfoTip";
import MandateCard from "./MandateCard";
import { TickerLabel } from "../TickerLogo";

export default function MandateColumn({
  summary, mandate, busy, lang, onWhatIf,
}: {
  summary: PortfolioSummary | null;
  mandate: Mandate | null;
  busy: boolean;
  lang: Lang;
  onWhatIf: (m: MandateCreateRequest) => void;
}) {
  const base = mandate?.mandate;
  const [horizon, setHorizon] = useState(base ? clamp(base.horizonYears) : 5);
  const [loss, setLoss] = useState(mandate ? clamp(mandate.effectiveMaxLossPct) : 20);
  const dirty =
    !!base && (Number(horizon) !== base.horizonYears || Number(loss) !== mandate!.effectiveMaxLossPct);

  function run() {
    if (!base) return;
    const m: MandateCreateRequest = {
      ...base,
      horizonYears: Number(horizon),
      maxAcceptableLossPct: Number(loss),
      fieldSources: { ...base.fieldSources, horizonYears: "slider", maxAcceptableLossPct: "slider" },
    };
    onWhatIf(m);
  }

  return (
    <aside className="chat-col">
      <div className="chat-col-scroll">
        <div className="eyebrow">{t("col.portfolio", lang)}</div>
        <p className="muted small">{t("col.portfolioSub", lang)}<InfoTip text={t("info.portfolio", lang)} /></p>
        {summary ? (
          <>
            <div className="stats" style={{ padding: 0 }}>
              <div className="stat"><div className="stat-label">{t("col.total", lang)}</div><div className="stat-value filled">{cad(summary.totals.value)}<span className="muted small"> {summary.baseCurrency}</span></div><div className="stat-sub">{summary.asOf.slice(0, 10)}</div></div>
              <div className="stat"><div className="stat-label">{t("col.pnl", lang)}</div><div className={`stat-value filled ${summary.totals.pnl >= 0 ? "up" : "down"}`}>{cad(summary.totals.pnl)}</div><div className="stat-sub">{plainPct(summary.totals.pnlPct, 2)}</div></div>
            </div>
            <table className="tbl" style={{ marginTop: 10 }}>
              <thead><tr><th>{t("col.positions", lang)}</th><th style={{ textAlign: "right" }}>{t("col.value", lang)}</th><th style={{ textAlign: "right" }}>{t("col.weight", lang)}</th></tr></thead>
              <tbody>
                {[...summary.holdings].sort((a, b) => b.weight - a.weight).map((h) => (
                  <tr key={h.ticker}>
                    <td className="small"><TickerLabel ticker={h.ticker} name={h.name} size={24} /></td>
                    <td className="small" style={{ textAlign: "right" }}>{cad(h.value)}</td>
                    <td className="small" style={{ textAlign: "right" }}>{h.weight.toFixed(1)} %</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : <p className="muted small">…</p>}

        <h2 className="section-title" style={{ marginTop: 16 }}>{t("col.mandate", lang)}</h2>
        {mandate ? (
          <MandateCard mandate={mandate.mandate} confirmed={mandate} lang={lang} />
        ) : (
          <p className="muted small">{t("col.mandateNone", lang)}</p>
        )}

        {base && (
          <>
            <div className="eyebrow" style={{ marginTop: 16 }}>{t("col.whatIf", lang)}</div>
            <p className="muted small">{t("col.whatIfHint", lang)}</p>
            <div className="field">
              <label htmlFor="wi-horizon">{t("col.sliderHorizon", lang)} : <strong>{horizon}</strong></label>
              <input id="wi-horizon" type="range" min={1} max={30} step={1} value={horizon}
                onChange={(e) => setHorizon(Number(e.target.value))} disabled={busy} />
            </div>
            <div className="field">
              <label htmlFor="wi-loss">{t("col.sliderLoss", lang)} : <strong>{loss} %</strong></label>
              <input id="wi-loss" type="range" min={5} max={40} step={1} value={loss}
                onChange={(e) => setLoss(Number(e.target.value))} disabled={busy} />
            </div>
            <button type="button" className="btn" disabled={busy || !dirty} onClick={run}>
              {busy ? t("chat.runInProgress", lang) : t("col.whatIfRun", lang)}
            </button>
          </>
        )}
      </div>
    </aside>
  );
}

const clamp = (n: number) => Math.min(40, Math.max(1, Math.round(n)));
