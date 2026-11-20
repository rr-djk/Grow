import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AppHeader from "../components/AppHeader";
import PriceChart from "../components/PriceChart";
import TickerLogo from "../components/TickerLogo";
import { getAssetDetail } from "../api/endpoints";
import { errorText } from "../api/errors";
import type { AssetDetail, SummaryRange } from "../api/types";
import InfoTip from "../components/InfoTip";
import { assetClassName } from "../lib/assetClasses";
import { colon, money, pct } from "../lib/format";
import { t as tt, useT } from "../lib/i18n";
import "../markets.css";

const RANGES: { value: SummaryRange; fr: string; en: string }[] = [
  { value: "1m", fr: "1 M", en: "1M" }, { value: "6m", fr: "6 M", en: "6M" }, { value: "1y", fr: "1 A", en: "1Y" }, { value: "5y", fr: "5 A", en: "5Y" },
];
const RANGE_TEXT: Record<SummaryRange, { fr: string; en: string }> = {
  "1m": { fr: "sur 1 mois", en: "over 1 month" }, "6m": { fr: "sur 6 mois", en: "over 6 months" },
  "1y": { fr: "sur 1 an", en: "over 1 year" }, "5y": { fr: "sur 5 ans", en: "over 5 years" },
};
const SYMBOL: Record<string, string> = { CAD: "$", USD: "US$" };

