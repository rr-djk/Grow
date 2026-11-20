import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, errorText } from "../api/errors";
import { createConversation, createMandate, createRun, getSummary, listPortfolios, putHoldings, searchAssets } from "../api/endpoints";
import type { Asset, Holding, Jurisdiction, MandateCreateRequest, MandateObjective, Portfolio, PortfolioSummary, Run, Slice, SummaryRange } from "../api/types";
import AppHeader from "../components/AppHeader";
import Chart from "../components/Chart";
import Explanation from "../components/Explanation";
import InfoTip from "../components/InfoTip";
import { assetClassName } from "../lib/assetClasses";
import { t as tr, useT } from "../lib/i18n";
import RiskForm from "../components/RiskForm";
import { amount, colon, localeDateTime, money, pct, plainPct, shortDate, signedAmount, toSeconds } from "../lib/format";
import { profileFromAnswers, saveRisk, type ProfileChoices } from "../lib/risk";
import { useApp } from "../lib/store";
import { TickerLabel } from "../components/TickerLogo";
import { loadPersonalAnswers } from "../lib/personalDraft";

const RANGES: { key: SummaryRange; fr: string; en: string }[] = [
  { key: "1m", fr: "1 M", en: "1M" }, { key: "6m", fr: "6 M", en: "6M" }, { key: "1y", fr: "1 A", en: "1Y" }, { key: "5y", fr: "5 A", en: "5Y" },
];
const PALETTE = ["#143D30", "#1B5E45", "#3E8F68", "#C4A15A", "#D08A62", "#8E9892", "#D5DDD8"];

type Row = { key: number; ticker: string; quantity: string; avgCost: string };
let rowKey = 0;
const toRows = (h: Holding[]): Row[] => h.map((x) => ({ key: ++rowKey, ticker: x.ticker, quantity: String(x.quantity), avgCost: String(x.avgCost) }));
const num = (s: string) => (s.trim() === "" ? NaN : Number(s.replace(",", ".")));

function parseRows(rows: Row[], L: (fr: string, en: string) => string): { holdings: Holding[] } | { error: string } {
  const seen = new Set<string>();
  const holdings: Holding[] = [];
  for (const [i, r] of rows.entries()) {
    const ticker = r.ticker.trim().toUpperCase(), quantity = num(r.quantity), avgCost = num(r.avgCost);
    const n = L(`Ligne ${i + 1}`, `Row ${i + 1}`);
    if (!ticker) return { error: L(`${n} : ticker requis.`, `${n}: ticker required.`) };
    if (seen.has(ticker)) return { error: L(`${n} : ${ticker} apparaît deux fois.`, `${n}: ${ticker} appears twice.`) };
    if (!(quantity > 0)) return { error: L(`${n} : la quantité doit être supérieure à 0.`, `${n}: quantity must be greater than 0.`) };
    if (!Number.isFinite(avgCost) || avgCost < 0) return { error: L(`${n} : prix de revient moyen invalide.`, `${n}: invalid average cost.`) };
    seen.add(ticker);
    holdings.push({ ticker, quantity, avgCost });
  }
  return { holdings };
}

const OBJECTIVES: MandateObjective[] = ["preservation", "income", "growth", "growth", "growth"];

function onboardingMandate(answers: Record<string, number>, province: Jurisdiction, choices: ProfileChoices,
  lang: string, buildAmount?: number): MandateCreateRequest {
  const profile = profileFromAnswers(answers, province, choices);
  const excluded = [...new Set(choices.industries.avoided)];
  const preferred = [...new Set(choices.industries.liked)].filter((i) => !excluded.includes(i));
  return {
    portfolioId: "main", mode: "build", province, userLanguage: lang === "en" ? "en" : "fr",
    objective: OBJECTIVES[answers.goal] ?? "growth",
    horizonYears: profile.horizonMinYears || 1,
    riskTolerance: profile.riskTolerance!, riskCapacity: profile.riskCapacity!,
    preferences: { excludedIndustries: excluded, preferredIndustries: preferred.map((industry) => ({ industry, minWeight: null })) },
    ...(buildAmount ? { buildAmount } : {}),
    fieldSources: {
      objective: "persona", horizonYears: "persona", riskTolerance: "persona", riskCapacity: "persona", preferences: "persona",
      ...(buildAmount ? { buildAmount: "user_answer" as const } : {}),
    },
  };
}

