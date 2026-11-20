import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { errorText } from "../api/errors";
import type { InvestorProfile, Jurisdiction, Portfolio, PortfolioSummary } from "../api/types";
import AppHeader from "../components/AppHeader";
import Avatar from "../components/Avatar";
import { getSummary, listPortfolios } from "../api/endpoints";
import RiskForm, { RiskResult } from "../components/RiskForm";
import { PROVINCES, loadLatestRisk, loadRisk, provinceName, QUESTIONS, qLabel, qOptions, saveRisk, syncRisk, type PortfolioRisk } from "../lib/risk";
import { levelLabel, levelName, retainedLevel, VOLATILITY_ASSUMPTION } from "../lib/riskScale";
import AssetClassPicker from "../components/AssetClassPicker";
import InfoTip from "../components/InfoTip";
import { assetClassName } from "../lib/assetClasses";
import { t, useT } from "../lib/i18n";
import IndustrySearch from "../components/IndustrySearch";
import { industryName, industryPrefs, splitPreferences, type IndustryChoice } from "../lib/industries";
import { ESG_ANSWERS, MARKETS, esgMarketPrefs, marketName, splitEsgMarket, toggleMarket, type Market } from "../lib/esgMarket";
import { useApp } from "../lib/store";
import { cad, localeDateTime, pct, plainPct, todayLong } from "../lib/format";
import CloseAccount from "../components/CloseAccount";

