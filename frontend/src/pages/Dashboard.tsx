import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorText } from "../api/errors";
import { getSummary, listPortfolios } from "../api/endpoints";
import type { Portfolio, PortfolioSummary, Slice, SummaryRange } from "../api/types";
import AppHeader from "../components/AppHeader";
import Chart from "../components/Chart";
import { TickerLabel } from "../components/TickerLogo";
import { amount, colon, money, pct, plainPct, shortDate, signedAmount, toSeconds } from "../lib/format";
import InfoTip from "../components/InfoTip";
import { assetClassName } from "../lib/assetClasses";
import { useT } from "../lib/i18n";
import { useApp } from "../lib/store";

const RANGES: { key: SummaryRange; fr: string; en: string }[] = [
  { key: "1m", fr: "1 M", en: "1M" }, { key: "6m", fr: "6 M", en: "6M" }, { key: "1y", fr: "1 A", en: "1Y" }, { key: "5y", fr: "5 A", en: "5Y" },
];
const PALETTE = ["#143D30", "#1B5E45", "#3E8F68", "#C4A15A", "#D08A62", "#6E8FA8", "#8E9892", "#D5DDD8"];
const BREAKDOWNS = [
  { key: "byAssetClass", fr: "Classes d'actifs", en: "Asset classes" },
  { key: "bySector", fr: "Secteurs", en: "Sectors" },
  { key: "byCurrency", fr: "Devises", en: "Currencies" },
] as const;
type BreakdownKey = (typeof BREAKDOWNS)[number]["key"];

