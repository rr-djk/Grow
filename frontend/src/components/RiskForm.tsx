import { useState, type FormEvent, type ReactNode } from "react";
import { isComplete, PROVINCES, QUESTIONS, qLabel, qOptions, type ProfileChoices } from "../lib/risk";
import { colon, money } from "../lib/format";
import { useT } from "../lib/i18n";
import { levelName, levelText, retainedLevel, VOLATILITY_ASSUMPTION } from "../lib/riskScale";
import type { Jurisdiction } from "../api/types";
import IndustrySearch from "./IndustrySearch";
import { EMPTY_INDUSTRIES, type IndustryChoice } from "../lib/industries";
import { ESG_ANSWERS, MARKETS, marketName, toggleMarket, type Market } from "../lib/esgMarket";

type Answers = Record<string, number>;

export const AMOUNT_CHOICES = [10_000, 25_000, 50_000, 100_000] as const;
const MIN_AMOUNT = 1_000, MAX_AMOUNT = 10_000_000;

export default function RiskForm({
  initial = {}, initialProvince = "", showPreferences = false, showAmount = false, submitLabel, busy = false, onSubmit, children,
}: {
  initial?: Answers; initialProvince?: string; showPreferences?: boolean; showAmount?: boolean; submitLabel: string; busy?: boolean;
  onSubmit: (a: Answers, province: Jurisdiction, choices: ProfileChoices, buildAmount?: number) => void; children?: ReactNode;
}) {
  const { lang, L } = useT();
  const [answers, setAnswers] = useState<Answers>(initial);
  const [province, setProvince] = useState(initialProvince);
  const [esg, setEsg] = useState<boolean | undefined>(undefined);
  const [markets, setMarkets] = useState<Market[]>([]);
  const [industries, setIndustries] = useState<IndustryChoice>(EMPTY_INDUSTRIES);
  const [tried, setTried] = useState(false);
  const [amountText, setAmountText] = useState(String(AMOUNT_CHOICES[2]));
  const buildAmount = Number(amountText.replace(/[\s\u00a0,]/g, ""));
  const badAmount = showAmount && !(Number.isFinite(buildAmount) && buildAmount >= MIN_AMOUNT && buildAmount <= MAX_AMOUNT);
  const missingProvince = !PROVINCES.some((p) => p.code === province);
  const missingEsg = showPreferences && esg === undefined;
  const missingMarket = showPreferences && markets.length === 0;
  const required = [
    ...QUESTIONS.map((q) => answers[q.id] !== undefined),
    !missingProvince,
    ...(showPreferences ? [!missingEsg, !missingMarket] : []),
  ];
  const done = required.filter(Boolean).length;

  function submit(e: FormEvent) {
    e.preventDefault();
    setTried(true);
    if (isComplete(answers) && !missingProvince && !missingEsg && !missingMarket && !badAmount)
      onSubmit(answers, province as Jurisdiction, { esg: esg === true, markets, industries }, showAmount ? buildAmount : undefined);
  }

  return (
    <form className="questionnaire" onSubmit={submit} noValidate>
      <div className="q-progress" aria-live="polite">
        <div className="alloc-bar" style={{ margin: 0, flex: 1, height: 6 }}><span style={{ width: `${(done / required.length) * 100}%`, background: "var(--red)" }} /></div>
        <span className="muted small">{done} / {required.length}</span>
      </div>
      {QUESTIONS.map((q, i) => (
        <fieldset key={q.id} className={`q risk-question${tried && answers[q.id] === undefined ? " missing" : ""}`}>
          <legend>{i + 1}. {qLabel(q, lang)}</legend>
          <div className="opts">
            {qOptions(q, lang).map((o, j) => (
              <label key={o} className={`opt${answers[q.id] === j ? " on" : ""}`}>
                <input type="radio" name={q.id} checked={answers[q.id] === j} onChange={() => setAnswers({ ...answers, [q.id]: j })} />
                {o}
              </label>
            ))}
          </div>
        </fieldset>
      ))}
      <fieldset className={`q province-question${tried && missingProvince ? " missing" : ""}`}>
        <legend>{QUESTIONS.length + 1}. {L("Province ou territoire de résidence", "Province or territory of residence")}</legend>
        <div className="field province-field">
          <select className="input" value={province} onChange={(e) => setProvince(e.target.value)} aria-label={L("Province ou territoire", "Province or territory")}>
            <option value="">{L("Sélectionner…", "Select…")}</option>
            {PROVINCES.map((p) => <option key={p.code} value={p.code}>{lang === "en" ? p.en : p.label} ({p.code})</option>)}
          </select>
        </div>
        <p className="muted small" style={{ margin: "6px 0 0" }}>{L("Sert à afficher les mentions propres à votre province. Aucune autre donnée personnelle n'est requise.", "Used to show the notices specific to your province. No other personal data is required.")}</p>
      </fieldset>
      {showPreferences && (
        <>
          <fieldset className={`q choice-question${tried && missingEsg ? " missing" : ""}`}>
            <legend>{QUESTIONS.length + 2}. {L("Critères ESG (environnementaux, sociaux et de gouvernance) : voulez-vous en tenir compte dans vos simulations ?", "ESG criteria (environmental, social and governance): do you want your simulations to take them into account?")}</legend>
            <div className="opts">
              {ESG_ANSWERS.map((o) => (
                <label key={o.label} className={`opt${esg === o.value ? " on" : ""}`}>
                  <input type="radio" name="esg" checked={esg === o.value} onChange={() => setEsg(o.value)} />
                  {lang === "en" ? o.en : o.label}
                </label>
              ))}
            </div>
            <p className="muted small" style={{ margin: "10px 0 0" }}>{L("Si oui, la règle R8 signale dans vos simulations les titres sans méthode ESG publiée par l'émetteur. L'outil n'attribue aucune note ESG.", "If yes, rule R8 flags in your simulations the securities whose issuer has published no ESG methodology. The tool assigns no ESG rating.")}</p>
          </fieldset>
          <fieldset className={`q choice-question${tried && missingMarket ? " missing" : ""}`}>
            <legend>{QUESTIONS.length + 3}. {L("Marché géographique : où voulez-vous investir ? (plusieurs choix possibles)", "Geographic market: where do you want to invest? (several choices possible)")}</legend>
            <div className="opts">
              {MARKETS.map((m) => (
                <label key={m} className={`opt${markets.includes(m) ? " on" : ""}`}>
                  <input type="checkbox" checked={markets.includes(m)} onChange={() => setMarkets(toggleMarket(markets, m))} />
                  {marketName(m, lang)}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="q preference-question">
            <legend>{QUESTIONS.length + 4}. {L("Industries : ce que vous aimez et ce que vous préférez éviter (facultatif, plusieurs choix possibles)", "Industries: what you like and what you prefer to avoid (optional, several choices possible)")}</legend>
            <IndustrySearch value={industries} onChange={setIndustries} />
          </fieldset>
        </>
      )}
      {showAmount && (
        <fieldset className={`q amount-question${tried && badAmount ? " missing" : ""}`}>
          <legend>{QUESTIONS.length + (showPreferences ? 5 : 2)}. {L("Montant fictif de départ (en $ CA)", "Fictitious starting amount (CAD)")}</legend>
          <div className="opts">
            {AMOUNT_CHOICES.map((a) => (
              <label key={a} className={`opt${buildAmount === a ? " on" : ""}`}>
                <input type="radio" name="buildAmount" checked={buildAmount === a} onChange={() => setAmountText(String(a))} />
                {money(a, 0)}
              </label>
            ))}
          </div>
          <div className="field" style={{ marginTop: 8 }}>
            <input className="input" inputMode="numeric" value={amountText} onChange={(e) => setAmountText(e.target.value)} aria-label={L("Montant fictif de départ", "Fictitious starting amount")} />
          </div>
          <p className="muted small" style={{ margin: "6px 0 0" }}>{L("Argent fictif : sert à proposer un premier portefeuille simulé dans le chat. Rien n'est acheté.", "Fictitious money: used to propose a first simulated portfolio in the chat. Nothing is bought.")}</p>
        </fieldset>
      )}
      {tried && (!isComplete(answers) || missingProvince || missingEsg || missingMarket) && <p className="error" role="alert">{L("Répondez à toutes les questions, y compris la province.", "Answer every question, including the province.")}</p>}
      {children}
      <div className="questionnaire-actions"><button className="btn" disabled={busy}>{submitLabel}</button></div>
    </form>
  );
}

export function RiskResult({ answers, province }: { answers: Answers; province?: string }) {
  const { lang, L } = useT();
  const tolerance = answers.maxLoss + 1, capacity = answers.capacity + 1;
  const retained = retainedLevel(tolerance, capacity);
  return (
    <div className="profile-card">
      <div className="eyebrow">{L("Tolérance et capacité de perte", "Loss tolerance and capacity")}</div>
      <div className="profile-top">
        <div className="big filled" style={{ fontSize: 40 }}>{levelName(retained, lang)}</div>
      </div>
      <p className="desc" style={{ WebkitLineClamp: "unset" }}>
        {levelText(retained, lang)}
        <br />
        {L("Tolérance à la perte", "Loss tolerance")}{colon()} <strong>{levelName(tolerance, lang)}</strong> · {L("Capacité à encaisser", "Loss capacity")}{colon()} <strong>{levelName(capacity, lang)}</strong>
        {province ? <> · {L("Province", "Province")}{colon()} <strong>{province}</strong></> : null}
        <br />{L("Niveau retenu (R1) : le plus bas des deux.", "Retained level (R1): the lower of the two.")}
        <br /><span className="muted small">{VOLATILITY_ASSUMPTION[lang]}</span>
      </p>
    </div>
  );
}