function RiskQuestionnaire({ userId }: { userId: string }) {
  const { lang, L } = useT();
  const [latest, setLatest] = useState<PortfolioRisk | null>(() => loadLatestRisk(userId));
  const [stored, setStored] = useState<Record<string, PortfolioRisk>>(() => loadRisk(userId));
  const [portfolios, setPortfolios] = useState<Portfolio[] | null>(null);
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listPortfolios()
      .then(({ items }) => { setPortfolios(items); setStored(syncRisk(userId, items.map((p) => p.portfolioId))); })
      .catch(() => setPortfolios([]));
  }, [userId]);

  async function submit(answers: Record<string, number>, province: Jurisdiction) {
    setMsg(""); setErr("");
    setBusy(true);
    try {
      const items = portfolios ?? (await listPortfolios()).items;
      const r = saveRisk(userId, items.map((p) => p.portfolioId), answers, province);
      setLatest(r);
      setStored(loadRisk(userId));
      setEditing(false);
      setMsg(L(`Réponses enregistrées pour ${items.length} portefeuille(s).`, `Answers saved for ${items.length} portfolio(s).`));
    } catch (x) { setErr(errorText(x)); } finally { setBusy(false); }
  }

  const name = (id: string) => portfolios?.find((p) => p.portfolioId === id)?.name ?? id;
  const shown = portfolios ? portfolios.filter((p) => stored[p.portfolioId]).map((p) => p.portfolioId) : Object.keys(stored);

  return (
    <section style={{ marginBottom: 48 }}>
      <h2 className="auth-h" style={{ fontSize: 20, marginBottom: 16 }}>{L("Questionnaire interactif", "Interactive questionnaire")}</h2>
      {msg && <div className="banner ok" style={{ marginBottom: 16 }}>{msg}</div>}

      {editing ? (
        <>
          <RiskForm initial={latest?.answers ?? {}} initialProvince={latest?.province ?? ""} submitLabel={busy ? L("Enregistrement…", "Saving…") : L("Enregistrer mes réponses", "Save my answers")} busy={busy} onSubmit={submit}>
            {err && <p className="error" role="alert">{err}</p>}
          </RiskForm>
          {latest && <button type="button" className="link" style={{ marginTop: 12 }} onClick={() => setEditing(false)}>{L("Annuler", "Cancel")}</button>}
        </>
      ) : latest ? (
        <div className="stack">
          <RiskResult answers={latest.answers} province={latest.province} />
          <table className="risk-answers">
            <thead><tr><th>Question</th><th>{L("Votre réponse", "Your answer")}</th></tr></thead>
            <tbody>
              {QUESTIONS.map((q, i) => (
                <tr key={q.id}><td>{i + 1}. {qLabel(q, lang)}</td><td>{qOptions(q, lang)[latest.answers[q.id]]}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">{L("Enregistré le", "Saved on")} {localeDateTime(latest.computedAt)}</p>
          <div>
            <h3 className="section-title" style={{ margin: "8px 0" }}>{L("Résultat par portefeuille", "Result by portfolio")}</h3>
            {shown.length ? (
              <ul className="risk-portfolios">
                {shown.map((id) => (
                  <li key={id}>
                    <span>{name(id)}</span>
                    <strong>
                      {levelName(retainedLevel(stored[id].answers.maxLoss + 1, stored[id].answers.capacity + 1), lang)}
                    </strong>
                  </li>
                ))}
              </ul>
            ) : <p className="muted small">{portfolios === null ? L("Chargement…", "Loading…") : L("Votre portefeuille est vide pour le moment.", "Your portfolio is empty for now.")}</p>}
          </div>
          <div><button type="button" className="btn" onClick={() => { setMsg(""); setEditing(true); }}>{L("Modifier mes réponses", "Edit my answers")}</button></div>
        </div>
      ) : (
        <p className="muted small">{L("Le questionnaire investisseur sera présenté lors de la création de votre portefeuille.", "The investor questionnaire will be shown when you create your portfolio.")}</p>
      )}
    </section>
  );
}

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
function Meter({ value }: { value: number | null | undefined }) {
  const { lang, L } = useT();
  return (
    <div className="meter" aria-label={value != null ? levelName(value, lang) : L("non renseigné", "not provided")}>
      {[1, 2, 3, 4, 5].map((n) => <span key={n} className={value != null && n <= value ? "on" : ""} />)}
    </div>
  );
}
function Chips({ items, tone, empty }: { items: string[]; tone?: "like" | "avoid"; empty: string }) {
  if (!items.length) return <p className="muted small">{empty}</p>;
  return <div className="chips">{items.map((x) => <span key={x} className={`chip ${tone ?? ""}`}>{x}</span>)}</div>;
}
function horizonText(p: InvestorProfile, L: (fr: string, en: string) => string) {
  if (p.horizonMaxYears != null) return p.horizonMinYears === p.horizonMaxYears ? L(`${p.horizonMinYears} ans`, `${p.horizonMinYears} years`) : L(`${p.horizonMinYears} à ${p.horizonMaxYears} ans`, `${p.horizonMinYears} to ${p.horizonMaxYears} years`);
  return L(`${p.horizonMinYears} ans et plus`, `${p.horizonMinYears} years or more`);
}
function objectiveText(objective: string, lang: "fr" | "en") {
  const goal = QUESTIONS.find((q) => q.id === "goal")!;
  const i = goal.options.indexOf(objective);
  return i >= 0 ? qOptions(goal, lang)[i] : objective;
}
function PortfolioCard() {
  const { lang, L } = useT();
  const [state, setState] = useState<{ summary: PortfolioSummary | null; name?: string; loading: boolean }>({ summary: null, loading: true });
  useEffect(() => {
    listPortfolios()
      .then(async ({ items }) => {
        const main = items[0];
        if (!main || !main.holdings.length) return setState({ summary: null, name: main?.name, loading: false });
        const summary = await getSummary(main.portfolioId, "1y");
        setState({ summary, name: main.name, loading: false });
      })
      .catch(() => setState({ summary: null, loading: false }));
  }, []);
  const s = state.summary;
  return (
    <div className="dcard span2">
      <div className="dcard-head">
        <div><div className="dcard-title">{L("Mon portefeuille", "My portfolio")}</div><div className="muted small">{state.name ?? L("Portefeuille principal", "Main portfolio")}{s ? ` · ${L("au", "as of")} ${s.asOf.slice(0, 10)}` : ""}</div></div>
        <Link to="/portefeuille" className="dcard-arrow" aria-label={L("Ouvrir le portefeuille", "Open the portfolio")}>↗</Link>
      </div>
      {state.loading ? <p className="muted small">{L("Chargement…", "Loading…")}</p> : !s ? (
        <p className="muted small">{L("Aucune position pour l'instant.", "No positions yet.")} <Link to="/portefeuille" className="link">{L("Ajouter des positions", "Add positions")}</Link></p>
      ) : (
        <div className="pf-grid">
          <div>
            <div className="dcard-value">{cad(s.totals.value, 0)}</div>
            <span className={`pill ${s.totals.pnlPct >= 0 ? "up" : "down"}`}>{pct(s.totals.pnlPct)}</span>
            <span className="muted small"> {L("depuis l'achat", "since purchase")}</span>
            <div className="pf-risk">
              <div><span className="muted small">{L("Volatilité annualisée", "Annualised volatility")}<InfoTip text={t("info.volatility", lang)} /></span><strong>{plainPct(s.risk.volatility)}</strong></div>
              <div><span className="muted small">{L("Pire baisse", "Worst drop")}<InfoTip text={t("info.drawdown", lang)} /></span><strong>{plainPct(s.risk.maxDrawdown)}</strong></div>
              <div><span className="muted small">{L("Positions", "Positions")}</span><strong>{s.holdings.length}</strong></div>
            </div>
          </div>
          <div>
            <div className="muted small" style={{ marginBottom: 6 }}>{L("Répartition par classe d'actifs", "Allocation by asset class")}</div>
            {s.allocation.byAssetClass.slice(0, 5).map((a) => (
              <div key={a.label} className="pf-bar">
                <span className="small">{assetClassName(a.label, lang)}</span>
                <div className="alloc-bar"><span style={{ width: `${Math.min(100, a.weight)}%` }} /></div>
                <span className="small muted">{a.weight.toFixed(1)} %</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <p className="muted small" style={{ marginTop: 10 }}>{L("Données passées : elles ne prédisent pas les rendements futurs.", "Past data: it does not predict future returns.")}</p>
    </div>
  );
}
export default function Profile() {
  const { user, saveProfile } = useApp();
  const { lang, L } = useT();
  const warning = (useLocation().state as { warning?: string } | null)?.warning;
  const p = user?.investorProfile;
  const [editing, setEditing] = useState(false);
  const [tolerance, setTolerance] = useState(p?.riskTolerance != null ? String(p.riskTolerance) : "");
  const [capacity, setCapacity] = useState(p?.riskCapacity != null ? String(p.riskCapacity) : "");
  const [province, setProvince] = useState<Jurisdiction | "">(p?.province ?? "");
  const [hMin, setHMin] = useState(p ? String(p.horizonMinYears) : "");
  const [hMax, setHMax] = useState(p?.horizonMaxYears != null ? String(p.horizonMaxYears) : "");
  const [objective, setObjective] = useState(p?.objective ?? "");
  const [constraints, setConstraints] = useState((p?.constraints ?? []).join("\n"));
  const initialPrefs = splitPreferences(p?.preferences);
  const initialEsgMarket = splitEsgMarket(initialPrefs.others);
  const [industries, setIndustries] = useState<IndustryChoice>({ liked: initialPrefs.liked, avoided: initialPrefs.avoided });
  const [esg, setEsg] = useState(initialEsgMarket.esg);
  const [markets, setMarkets] = useState<Market[]>(initialEsgMarket.markets);
  const [preferences, setPreferences] = useState(initialEsgMarket.others.join("\n"));
  const [excluded, setExcluded] = useState<string[]>(p?.excludedAssetClasses ?? []);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    const min = Number(hMin), max = hMax.trim() === "" ? undefined : Number(hMax);
    if (!Number.isInteger(min) || min < 0) return setErr(L("L'horizon minimum doit être un nombre entier d'années.", "The minimum horizon must be a whole number of years."));
    if (max !== undefined && (!Number.isInteger(max) || max < min)) return setErr(L("L'horizon maximum doit être un entier supérieur ou égal au minimum.", "The maximum horizon must be a whole number greater than or equal to the minimum."));
    if (!objective.trim()) return setErr(L("L'objectif est requis.", "The objective is required."));
    const tol = Number(tolerance);
    const cap = Number(capacity);
    if (!Number.isInteger(tol) || tol < 1 || tol > 5) return setErr(L("Choisissez votre tolérance à la perte.", "Choose your loss tolerance."));
    if (!Number.isInteger(cap) || cap < 1 || cap > 5) return setErr(L("Choisissez votre capacité à encaisser une perte.", "Choose your capacity to absorb a loss."));
    const body: InvestorProfile = {
      riskTolerance: tol, riskCapacity: cap,
      ...(province ? { province } : {}),
      horizonMinYears: min, ...(max !== undefined ? { horizonMaxYears: max } : {}),
      objective: objective.trim(), constraints: lines(constraints),
      preferences: [...lines(preferences), ...esgMarketPrefs({ esg, markets }), ...industryPrefs(industries)], excludedAssetClasses: excluded,
    };
    setErr(""); setBusy(true);
    try { await saveProfile(body); setSaved(true); setEditing(false); } catch (x) { setErr(errorText(x)); } finally { setBusy(false); }
  }
  const retained = p?.riskTolerance != null && p?.riskCapacity != null ? retainedLevel(p.riskTolerance, p.riskCapacity) : null;
  const prefs = splitPreferences(p?.preferences);
  const esgMarket = splitEsgMarket(prefs.others);
  const name = (user?.displayName ?? user?.username ?? "").split(" ")[0];
  const today = todayLong();
  return (
    <>
      <AppHeader />
      <main className="wrap dash">
        <div className="dash-hero">
          <div className="dash-hero-id">
            <Avatar seed={user?.userId ?? ""} size={64} label={name} />
            <div>
              <h1 className="dash-title">{L("Bon retour,", "Welcome back,")} <span className="muted-name">{name}</span></h1>
              <p className="muted">{L("Votre profil d'investisseur, tel que l'outil l'utilise pour cadrer vos simulations. Profil fictif : aucune donnée personnelle réelle.", "Your investor profile, as the tool uses it to frame your simulations. Fictitious profile: no real personal data.")}</p>
            </div>
          </div>
          <div className="dash-actions">
            <span className="date-chip">📅 {today}</span>
            {p ? (
              <button type="button" className="btn" onClick={() => { setSaved(false); setEditing((v) => !v); }}>
                {editing ? L("Fermer la modification", "Close editing") : L("Modifier mon profil", "Edit my profile")}
              </button>
            ) : (
              <Link to="/portefeuille" className="btn">{L("Créer mon portefeuille", "Create my portfolio")}</Link>
            )}
          </div>
        </div>
        {warning && !p && <div className="banner warn" style={{ marginBottom: 16 }}>{warning}</div>}
        {!p && <div className="banner" style={{ background: "var(--ghost)", marginBottom: 16 }}>{L("Profil non rempli :", "Profile not filled in:")} <Link to="/portefeuille" className="link">{L("créez votre portefeuille", "create your portfolio")}</Link> {L("pour répondre au questionnaire investisseur.", "to answer the investor questionnaire.")}</div>}
        {p && retained === null && (
          <div className="banner warn" style={{ marginBottom: 16 }}>{L("Profil ancien incomplet : la capacité à encaisser une perte manque. Complétez-la dans « Modifier mon profil ».", "Older profile is incomplete: the capacity to absorb a loss is missing. Complete it in “Edit my profile”.")}</div>
        )}
        {saved && <div className="banner ok" style={{ marginBottom: 16 }}>{L("Profil enregistré.", "Profile saved.")}</div>}

        {p && (
          <div className="dash-grid">
            <div className="dcard green">
              <div className="dcard-head">
                <div><div className="dcard-title">{L("Niveau retenu", "Retained level")}</div><div className="small" style={{ opacity: .8 }}>{L("Règle R1 : le plus bas de la tolérance et de la capacité", "Rule R1: the lower of tolerance and capacity")}</div></div>
              </div>
              <div className="green-inner">
                <div className="small" style={{ opacity: .8 }}>{L("Profil de risque", "Risk profile")}</div>
                <div className="green-value">{retained !== null ? levelName(retained, lang) : L("À compléter", "To complete")}</div>
                <div className="green-foot">
                  <span>{p.province ? `${provinceName(p.province, lang)} (${p.province})` : L("Province non renseignée", "Province not provided")}</span>
                </div>
              </div>
            </div>
            <div className="dcard">
              <div className="dcard-head"><div><div className="dcard-title">{L("Tolérance et capacité", "Tolerance and capacity")}</div><div className="muted small">{L("Du très prudent au très orienté croissance", "From very cautious to very growth-oriented")}</div></div></div>
              <div className="meter-row"><span className="small">{L("Tolérance à la perte", "Loss tolerance")}</span><strong>{p.riskTolerance != null ? levelName(p.riskTolerance, lang) : "—"}</strong></div>
              <Meter value={p.riskTolerance} />
              <p className="muted small" style={{ margin: "4px 0 12px" }}>{L("Ce que vous acceptez de subir.", "What you are willing to go through.")}</p>
              <div className="meter-row"><span className="small">{L("Capacité à encaisser", "Loss capacity")}</span><strong>{p.riskCapacity != null ? levelName(p.riskCapacity, lang) : "—"}</strong></div>
              <Meter value={p.riskCapacity} />
              <p className="muted small" style={{ marginTop: 4 }}>{L("Ce que vos finances peuvent absorber.", "What your finances can absorb.")}</p>
            </div>
            <div className="dcard">
              <div className="dcard-head"><div><div className="dcard-title">{L("Objectif et horizon", "Objective and horizon")}</div><div className="muted small">{L("Cadrent chaque session", "Frame every session")}</div></div></div>
              <div className="muted small">{L("Objectif", "Objective")}</div>
              <div className="dcard-value sm">{objectiveText(p.objective, lang)}</div>
              <div className="muted small" style={{ marginTop: 14 }}>{L("Horizon de placement", "Investment horizon")}</div>
              <div className="dcard-value sm">{horizonText(p, L)}</div>
              <p className="muted small" style={{ marginTop: 12 }}>{VOLATILITY_ASSUMPTION[lang]}</p>
            </div>

            <PortfolioCard />
            <div className="dcard">
              <div className="dcard-head"><div><div className="dcard-title">{L("Contraintes et exclusions", "Constraints and exclusions")}</div><div className="muted small">{L("Respectées par les règles", "Respected by the rules")}</div></div></div>
              <div className="muted small">{L("Contraintes", "Constraints")}</div>
              <Chips items={p.constraints ?? []} empty={L("Aucune contrainte.", "No constraints.")} />
              <div className="muted small" style={{ marginTop: 12 }}>{L("Classes d'actifs exclues", "Excluded asset classes")}</div>
              <Chips items={(p.excludedAssetClasses ?? []).map((c) => assetClassName(c, lang))} tone="avoid" empty={L("Aucune exclusion.", "No exclusions.")} />
              {esgMarket.others.length > 0 && (<><div className="muted small" style={{ marginTop: 12 }}>{L("Autres préférences", "Other preferences")}</div><Chips items={esgMarket.others} empty="" /></>)}
            </div>

            <div className="dcard">
              <div className="dcard-head"><div><div className="dcard-title">🌎 {L("ESG et marché géographique", "ESG and geographic market")}</div><div className="muted small">{L("Vos préférences d'investissement", "Your investment preferences")}</div></div></div>
              <div className="muted small">{L("Critères ESG", "ESG criteria")}</div>
              <div className="dcard-value sm">{esgMarket.esg ? L("Pris en compte (règle R8)", "Taken into account (rule R8)") : L("Non pris en compte", "Not taken into account")}</div>
              <div className="muted small" style={{ marginTop: 14 }}>{L("Marché géographique", "Geographic market")}</div>
              <Chips items={esgMarket.markets.map((m) => marketName(m, lang))} empty={L("Aucun marché choisi. Ajoutez-en dans « Modifier mon profil ».", "No market chosen. Add some in “Edit my profile”.")} />
            </div>
            <div className="dcard span-half">
              <div className="dcard-head"><div><div className="dcard-title">👍 {L("Ce que j'aime", "What I like")}</div><div className="muted small">{L("Industries qui vous intéressent", "Industries that interest you")}</div></div></div>
              <Chips items={prefs.liked.map((x) => industryName(x, lang))} tone="like" empty={L("Aucune industrie choisie. Ajoutez-en dans « Modifier mon profil ».", "No industry chosen. Add some in “Edit my profile”.")} />
            </div>
            <div className="dcard span-half">
              <div className="dcard-head"><div><div className="dcard-title">👎 {L("Ce que je préfère éviter", "What I prefer to avoid")}</div><div className="muted small">{L("Industries à écarter", "Industries to rule out")}</div></div></div>
              <Chips items={prefs.avoided.map((x) => industryName(x, lang))} tone="avoid" empty={L("Aucune industrie à éviter.", "No industry to avoid.")} />
            </div>
          </div>
        )}

        {editing && (
          <div className="dcard" style={{ marginTop: 16 }} id="modifier">
            <div className="dcard-head"><div><div className="dcard-title">{L("Modifier mon profil", "Edit my profile")}</div><div className="muted small">{L("Les changements s'appliquent aux prochaines sessions", "Changes apply to your next sessions")}</div></div></div>
            <form className="stack" onSubmit={submit} noValidate>
              <div className="row2">
                <div className="field"><label htmlFor="tol">{L("Tolérance à la perte", "Loss tolerance")}</label>
                  <select id="tol" className="input" value={tolerance} onChange={(e) => setTolerance(e.target.value)}>
                    <option value="">{L("Non renseignée", "Not provided")}</option>
                    {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{levelLabel(n, lang)}</option>)}
                  </select></div>
                <div className="field"><label htmlFor="cap">{L("Capacité à encaisser une perte", "Capacity to absorb a loss")}</label>
                  <select id="cap" className="input" value={capacity} onChange={(e) => setCapacity(e.target.value)}>
                    <option value="">{L("Non renseignée", "Not provided")}</option>
                    {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{levelLabel(n, lang)}</option>)}
                  </select></div>
              </div>
              <div className="field"><label htmlFor="prov">{L("Province ou territoire", "Province or territory")}</label>
                <select id="prov" className="input" value={province} onChange={(e) => setProvince(e.target.value as Jurisdiction | "")}>
                  <option value="">{L("Non renseignée", "Not provided")}</option>
                  {PROVINCES.map((pr) => <option key={pr.code} value={pr.code}>{lang === "en" ? pr.en : pr.label} ({pr.code})</option>)}
                </select></div>
              <div className="row2">
                <div className="field"><label htmlFor="hmin">{L("Horizon minimum (années)", "Minimum horizon (years)")}</label><input id="hmin" inputMode="numeric" value={hMin} onChange={(e) => setHMin(e.target.value)} /></div>
                <div className="field"><label htmlFor="hmax">{L("Horizon maximum (facultatif)", "Maximum horizon (optional)")}</label><input id="hmax" inputMode="numeric" value={hMax} onChange={(e) => setHMax(e.target.value)} /></div>
              </div>
              <div className="field"><label htmlFor="obj">{L("Objectif", "Objective")}</label><input id="obj" placeholder={L("ex. croissance à long terme", "e.g. long-term growth")} value={objective} onChange={(e) => setObjective(e.target.value)} /></div>
              <div className="row2">
                <div className="field"><label id="esg-label">{L("Critères ESG dans vos simulations", "ESG criteria in your simulations")}</label>
                  <div className="opts" role="radiogroup" aria-labelledby="esg-label">
                    {ESG_ANSWERS.map((o) => (
                      <label key={o.label} className={`opt${esg === o.value ? " on" : ""}`}>
                        <input type="radio" name="profile-esg" checked={esg === o.value} onChange={() => setEsg(o.value)} />{lang === "en" ? o.en : o.label}
                      </label>
                    ))}
                  </div></div>
                <div className="field"><label id="market-label">{L("Marché géographique (plusieurs choix possibles)", "Geographic market (several choices possible)")}</label>
                  <div className="opts" role="group" aria-labelledby="market-label">
                    {MARKETS.map((m) => (
                      <label key={m} className={`opt${markets.includes(m) ? " on" : ""}`}>
                        <input type="checkbox" checked={markets.includes(m)} onChange={() => setMarkets(toggleMarket(markets, m))} />{marketName(m, lang)}
                      </label>
                    ))}
                  </div></div>
              </div>
              <div className="field"><label>{L("Industries", "Industries")}</label><IndustrySearch value={industries} onChange={setIndustries} /></div>
              <div className="field"><label>{L("Classes d'actifs exclues (plusieurs choix possibles)", "Excluded asset classes (several choices possible)")}</label><AssetClassPicker value={excluded} onChange={setExcluded} /></div>
              <div className="field"><label htmlFor="con">{L("Contraintes (une par ligne)", "Constraints (one per line)")}</label><textarea id="con" rows={3} placeholder={L("ex. diversification minimale", "e.g. minimum diversification")} value={constraints} onChange={(e) => setConstraints(e.target.value)} /></div>
              <div className="field"><label htmlFor="pre">{L("Autres préférences (une par ligne)", "Other preferences (one per line)")}</label><textarea id="pre" rows={2} placeholder={L("ex. éviter la spéculation", "e.g. avoid speculation")} value={preferences} onChange={(e) => setPreferences(e.target.value)} /></div>
              {err && <p className="error" role="alert">{err}</p>}
              <div><button className="btn" disabled={busy}>{busy ? L("Enregistrement…", "Saving…") : L("Enregistrer", "Save")}</button></div>
            </form>
          </div>
        )}

        {user && <div className="dcard" style={{ marginTop: 16 }}><RiskQuestionnaire userId={user.userId} /></div>}
        <div style={{ marginBottom: 64 }}><CloseAccount /></div>
      </main>
    </>
  );
}