function Donut({ slices, centerTitle, centerValue, classes = false }: { slices: Slice[]; centerTitle: string; centerValue: string; classes?: boolean }) {
  const { lang, L } = useT();
  const name = (label: string) => (classes ? assetClassName(label, lang) : label);
  const [hover, setHover] = useState<number | null>(null);
  const R = 70, C = 2 * Math.PI * R, GAP = 2;
  const data = slices.filter((s) => s.weight > 0);
  const total = data.reduce((s, x) => s + x.weight, 0) || 1;
  let acc = 0;
  const active = hover !== null ? data[hover] : null;
  return (
    <div className="donut">
      <svg viewBox="0 0 200 200" role="img" aria-label={L("Répartition du portefeuille", "Portfolio allocation")}>
        <circle cx="100" cy="100" r={R} fill="none" stroke="#EEF2EF" strokeWidth="26" />
        {data.map((s, i) => {
          const len = (s.weight / total) * C;
          const el = (
            <circle
              key={s.label}
              cx="100" cy="100" r={R} fill="none"
              stroke={PALETTE[i % PALETTE.length]}
              strokeWidth={hover === i ? 32 : 26}
              strokeDasharray={`${Math.max(len - GAP, 0.5)} ${C}`}
              strokeDashoffset={-acc}
              transform="rotate(-90 100 100)"
              className="donut-arc"
              opacity={hover === null || hover === i ? 1 : 0.35}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
            >
              <title>{`${name(s.label)} ${plainPct(s.weight)}`}</title>
            </circle>
          );
          acc += len;
          return el;
        })}
      </svg>
      <div className="donut-center">
        <span className="donut-label">{active ? name(active.label) : centerTitle}</span>
        <strong className="donut-value">{active ? plainPct(active.weight) : centerValue}</strong>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { user, status } = useApp();
  const { lang, L, t: tr } = useT();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [range, setRange] = useState<SummaryRange>("1y");
  const [by, setBy] = useState<BreakdownKey>("byAssetClass");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user?.investorProfile) return;
    setLoading(true);
    listPortfolios()
      .then(({ items }) => setPortfolio(items.find((p) => p.portfolioId === "main") ?? items[0] ?? null))
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, [user?.investorProfile]);

  useEffect(() => {
    if (!portfolio || portfolio.holdings.length === 0) { setSummary(null); return; }
    let live = true;
    getSummary(portfolio.portfolioId, range)
      .then((s) => { if (live) { setSummary(s); setError(""); } })
      .catch((e) => { if (live) setError(errorText(e)); });
    return () => { live = false; };
  }, [portfolio, range]);

  const chart = useMemo(() => {
    const pts = summary?.performance.points ?? [];
    return pts.length > 1 ? { values: pts.map((p) => p.value), timestamps: pts.map((p) => toSeconds(p.date)) } : null;
  }, [summary]);

  const holdings = useMemo(() => [...(summary?.holdings ?? [])].sort((a, b) => b.value - a.value), [summary]);

  if (status === "loading") return <><AppHeader /><main className="wrap"><p className="muted" style={{ padding: "48px 0" }}>{L("Chargement…", "Loading…")}</p></main></>;
  const anon = status === "anon" || !user;
  const needsProfile = !anon && !user?.investorProfile;

  const cur = summary?.baseCurrency ?? portfolio?.baseCurrency ?? "CAD";
  const t = summary?.totals;
  const name = user ? (user.displayName ?? user.username) : "";
  const best = holdings.length ? holdings.reduce((a, b) => (b.dayChangePct > a.dayChangePct ? b : a)) : null;
  const worst = holdings.length ? holdings.reduce((a, b) => (b.dayChangePct < a.dayChangePct ? b : a)) : null;

  return (
    <>
      <AppHeader />
      <main className="wrap dash2">
        <section className="dash2-hero">
          <div>
            <p className="dash2-hello">{anon ? L("Mode exploration", "Exploration mode") : `${L("Bonjour", "Hello")} ${name}`}</p>
            <h1 className="dash2-title">{L("Vue générale de votre portefeuille", "Your portfolio at a glance")}</h1>
          </div>
          <div className="dash2-actions">
            <Link to="/chat" className="btn">{L("Nouvelle session", "New session")}</Link>
            <Link to="/portefeuille" className="btn-ghost">{L("Gérer mes positions", "Manage my positions")}</Link>
          </div>
        </section>

        {anon && (
          <section className="dash2-card dash2-empty dash2-empty-tree">
            <h2>{L("Aucune donnée à afficher", "No data to show")}</h2>
            <p className="muted">{L("Explorez Grow sans compte, ou connectez-vous pour voir la vue d'ensemble de votre portefeuille.", "Explore Grow without an account, or log in to see an overview of your portfolio.")}</p>
            <Link to="/inscription" className="btn dash2-create">{L("Créez votre portefeuille !", "Create your portfolio!")}</Link>
          </section>
        )}
        {needsProfile && (
          <section className="dash2-card dash2-empty">
            <h2>{L("Créez votre portefeuille", "Create your portfolio")}</h2>
            <p className="muted">{L("Répondez au questionnaire investisseur pour afficher ici votre vue d'ensemble.", "Answer the investor questionnaire to see your overview here.")}</p>
            <Link to="/portefeuille" className="btn">{L("Commencer", "Get started")}</Link>
          </section>
        )}
        {loading && <p className="muted">{L("Chargement…", "Loading…")}</p>}
        {error && <p className="error" role="alert">{error}</p>}

        {!loading && portfolio && portfolio.holdings.length === 0 && (
          <section className="dash2-card dash2-empty">
            <h2>{L("Votre portefeuille est vide", "Your portfolio is empty")}</h2>
            <p className="muted">{L("Ajoutez vos premiers titres ou demandez à l'assistant de vous proposer un mandat.", "Add your first holdings or ask the assistant to propose a mandate.")}</p>
            <div className="dash2-actions">
              <Link to="/portefeuille" className="btn">{L("Ajouter des positions", "Add positions")}</Link>
              <Link to="/chat" className="btn-ghost">{L("Démarrer une session", "Start a session")}</Link>
            </div>
          </section>
        )}

        {summary && t && (
          <>
            <section className="dash2-kpis" aria-label={L("Indicateurs clés", "Key indicators")}>
              <div className="dash2-card dash2-kpi main">
                <span className="dash2-kpi-label">{L("Valeur totale", "Total value")}<InfoTip text={tr("info.portfolio")} /></span>
                <strong className="dash2-kpi-value">{money(t.value)} <small>{cur}</small></strong>
                <span className={`dash2-chip ${t.dayChange >= 0 ? "up" : "down"}`}>
                  {t.dayChange >= 0 ? "▲" : "▼"} {signedAmount(t.dayChange, cur)} ({pct(t.dayChangePct)}) <em>{L("aujourd'hui", "today")}</em>
                </span>
              </div>
              <div className="dash2-card dash2-kpi">
                <span className="dash2-kpi-label">{L("Gain / perte total", "Total gain / loss")}</span>
                <strong className={`dash2-kpi-value sm ${t.pnl >= 0 ? "up" : "down"}`}>{signedAmount(t.pnl, cur)}</strong>
                <span className="dash2-kpi-sub">{pct(t.pnlPct)} {L("depuis l'achat", "since purchase")}</span>
              </div>
              <div className="dash2-card dash2-kpi">
                <span className="dash2-kpi-label">{L("Volatilité annualisée", "Annualised volatility")}<InfoTip text={tr("info.volatility")} /></span>
                <strong className="dash2-kpi-value sm">{plainPct(summary.risk.volatility, 2)}</strong>
                <span className="dash2-kpi-sub">{L("Baisse maximale", "Maximum drawdown")} {plainPct(summary.risk.maxDrawdown, 2)}<InfoTip text={tr("info.drawdown")} /></span>
              </div>
              <div className="dash2-card dash2-kpi">
                <span className="dash2-kpi-label">{L("Titres détenus", "Holdings")}</span>
                <strong className="dash2-kpi-value sm">{holdings.length}</strong>
                <span className="dash2-kpi-sub">{L("Capital investi", "Amount invested")} {amount(t.cost, cur, 0)}</span>
              </div>
            </section>

            <section className="dash2-row">
              <div className="dash2-card dash2-perf">
                <div className="dash2-card-head">
                  <h2>{L("Performance", "Performance")}<InfoTip text={tr("info.performance")} /></h2>
                  <div className="segmented" role="group" aria-label={L("Période", "Period")}>
                    {RANGES.map((r) => (
                      <button key={r.key} type="button" className={r.key === range ? "on" : undefined} aria-pressed={r.key === range} onClick={() => setRange(r.key)}>{r[lang]}</button>
                    ))}
                  </div>
                </div>
                {chart
                  ? <div className="chart"><Chart key={range} trend={summary && summary.totals.pnl < 0 ? "down" : "up"} values={chart.values} timestamps={chart.timestamps} axisLabel={(ts) => shortDate(ts, range === "1y" || range === "5y")} format={(v) => amount(v, cur)} /></div>
                  : <p className="muted">{L("Pas assez de points pour tracer la performance.", "Not enough points to plot performance.")}</p>}
              </div>

              <div className="dash2-card dash2-alloc">
                <div className="dash2-card-head"><h2>{L("Répartition", "Allocation")}</h2></div>
                <div className="dash2-tabs" role="tablist" aria-label={L("Type de répartition", "Allocation type")}>
                  {BREAKDOWNS.map((b) => (
                    <button key={b.key} type="button" role="tab" aria-selected={by === b.key} className={by === b.key ? "on" : undefined} onClick={() => setBy(b.key)}>{b[lang]}</button>
                  ))}
                </div>
                <Donut key={by} slices={summary.allocation[by]} centerTitle="Total" centerValue={`${money(t.value, 0)} ${cur}`} classes={by === "byAssetClass"} />
                <ul className="dash2-legend">
                  {summary.allocation[by].map((s, i) => (
                    <li key={s.label}>
                      <span className="dot" style={{ background: PALETTE[i % PALETTE.length] }} />
                      <span className="dash2-legend-name">{by === "byAssetClass" ? assetClassName(s.label, lang) : s.label}</span>
                      <strong>{plainPct(s.weight)}</strong>
                    </li>
                  ))}
                </ul>
              </div>
            </section>

            <section aria-labelledby="titres-h">
              <div className="dash2-section-head">
                <h2 id="titres-h">{L("Mes titres", "My holdings")}</h2>
                {best && worst && holdings.length > 1 && (
                  <span className="muted small">
                    {L("Meilleur du jour", "Best of the day")}{colon()} <strong className="up">{best.ticker} {pct(best.dayChangePct)}</strong> · {L("Plus faible", "Weakest")}{colon()} <strong className="down">{worst.ticker} {pct(worst.dayChangePct)}</strong>
                  </span>
                )}
              </div>

              <div className="dash2-stack" role="img" aria-label={L("Poids de chaque titre dans le portefeuille", "Weight of each holding in the portfolio")}>
                {holdings.map((h, i) => (
                  <span key={h.ticker} style={{ width: `${h.weight}%`, background: PALETTE[i % PALETTE.length] }} title={`${h.ticker} ${plainPct(h.weight)}`} />
                ))}
              </div>

              <div className="dash2-holdings">
                {holdings.map((h, i) => (
                  <article key={h.ticker} className="dash2-card dash2-holding">
                    <header>
                      <TickerLabel ticker={h.ticker} name={h.name} size={36} />
                      <span className={`dash2-chip ${h.dayChangePct >= 0 ? "up" : "down"}`}>{pct(h.dayChangePct)}</span>
                    </header>
                    <div className="dash2-holding-value">{money(h.value)} <small>{cur}</small></div>
                    <div className="dash2-bar"><span style={{ width: `${Math.min(h.weight, 100)}%`, background: PALETTE[i % PALETTE.length] }} /></div>
                    <footer>
                      <span>{plainPct(h.weight)} {L("du portefeuille", "of the portfolio")}</span>
                      <span className={h.pnl >= 0 ? "up" : "down"}>{signedAmount(h.pnl, cur)}</span>
                    </footer>
                  </article>
                ))}
              </div>
            </section>
          </>
        )}
      </main>
      <footer className="footer"><div className="wrap footer-row"><span>{L("Simulation seulement : aucune transaction n'est exécutée et rien ici ne constitue un conseil financier personnalisé. Le rendement passé ne prédit pas le futur.", "Simulation only: no transaction is executed and nothing here is personalised financial advice. Past performance does not predict the future.")}</span></div></footer>
    </>
  );
}