function Alloc({ title, items, classes = false }: { title: string; items: Slice[]; classes?: boolean }) {
  const { lang, L } = useT();
  const name = (label: string) => (classes ? assetClassName(label, lang) : label);
  return (
    <section>
      <h2 className="section-title">{title}</h2>
      {items.length === 0 ? <div className="empty"><strong>{L("Aucune donnée", "No data")}</strong></div> : (
        <>
          <div className="alloc-bar">{items.filter((a) => a.weight > 0).map((a, i) => <span key={a.label} style={{ width: `${a.weight}%`, background: PALETTE[i % PALETTE.length] }} title={`${name(a.label)} ${plainPct(a.weight)}`} />)}</div>
          <ul className="legend">{items.map((a, i) => <li key={a.label}><span className="dot" style={{ background: PALETTE[i % PALETTE.length] }} />{name(a.label)}<span className="pct filled">{plainPct(a.weight)}</span></li>)}</ul>
        </>
      )}
    </section>
  );
}

export default function PortfolioPage() {
  const { lang, L } = useT();
  const { user, saveProfile } = useApp();
  const [profileReady, setProfileReady] = useState(() => Boolean(user?.investorProfile));
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [range, setRange] = useState<SummaryRange>("1y");
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(() => Boolean(user?.investorProfile));
  const [onboardingBusy, setOnboardingBusy] = useState(false);
  const [onboardingError, setOnboardingError] = useState("");
  const [buildNote, setBuildNote] = useState("");
  const [building, setBuilding] = useState(false);
  const [sumLoading, setSumLoading] = useState(false);
  const [error, setError] = useState("");
  const [sumError, setSumError] = useState("");
  const [saveErr, setSaveErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [suggestions, setSuggestions] = useState<Asset[]>([]);
  const [info, setInfo] = useState<Record<string, Asset>>({});
  const searchSeq = useRef<AbortController | null>(null);
  const timer = useRef<number>();
  const sumSeq = useRef(0);

  useEffect(() => {
    if (!profileReady || portfolio) return;
    setLoading(true);
    listPortfolios()
      .then(({ items }) => {
        const p = items.find((x) => x.portfolioId === "main") ?? items[0];
        if (!p) return setError(L("Aucun portefeuille.", "No portfolio."));
        setPortfolio(p); setRows(toRows(p.holdings));
      })
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, [profileReady]);

  async function createPortfolio(
    answers: Record<string, number>,
    province: Jurisdiction,
    choices: ProfileChoices,
    buildAmount?: number,
  ) {
    if (!user) return;
    setOnboardingBusy(true); setOnboardingError("");
    try {
      await saveProfile(profileFromAnswers(answers, province, choices));
      saveRisk(user.userId, ["main"], answers, province);
    } catch (e) {
      setOnboardingError(errorText(e));
      setOnboardingBusy(false);
      return;
    }
    setBuilding(true);
    try {
      const { items } = await listPortfolios();
      let main = items.find((x) => x.portfolioId === "main") ?? items[0];
      try {
        const conv = await createConversation(L("Premier portefeuille", "First portfolio"));
        const mandate = await createMandate(conv.sessionId, onboardingMandate(answers, province, choices, lang, buildAmount));
        let run: Run;
        try {
          run = await createRun(conv.sessionId, mandate.version);
        } catch {
          run = await createRun(conv.sessionId, mandate.version);
        }
        const built = run.scenarios.find((x) => x.index === 1 && x.holdings?.length);
        const holdings = (built?.holdings ?? []).filter((h) => h.quantity && h.price)
          .map((h) => ({ ticker: h.symbol, quantity: h.quantity!, avgCost: h.price! }));
        if (!holdings.length) throw new Error(run.scenarios.length ? "no build scenario" : "empty run");
        main = await putHoldings("main", holdings);
      } catch {
        setBuildNote(L(
          "Le premier portefeuille n'a pas pu être construit. Saisissez vos positions ci-dessous ou construisez-le dans le chat.",
          "The first portfolio could not be built. Enter your positions below or build it in the chat.",
        ));
      }
      if (main) { setPortfolio(main); setRows(toRows(main.holdings)); }
      else setError(L("Aucun portefeuille.", "No portfolio."));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
      setProfileReady(true);
      setBuilding(false);
      setOnboardingBusy(false);
    }
  }

  const loadSummary = useCallback(async (p: Portfolio, r: SummaryRange) => {
    const seq = ++sumSeq.current;
    if (p.holdings.length === 0) { setSummary(null); setSumError(""); return; }
    setSumLoading(true); setSumError("");
    try {
      const s = await getSummary(p.portfolioId, r);
      if (seq === sumSeq.current) setSummary(s);
    } catch (e) {
      if (seq === sumSeq.current) { setSummary(null); setSumError(errorText(e)); }
    } finally {
      if (seq === sumSeq.current) setSumLoading(false);
    }
  }, []);

  useEffect(() => { if (portfolio) void loadSummary(portfolio, range); }, [portfolio, range, loadSummary]);

  const currencyOf = useMemo(() => {
    const m: Record<string, string> = {};
    for (const [t, a] of Object.entries(info)) if (a.currency) m[t] = a.currency;
    for (const h of summary?.holdings ?? []) m[h.ticker] = h.currency;
    return m;
  }, [info, summary]);

  function onTicker(key: number, value: string) {
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ticker: value } : r)));
    window.clearTimeout(timer.current);
    searchSeq.current?.abort();
    const q = value.trim();
    if (q.length < 1) return setSuggestions([]);
    timer.current = window.setTimeout(() => {
      const ctl = new AbortController();
      searchSeq.current = ctl;
      searchAssets(q, undefined, ctl.signal)
        .then(({ items }) => {
          setSuggestions(items);
          setInfo((m) => ({ ...m, ...Object.fromEntries(items.map((a) => [a.ticker, a])) }));
        })
        .catch(() => {});
    }, 250);
  }

  const parsed = parseRows(rows, L);
  const norm = (h: Holding[]) => JSON.stringify(h.map((x) => [x.ticker, x.quantity, x.avgCost]));
  const dirty = portfolio ? !("holdings" in parsed) || norm(parsed.holdings) !== norm(portfolio.holdings) : false;

  async function save() {
    if (!portfolio) return;
    const r = parseRows(rows, L);
    if ("error" in r) return setSaveErr(r.error);
    setSaving(true); setSaveErr("");
    try {
      const p = await putHoldings(portfolio.portfolioId, r.holdings);
      setPortfolio(p); setRows(toRows(p.holdings));
    } catch (e) {
      setSaveErr(e instanceof ApiError && e.code === "ASSET_NOT_FOUND" && e.message ? e.message : errorText(e));
    } finally {
      setSaving(false);
    }
  }

  const chart = useMemo(() => {
    const pts = summary?.performance.points ?? [];
    return pts.length > 1 ? { values: pts.map((p) => p.value), timestamps: pts.map((p) => toSeconds(p.date)) } : null;
  }, [summary]);

  if (!profileReady && building) {
    return <><AppHeader /><main className="wrap"><p className="muted" style={{ padding: "48px 0" }}>{L("Construction de votre premier portefeuille fictif…", "Building your first fictitious portfolio…")}</p></main></>;
  }
  if (!profileReady) {
    return (
      <>
        <AppHeader />
        <main className="wrap onboarding-page">
          <section className="onboarding-card" aria-labelledby="onboarding-title">
            <header className="onboarding-head">
              <div className="eyebrow onboarding-kicker">
                <span>{L("Création du portefeuille", "Portfolio creation")}</span>
                <span className="tag">{L("Étape 1", "Step 1")}</span>
              </div>
              <h1 id="onboarding-title" className="auth-h">{L("Quel investisseur êtes-vous\u00a0?", "What kind of investor are you?")}</h1>
              <p className="muted onboarding-intro">
                {L("Répondez à ces questions pour établir le profil utilisé par vos simulations. Votre premier portefeuille fictif sera ensuite construit à partir de ces réponses.", "Answer these questions to set the profile used by your simulations. Your first fictitious portfolio will then be built from these answers.")}
              </p>
            </header>
            <RiskForm
              showPreferences
              showAmount
              initial={loadPersonalAnswers() ?? {}}
              busy={onboardingBusy}
              submitLabel={onboardingBusy ? L("Création…", "Creating…") : L("Créer mon portefeuille", "Create my portfolio")}
              onSubmit={createPortfolio}
            >
              {onboardingError && <p className="error" role="alert">{onboardingError}</p>}
            </RiskForm>
          </section>
        </main>
      </>
    );
  }
  if (loading) return <><AppHeader /><main className="wrap"><p className="muted" style={{ padding: "48px 0" }}>{L("Création du portefeuille…", "Creating the portfolio…")}</p></main></>;
  if (!portfolio) return <><AppHeader /><main className="wrap"><p className="error" role="alert" style={{ padding: "48px 0" }}>{error}</p></main></>;

  const cur = summary?.baseCurrency ?? portfolio.baseCurrency;
  const t = summary?.totals;

  return (
    <>
      <AppHeader />
      <main className="wrap">
        <section className="hero">
          <div>
            <div className="eyebrow">{portfolio.name}<span className="tag">{L("Simulation seulement", "Simulation only")}</span></div>
            <div className="big filled">{t ? money(t.value) : "—"}<small>{cur}</small></div>
            {t && <div className={`sub ${t.dayChange >= 0 ? "up" : "down"}`}>{signedAmount(t.dayChange, cur)} ({pct(t.dayChangePct)}) <span>{L("jour", "day")} · {L("au", "as of")} {summary!.asOf}</span></div>}
          </div>
          <div className="controls">
            <div className="segmented" role="group" aria-label={L("Période", "Period")}>
              {RANGES.map((r) => <button key={r.key} type="button" className={r.key === range ? "on" : undefined} aria-pressed={r.key === range} onClick={() => setRange(r.key)}>{r[lang]}</button>)}
            </div>
          </div>
        </section>

        {buildNote && <div className="banner warn" role="status"><p>{buildNote}</p></div>}
        {sumError && <p className="error" role="alert" style={{ marginBottom: 16 }}>{sumError}</p>}
        {sumLoading && <p className="muted small">{L("Calcul en cours…", "Calculating…")}</p>}
        {!!summary?.warnings?.length && <div className="banner warn" role="status">{summary.warnings.map((w, i) => <p key={i}>{w}</p>)}</div>}

        {summary && (
          <>
            <section className="chart" aria-label={L("Évolution de la valeur", "Value over time")}>
              <div className="muted small" style={{ marginBottom: 4 }}>{L("Évolution de la valeur", "Value over time")}<InfoTip text={tr("info.performance", lang)} /></div>
              {chart
                ? <Chart key={range} trend={summary.totals.pnl >= 0 ? "up" : "down"} values={chart.values} timestamps={chart.timestamps} axisLabel={(ts) => shortDate(ts, range === "1y" || range === "5y")} format={(v) => amount(v, cur)} />
                : <div className="chart-empty"><p>{L("Pas assez de points pour tracer la performance.", "Not enough points to plot performance.")}</p></div>}
            </section>
            <p className="muted small chart-note">{tr("chart.adjusted", lang)}</p>
            <section className="stats">
              <div className="stat"><div className="stat-label">{L("Valeur investie (coût)", "Amount invested (cost)")}</div><div className="stat-value filled">{amount(summary.totals.cost, cur, 0)}</div></div>
              <div className="stat"><div className="stat-label">{L("Gain / perte", "Gain / loss")}</div><div className={`stat-value filled ${summary.totals.pnl >= 0 ? "up" : "down"}`}>{signedAmount(summary.totals.pnl, cur)}</div><div className="stat-sub">{pct(summary.totals.pnlPct)}</div></div>
              <div className="stat"><div className="stat-label">{L("Volatilité annualisée", "Annualised volatility")}<InfoTip text={tr("info.volatility", lang)} /></div><div className="stat-value filled">{plainPct(summary.risk.volatility, 2)}</div></div>
              <div className="stat"><div className="stat-label">{L("Baisse maximale", "Maximum drawdown")} ({summary.performance.range})<InfoTip text={tr("info.drawdown", lang)} /></div><div className="stat-value filled">{plainPct(summary.risk.maxDrawdown, 2)}</div></div>
            </section>

            <div className="grid2">
              <Alloc title={L("Classes d'actifs", "Asset classes")} items={summary.allocation.byAssetClass} classes />
              <Alloc title={L("Secteurs", "Sectors")} items={summary.allocation.bySector} />
            </div>
            <div className="grid2" style={{ paddingTop: 0 }}>
              <Alloc title={L("Devises", "Currencies")} items={summary.allocation.byCurrency} />
              <div />
            </div>

            <section style={{ padding: "8px 0 32px" }}>
              <h2 className="section-title">{L("Positions enrichies", "Positions in detail")}<InfoTip text={tr("info.portfolio", lang)} /></h2>
              <div className="table-wrap">
                <table className="tbl">
                  <thead><tr><th>{L("Titre", "Holding")}</th><th>{L("Quantité", "Quantity")}</th><th>{L("Prix", "Price")}</th><th>{L("Valeur", "Value")} ({cur})</th><th>{L("Poids", "Weight")}</th><th>{L("Gain / perte", "Gain / loss")}</th><th>{L("Jour", "Day")}</th></tr></thead>
                  <tbody>
                    {summary.holdings.map((h) => (
                      <tr key={h.ticker}>
                        <td><TickerLabel ticker={h.ticker} name={`${h.name} · ${h.assetClass}${h.sector ? ` · ${h.sector}` : ""}`} /> {h.stale && <span className="badge warn" title={L("Dernier cours connu utilisé", "Latest known price used")}>{L("cours ancien", "stale price")}</span>}</td>
                        <td>{money(h.quantity, 4).replace(/,?0+$/, "")}</td>
                        <td>{amount(h.price, h.currency)}</td>
                        <td>{money(h.value)}</td>
                        <td>{plainPct(h.weight)}</td>
                        <td className={h.pnl >= 0 ? "up" : "down"}>{signedAmount(h.pnl, cur)}<br /><span className="small">{pct(h.pnlPct)}</span></td>
                        <td className={h.dayChangePct >= 0 ? "up" : "down"}>{pct(h.dayChangePct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {summary.explanation && <div style={{ paddingBottom: 32 }}><Explanation data={summary.explanation} defaultOpen /></div>}
          </>
        )}

        <section style={{ padding: "8px 0 48px" }}>
          <div className="section-row"><h2 className="section-title">{L("Modifier mes positions", "Edit my positions")}</h2><span className="muted small">{L("Mis à jour", "Updated")}{colon()} {localeDateTime(portfolio.updatedAt)}</span></div>
          <p className="muted small" style={{ marginBottom: 12 }}>{L("Le prix de revient moyen est exprimé dans la devise de cotation de l'actif (.TO = CAD, les autres = USD). Enregistrer remplace toute la liste. Aucun ordre n'est exécuté.", "The average cost is expressed in the asset's listing currency (.TO = CAD, others = USD). Saving replaces the whole list. No order is executed.")}</p>
          <datalist id="tickers">{suggestions.map((a) => <option key={a.ticker} value={a.ticker}>{a.name}</option>)}</datalist>
          <div className="table-wrap">
            <table className="tbl edit">
              <thead><tr><th>Ticker</th><th>{L("Quantité", "Quantity")}</th><th>{L("Prix de revient moyen", "Average cost")}</th><th /></tr></thead>
              <tbody>
                {rows.map((r) => {
                  const k = r.ticker.trim().toUpperCase();
                  return (
                    <tr key={r.key}>
                      <td><input className="cell" list="tickers" aria-label="Ticker" value={r.ticker} onChange={(e) => onTicker(r.key, e.target.value)} placeholder={L("ex. RY.TO", "e.g. RY.TO")} autoComplete="off" /><span className="muted small">{info[k]?.name ?? summary?.holdings.find((h) => h.ticker === k)?.name ?? ""}</span></td>
                      <td><input className="cell" inputMode="decimal" aria-label={L("Quantité", "Quantity")} value={r.quantity} onChange={(e) => setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, quantity: e.target.value } : x)))} /></td>
                      <td><input className="cell" inputMode="decimal" aria-label={L("Prix de revient moyen", "Average cost")} value={r.avgCost} onChange={(e) => setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, avgCost: e.target.value } : x)))} /> <span className="muted small">{currencyOf[k] ?? ""}</span></td>
                      <td><button type="button" className="link" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>{L("Retirer", "Remove")}</button></td>
                    </tr>
                  );
                })}
                {rows.length === 0 && <tr><td colSpan={4} className="muted">{L("Aucune position.", "No positions.")}</td></tr>}
              </tbody>
            </table>
          </div>
          {saveErr && <p className="error" role="alert" style={{ marginTop: 12 }}>{saveErr}</p>}
          <div className="actions-row" style={{ marginTop: 16 }}>
            <button type="button" className="btn-ghost" onClick={() => setRows((rs) => [...rs, { key: ++rowKey, ticker: "", quantity: "", avgCost: "" }])}>{L("+ Ajouter une position", "+ Add a position")}</button>
            <button type="button" className="btn" disabled={!dirty || saving} onClick={() => void save()}>{saving ? L("Enregistrement…", "Saving…") : L("Enregistrer", "Save")}</button>
            {dirty && <button type="button" className="link" onClick={() => { setRows(toRows(portfolio.holdings)); setSaveErr(""); }}>{L("Annuler les changements", "Discard changes")}</button>}
          </div>
        </section>
      </main>
      <footer className="footer"><div className="wrap footer-row"><span>{L("Simulation seulement : aucune transaction n'est exécutée et rien ici ne constitue un conseil financier personnalisé. Le rendement passé ne prédit pas le futur.", "Simulation only: no transaction is executed and nothing here is personalised financial advice. Past performance does not predict the future.")}</span></div></footer>
    </>
  );
}