export default function AssetPage() {
  const { lang, L } = useT();
  const { ticker = "" } = useParams();
  const [range, setRange] = useState<SummaryRange>("1y");
  const [data, setData] = useState<AssetDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => { setData(null); }, [ticker]);
  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true); setError("");
    getAssetDetail(ticker, range, ctrl.signal)
      .then((d) => { if (!ctrl.signal.aborted) setData(d); })
      .catch((x) => { if (!ctrl.signal.aborted) setError(errorText(x)); })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [ticker, range]);

  const cur = data?.currency ?? "";
  const price = (v: number | null | undefined) =>
    v == null ? "—" : `${money(v, Math.abs(v) < 1 ? 4 : 2)} ${SYMBOL[cur] ?? cur}`.trim();
  const rangePct = data?.rangeChangePct ?? null;
  const up = (rangePct ?? 0) >= 0;
  const hi = data?.stats.high52w ?? null, lo = data?.stats.low52w ?? null;
  const pos = data && hi != null && lo != null && hi > lo ? Math.min(100, Math.max(0, ((data.price - lo) / (hi - lo)) * 100)) : null;
  const classLabel = data ? assetClassName(data.assetClass, lang) : "";

  const facts: [string, string][] = data ? [
    [L("Marché", "Market"), data.market ?? "—"], [L("Devise", "Currency"), data.currency ?? "—"],
    [L("Secteur", "Sector"), data.sector ?? "—"], [L("Industrie", "Industry"), data.industry ?? "—"], [L("Pays", "Country"), data.country ?? "—"],
    [L("Historique depuis", "History since"), data.stats.historyStart.slice(0, 4)],
  ] : [];
  const about = data?.description
    ?? (data ? L(
      `${data.name} (${data.ticker}) est ${data.assetClass.startsWith("etf") ? "un FNB" : data.assetClass === "crypto" ? "un cryptoactif" : "une action"}${data.market ? ` cotée au ${data.market}` : ""}${data.sector ? `, secteur ${data.sector.toLowerCase()}` : ""}. Aucune description détaillée n'est disponible dans le jeu de données.`,
      `${data.name} (${data.ticker}) is ${data.assetClass.startsWith("etf") ? "an ETF" : data.assetClass === "crypto" ? "a crypto asset" : "a stock"}${data.market ? ` listed on ${data.market}` : ""}${data.sector ? `, ${data.sector.toLowerCase()} sector` : ""}. No detailed description is available in the dataset.`) : "");

  return (
    <>
      <AppHeader />
      <main className="wrap mk ap">
        <Link to="/marches" className="ap-back">← {L("Marchés", "Markets")}</Link>

        {error && !data && (
          <section className="mk-empty">
            <h2>{L("Fiche indisponible", "Details unavailable")}</h2>
            <p>{error}</p>
            <Link className="btn" to="/marches">{L("Retour aux marchés", "Back to markets")}</Link>
          </section>
        )}

        {!error && !data && <div className="ap-skel" aria-busy="true"><span className="sk-l" /><span className="sk-l" /><span className="sk-l big" /></div>}

        {data && (
          <div className="ap-grid">
            <section className="ap-main">
              <header className="ap-head">
                <TickerLogo ticker={data.ticker} size={56} />
                <div>
                  <h1>{data.name}</h1>
                  <p><span className="mono">{data.ticker}</span><span className="ap-dot" />{classLabel}{data.market ? <><span className="ap-dot" />{data.market}</> : null}</p>
                </div>
              </header>

              <div className="ap-price">
                <strong>{price(data.price)}</strong>
                {rangePct !== null && (
                  <span className={`ap-chg ${up ? "up" : "down"}`}>
                    <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true"><path d={up ? "M6 2 11 10H1z" : "M6 10 1 2h10z"} fill="currentColor" /></svg>
                    {pct(rangePct)} <em>{RANGE_TEXT[range][lang]}</em><InfoTip text={tt("info.return", lang)} />
                  </span>
                )}
              </div>
              <p className="ap-asof">{L("Dernière clôture du", "Last close on")} {data.asOf}{data.dayChangePct != null && <> · {L("jour", "day")} {pct(data.dayChangePct)}</>}</p>

              <div className={`ap-chart${loading ? " stale" : ""}`}>
                <PriceChart points={data.points} up={up} format={price} />
              </div>
              <div className="ap-ranges" role="group" aria-label={L("Période", "Period")}>
                {RANGES.map((r) => (
                  <button key={r.value} type="button" className={range === r.value ? "on" : ""} aria-pressed={range === r.value} onClick={() => setRange(r.value)}>{r[lang]}</button>
                ))}
              </div>
              {error && <p className="mk-note" role="status">{error}</p>}
            </section>

            <aside className="ap-side">
              <div className="ap-card">
                <h2>{L("À propos", "About")}</h2>
                <p className="ap-about">{about}</p>
                {data.website && <a className="ap-link" href={data.website} target="_blank" rel="noreferrer noopener">{L("Site officiel ↗", "Official website ↗")}</a>}
              </div>

              <div className="ap-card">
                <h2>{L("Repères", "Key figures")}</h2>
                {pos !== null && (
                  <div className="ap-range52">
                    <div className="ap-range52-lbl"><span>{L("Bas 52 sem.", "52-week low")}</span><span>{L("Haut 52 sem.", "52-week high")}</span></div>
                    <div className="ap-range52-bar"><i style={{ left: `${pos}%` }} /></div>
                    <div className="ap-range52-val"><strong>{price(lo)}</strong><strong>{price(hi)}</strong></div>
                  </div>
                )}
                <dl className="ap-stats">
                  <div><dt>{L("Volatilité (1 an)", "Volatility (1 year)")}<InfoTip text={tt("info.volatility", lang)} /></dt><dd>{data.stats.volatility != null ? `${money(data.stats.volatility, 1)} %` : "—"}</dd></div>
                  <div><dt>{L("Baisse maximale (1 an)", "Maximum drawdown (1 year)")}<InfoTip text={tt("info.drawdown", lang)} /></dt><dd>{data.stats.maxDrawdown != null ? `${money(data.stats.maxDrawdown, 1)} %` : "—"}</dd></div>
                  {facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
                </dl>
              </div>

              <div className="mk-cta">
                <Link className="btn" to="/portefeuille">{L("Ajouter au portefeuille", "Add to portfolio")}</Link>
                <Link className="btn-ghost" to="/chat">{L("Analyser en session", "Analyse in a session")}</Link>
              </div>
            </aside>
          </div>
        )}
      </main>
      <footer className="footer"><div className="wrap footer-row"><span>{L("Simulation pédagogique, pas un conseil financier. Les performances passées ne prédisent pas les résultats futurs.", "Educational simulation, not financial advice. Past performance does not predict future results.")}{data?.source ? ` Source${colon()} ${data.source}.` : ""}</span></div></footer>
    </>
  );
}
