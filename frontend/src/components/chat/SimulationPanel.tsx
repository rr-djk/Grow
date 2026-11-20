import { useState } from "react";
import type { RuleVerdict, Run, Scenario } from "../../api/types";
import { money } from "../../lib/format";
import { t, type Lang } from "../../lib/i18n";
import { levelName } from "../../lib/riskScale";
import { scenarioRuleSummary } from "../../lib/ruleLabels";
import Provenance from "./Provenance";
import RuleItem from "./RuleItem";
import SummaryCards from "./SummaryCards";
import EvidenceText, { EvidenceBadge } from "./EvidenceText";
import CompareCategory, { CompareCategoryButton } from "./CompareCategory";
import TickerLogo from "../TickerLogo";

const SCENARIO_LABEL_KEY = ["sim.scenario.current", "sim.scenario.idea", "sim.scenario.alternative"] as const;

function ScenarioCard({ run, s, lang }: { run: Run; s: Scenario; lang: Lang }) {
  const metric = (evId?: string) => run.evidence.find((e) => e.id === evId);
  const summary = scenarioRuleSummary(run.verdicts, s.index, lang);
  return (
    <div className="scenario-card">
      <div className="scenario-head">
        <strong>{s.label}</strong>
        <span className="badge">{summary}</span>
      </div>
      <div className="muted small">{t(s.holdings?.length ? "sim.scenario.built" : SCENARIO_LABEL_KEY[s.index], lang)}</div>
      {s.description && <p className="small" style={{ marginTop: 6 }}>{s.description}</p>}
      {s.proxyNote && <p className="muted small" style={{ marginTop: 4 }}>{s.proxyNote}</p>}
      {s.holdings?.length ? <BuiltPortfolio run={run} s={s} lang={lang} /> : null}
      {s.allocation?.length && !s.holdings?.length ? (
        <>
          <div className="section-title" style={{ margin: "10px 0 4px" }}>{t("sim.allocation", lang)}</div>
          {s.allocation.map((a) => (
            <div key={a.label} className="alloc-row">
              <span className="small">{a.label}</span>
              <div className="alloc-bar"><span style={{ width: `${Math.min(100, a.weight)}%` }} /></div>
              <span className="small muted">{a.weight.toFixed(1)} %</span>
            </div>
          ))}
        </>
      ) : null}
      {s.metrics && (
        <table className="tbl" style={{ marginTop: 10 }}>
          <tbody>
            {Object.entries(s.metrics).map(([key, evId]) => {
              const ev = metric(evId);
              return (
                <tr key={key}>
                  <td className="small">{t(`sim.metric.${key}`, lang)}</td>
                  <td className="small" style={{ textAlign: "right" }}>
                    {ev?.formatted ?? <span className="muted small">{t("app.unresolved", lang)}</span>}
                  </td>
                  <td className="small" style={{ width: 56 }}><EvidenceBadge ev={ev} lang={lang} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function BuiltPortfolio({ run, s, lang }: { run: Run; s: Scenario; lang: Lang }) {
  const ev = (id?: string) => run.evidence.find((e) => e.id === id);
  const fmt = (template: string, values: Record<string, string | number | undefined>) =>
    Object.entries(values).reduce((text, [k, v]) => text.replace(`{${k}}`, String(v ?? "")), template);
  const paramText = (p: NonNullable<Scenario["parameters"]>[number]) => {
    const value = Array.isArray(p.value)
      ? (p.value as (string | { industry: string; minWeight?: number | null })[])
          .map((x) => (typeof x === "string" ? x : x.minWeight ? `${x.industry} (${t("mandate.minWeight", lang)} ${Math.round(x.minWeight * 100)} %)` : x.industry))
          .join(", ")
      : p.key === "amount" ? money(Number(p.value), 0) : p.value;
    return fmt(t(`sim.built.${p.key}`, lang), { value, riskProfile: p.riskProfile != null ? levelName(Number(p.riskProfile), lang) : undefined });
  };
  return (
    <>
      <p className="muted small" style={{ marginTop: 6 }}>{t("sim.built.notice", lang)}</p>
      <div className="section-title" style={{ margin: "10px 0 4px" }}>{t("sim.built.holdings", lang)}</div>
      <ul className="built-holdings small">
        {s.holdings!.map((h) => (
          <li key={h.symbol}>
            <TickerLogo ticker={h.symbol} size={18} /> <strong>{h.symbol}</strong> — {h.name} ({h.industry}) : {ev(h.evidence.weight)?.formatted ?? `${h.weight.toFixed(1)} %`}{" "}
            <EvidenceBadge ev={ev(h.evidence.weight)} lang={lang} />
            <span className="muted">
              {" · "}{t("sim.built.beta", lang)} {ev(h.evidence.beta)?.formatted}
              {" · "}{t("sim.built.expected", lang)} {ev(h.evidence.expectedReturn)?.formatted}
            </span>{" "}
            <EvidenceBadge ev={ev(h.evidence.expectedReturn)} lang={lang} />
          </li>
        ))}
      </ul>
      {s.parameters?.length ? (
        <>
          <div className="section-title" style={{ margin: "10px 0 4px" }}>{t("sim.built.parameters", lang)}</div>
          <ul className="built-holdings small muted">
            {s.parameters.map((p) => <li key={p.key}>{paramText(p)}{p.evidence ? <> <EvidenceBadge ev={ev(p.evidence)} lang={lang} /></> : null}</li>)}
          </ul>
        </>
      ) : null}
    </>
  );
}

function AdoptCard({ s, lang, busy, onAdopt, onLater }: { s: Scenario; lang: Lang; busy?: boolean; onAdopt: () => void; onLater: () => void }) {
  if (!s.holdings?.length || s.holdings.some((h) => !(h.quantity && h.price))) return null;
  return (
    <div className="banner" style={{ background: "var(--ghost)", marginTop: 12 }}>
      <p className="small"><strong>{t("sim.adopt.title", lang)}</strong></p>
      <p className="small muted">{t("sim.adopt.text", lang)}</p>
      <div className="questionnaire-actions" style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn" disabled={busy} onClick={onAdopt}>{busy ? t("sim.adopt.busy", lang) : t("sim.adopt.button", lang)}</button>
        <button type="button" className="btn-ghost" disabled={busy} onClick={onLater}>{t("sim.adopt.later", lang)}</button>
      </div>
    </div>
  );
}

function RuleTable({ run, lang }: { run: Run; lang: Lang }) {
  const byScenario = new Map<number, RuleVerdict[]>();
  for (const v of run.verdicts) {
    const k = v.scenario ?? -1;
    (byScenario.get(k) ?? byScenario.set(k, []).get(k)!).push(v);
  }
  const citationsOf = (v: RuleVerdict): string[] =>
    v.status === "warn" || v.status === "fail" ? (v.citations ?? []) : [];
  const groupTitle = (sc: number) => sc < 0
    ? t("sim.rules.run", lang)
    : t(sc === 1 && run.scenarios.find((x) => x.index === 1)?.holdings?.length ? "sim.scenario.built" : SCENARIO_LABEL_KEY[sc] ?? "", lang);
  return (
    <>
      <h3 className="section-title" style={{ margin: "16px 0 10px" }}>{t("sim.rules", lang)}</h3>
      {[...byScenario.entries()].map(([sc, list]) => (
        <div key={sc} className="rule-group">
          <div className="rule-group-title">{groupTitle(sc)}</div>
          <ul className="rule-list">
            {list.map((v, i) => {
              const message = v.message ?? v.messageEn ?? "";
              const cites = citationsOf(v);
              const details = message || v.threshold || cites.length ? (
                <>
                  {message && <p>{message}</p>}
                  {v.threshold && (
                    <p className="muted">{t("sim.rule.threshold", lang)} : {v.threshold.value}
                      {v.threshold.nature === "team_assumption" ? ` (${t("app.teamAssumption", lang)})` : ""}
                    </p>
                  )}
                  {cites.length > 0 && (
                    <p className="rule-cites">
                      <span className="muted">{t("sim.rule.citations", lang)} :</span>
                      {cites.map((c) => <EvidenceBadge key={c} ev={run.evidence.find((e) => e.id === c)} lang={lang} />)}
                    </p>
                  )}
                </>
              ) : null;
              return <RuleItem key={i} rule={v.rule} reasonCode={v.reasonCode} status={v.status} lang={lang}>{details}</RuleItem>;
            })}
          </ul>
        </div>
      ))}
    </>
  );
}

const SECTION_ORDER = ["data_used", "why", "limits", "what_would_change"] as const;

function NoticeCitations({ run, lang, rule, titleKey }: { run: Run; lang: Lang; rule: "R5" | "R9"; titleKey: string }) {
  const ids = run.noticeCitations?.[rule];
  if (!ids?.length) return null;
  return (
    <div style={{ marginTop: 6 }}>
      <p className="muted small" style={{ marginBottom: 4 }}>{t(titleKey, lang)}</p>
      <div className="suggest">
        {ids.map((id) => <EvidenceBadge key={id} ev={run.evidence.find((e) => e.id === id)} lang={lang} />)}
      </div>
    </div>
  );
}

function FixedNotices({ run, lang }: { run: Run; lang: Lang }) {
  return (
    <div className="notice" role="note">
      <p className="small pre">{t("app.fixedNotice.decisions", lang)}<br />
        {t("app.fixedNotice.simulation", lang)}<br />
        {t("app.fixedNotice.generic", lang)}<br />
        {(t("app.fixedNotice.universe", lang) as string).replace("{datasetVersion}", run.datasetVersion)}</p>
    </div>
  );
}

export default function SimulationPanel({ run, lang, compareCategory, horizonYears, onCompare, onRerun, onAdopt, onAdoptLater, busy }: {
  run: Run | null;
  lang: Lang;
  horizonYears?: number;
  compareCategory?: string;
  onCompare?: (req: { compareCategory?: import("../../lib/comparisonCategories").ComparisonCategoryId }) => void;
  onRerun?: () => void;
  onAdopt?: (s: Scenario) => void;
  onAdoptLater?: () => void;
  busy?: boolean;
}) {
  const narrative = run?.narrative;
  const [choosing, setChoosing] = useState(false);
  const hasComparison = !!run?.scenarios.some((s) => s.index === 2);
  return (
    <aside className="sim-panel" aria-label={t("sim.title", lang)}>
      <div className="sim-scroll">
        <div className="banner" style={{ background: "var(--ghost)" }}>
          <p className="small"><strong>{t("app.disclaimer", lang)}</strong></p>
        </div>
        {run?.jurisdictionNotices?.length ? (
          <div className="banner warn">
            <p className="small">{run.jurisdictionNotices.map((n, i) => <span key={i} className="pre">{n}<br /></span>)}</p>
            <NoticeCitations run={run} lang={lang} rule="R9" titleKey="sim.notice.fixedR9" />
          </div>
        ) : null}

        {!run && <p className="muted">{t("sim.empty", lang)}</p>}

        {run?.status === "error" && <div className="banner warn"><p>{t("chat.runError", lang)}</p></div>}

        {run && run.status !== "error" && (
          <>
            {(run.rulesVersion ?? 0) < 2 && (
              <div className="banner warn">
                <p className="small">{t("sim.oldRun", lang)}</p>
                {onRerun && <button type="button" className="btn-ghost" disabled={busy} onClick={onRerun}>{t("sim.rerun", lang)}</button>}
              </div>
            )}
            <SummaryCards run={run} lang={lang} horizonYears={horizonYears} />
            <h2 className="section-title" style={{ marginTop: 12 }}>{t("sim.scenarios", lang)}</h2>
            <div className={`scenario-grid${run.scenarios.length < 3 ? " two" : ""}`}>
              {run.scenarios.map((s) => <ScenarioCard key={s.index} run={run} s={s} lang={lang} />)}
            </div>
            {onAdopt && (() => {
              const built = run.scenarios.find((x) => x.index === 1 && x.holdings?.length);
              return built ? <AdoptCard s={built} lang={lang} busy={busy} onAdopt={() => onAdopt(built)} onLater={() => onAdoptLater?.()} /> : null;
            })()}
            {run.status === "partial" && <p className="muted small">{t("sim.partialHint", lang)}</p>}
            <FixedNotices run={run} lang={lang} />
            <NoticeCitations run={run} lang={lang} rule="R5" titleKey="sim.notice.fixedR5" />
            {onCompare && (
              <CompareCategoryButton lang={lang} busy={busy} onOpen={() => setChoosing(true)} />
            )}
            {onCompare && choosing && (
              <CompareCategory
                lang={lang}
                currentId={compareCategory as import("../../lib/comparisonCategories").ComparisonCategoryId | undefined}
                onClose={() => setChoosing(false)}
                onChoose={(id) => { setChoosing(false); onCompare({ compareCategory: id }); }}
                onRemove={() => { setChoosing(false); onCompare({}); }}
              />
            )}

            {run.verdicts.length > 0 && <RuleTable run={run} lang={lang} />}

            {narrative && (
              <>
                <h3 className="section-title">{t("sim.narrative", lang)}</h3>
                {narrative.sections
                  .slice()
                  .sort((a, b) => SECTION_ORDER.indexOf(a.key) - SECTION_ORDER.indexOf(b.key))
                  .map((sec) => (
                    <section key={sec.key}>
                      <div className="section-title" style={{ margin: "10px 0 4px" }}>{t(`sim.section.${sec.key}`, lang)}</div>
                      <p className="small pre">
                        <EvidenceText text={sec.text} evidence={run.evidence} lang={lang} />
                      </p>
                    </section>
                  ))}
                {narrative.hiddenSentences?.length ? (
                  <p className="muted small">
                    {narrative.hiddenSentences.length} phrase(s) masquée(s) par le vérificateur
                    {narrative.hiddenSentences.map((h, i) => <span key={i}> · {h.reason}</span>)}
                  </p>
                ) : null}
              </>
            )}

            {run.verifier && (
              <>
                <h3 className="section-title">{t("sim.verifier", lang)}</h3>
                <div className="stats" style={{ padding: 0 }}>
                  <div className="stat"><div className="stat-label">{t("sim.verifier.placeholders", lang)}</div><div className="stat-value filled" style={{ fontSize: 20 }}>{run.verifier.placeholdersResolved}/{run.verifier.placeholdersTotal}</div></div>
                  <div className="stat"><div className="stat-label">{t("sim.verifier.handwritten", lang)}</div><div className="stat-value filled" style={{ fontSize: 20 }}>{run.verifier.handwrittenNumbers}</div></div>
                  <div className="stat"><div className="stat-label">{t("sim.verifier.forbidden", lang)}</div><div className="stat-value filled" style={{ fontSize: 20 }}>{run.verifier.forbiddenPhrases}</div></div>
                  <div className="stat"><div className="stat-label">{t("sim.verifier.match", lang)}</div><div className="stat-value filled" style={{ fontSize: 20 }}>{run.verifier.placeholdersMatch ? "✓" : "✕"}</div></div>
                </div>
              </>
            )}

            <Provenance run={run} lang={lang} />
          </>
        )}
      </div>
    </aside>
  );
}
