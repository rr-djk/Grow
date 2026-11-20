import type { RuleVerdict, Run } from "../../api/types";
import { t, type Lang } from "../../lib/i18n";
import { ruleBadgeClass, ruleLabel } from "../../lib/ruleLabels";
import { EvidenceBadge } from "./EvidenceText";
import RuleItem from "./RuleItem";

const raised = (v: RuleVerdict) => v.status === "warn" || v.status === "fail";

function thresholdText(v: RuleVerdict | undefined, lang: Lang): string | null {
  if (!v?.threshold) return null;
  const nature = v.threshold.nature === "team_assumption" ? ` (${t("app.teamAssumption", lang)})` : "";
  return `${t("sim.rule.threshold", lang)} : ${v.threshold.value} %${nature}`;
}

export default function SummaryCards({ run, lang, horizonYears }: { run: Run; lang: Lang; horizonYears?: number }) {
  const scenario = run.scenarios.find((s) => s.index === 1) ?? run.scenarios.find((s) => s.index === 0);
  if (!scenario) return null;
  const idx = scenario.index;
  const ev = (key: string) => run.evidence.find((e) => e.id === scenario.metrics?.[key]);
  const rule = (id: string) => run.verdicts.find((v) => v.rule === id && (v.scenario ?? idx) === idx);
  const r2 = rule("R2");
  const r6 = rule("R6");
  const top = ev("topSingleWeight");
  const range = ev("maxDrawdownRange");
  const flagged = run.verdicts.filter((v) => raised(v) && (v.scenario ?? idx) === idx);
  const cryptoAlert = flagged.some((v) => v.rule === "R7");

  return (
    <section aria-label={t("cards.title", lang)}>
      <h2 className="section-title" style={{ marginTop: 12 }}>{t("cards.title", lang)}</h2>
      <p className="muted small">{t("cards.scenario", lang)} : {scenario.label}</p>
      <div className="summary-cards">
        <div className="profile-card summary-card">
          <div className="eyebrow">{t("cards.concentration", lang)}</div>
          {top ? (
            <p className="small">{t("cards.concentration.fact", lang).replace("{value}", top.formatted ?? "")} <EvidenceBadge ev={top} lang={lang} /></p>
          ) : <p className="muted small">{t("app.unresolved", lang)}</p>}
          {r6 && <p className="small"><span className={ruleBadgeClass(r6.reasonCode, r6.status)}>{ruleLabel(r6.reasonCode, r6.status, lang)}</span></p>}
          {thresholdText(r6, lang) && <p className="muted small">{thresholdText(r6, lang)}</p>}
        </div>

        <div className="profile-card summary-card">
          <div className="eyebrow">{t("cards.downside", lang)}</div>
          {range ? (
            <p className="small">{t("cards.downside.fact", lang).replace("{range}", range.formatted ?? "")} <EvidenceBadge ev={range} lang={lang} /></p>
          ) : <p className="muted small">{t("cards.downside.none", lang)}</p>}
          {r2 && <p className="small"><span className={ruleBadgeClass(r2.reasonCode, r2.status)}>{ruleLabel(r2.reasonCode, r2.status, lang)}</span></p>}
          {thresholdText(r2, lang) && <p className="muted small">{thresholdText(r2, lang)}</p>}
          <p className="muted small">{t("cards.downside.note", lang)}</p>
        </div>

        <div className="profile-card summary-card">
          <div className="eyebrow">{t("cards.review", lang)}</div>
          {flagged.length === 0 ? <p className="muted small">{t("cards.review.none", lang)}</p> : (
            <ul className="rule-list">
              {flagged.map((v, i) => {
                const message = v.message ?? v.messageEn ?? "";
                return (
                  <RuleItem key={i} rule={v.rule} reasonCode={v.reasonCode} status={v.status} lang={lang}>
                    {message ? <p>{message}</p> : null}
                  </RuleItem>
                );
              })}
            </ul>
          )}
          {horizonYears !== undefined && <p className="muted small">{t("cards.review.horizon", lang).replace("{years}", String(horizonYears))}</p>}
          {cryptoAlert && <p className="small">{t("cards.review.crypto", lang)}</p>}
        </div>
      </div>
      <p className="muted small">{t("cards.notice", lang)}</p>
      <p className="muted small">{t("cards.pastPerformance", lang)}</p>
    </section>
  );
}
