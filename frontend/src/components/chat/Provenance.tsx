import type { Run } from "../../api/types";
import { t, type Lang } from "../../lib/i18n";
import { ruleBadgeClass, ruleLabel } from "../../lib/ruleLabels";
import Explanation from "../Explanation";

export default function Provenance({ run, lang }: { run: Run; lang: Lang }) {
  const metrics = run.evidence.filter((e) => e.kind === "metric" || e.kind === "etf_fact");
  const regs = run.evidence.filter((e) => e.kind === "regulation");
  const assumptions = run.evidence.filter((e) => e.kind === "assumption");
  const raised = run.verdicts.filter((v) => v.status === "warn" || v.status === "fail");
  const teamThresholds = run.verdicts.filter((v) => v.threshold?.nature === "team_assumption");
  const r10 = run.verdicts.find((v) => v.rule === "R10");
  const groups = new Map<string, { source: string; window?: string; asOf?: string; n: number }>();
  for (const e of metrics) {
    const k = `${e.source}|${e.window ?? ""}`;
    const g = groups.get(k) ?? { source: e.source, window: e.window, asOf: e.asOf, n: 0 };
    g.n += 1;
    if (e.asOf && (!g.asOf || e.asOf > g.asOf)) g.asOf = e.asOf;
    groups.set(k, g);
  }
  const labels = Array.from(new Set(metrics.map((e) => e.label.replace(/, scenario \d$/, ""))));
  const methods = Array.from(new Set(metrics.map((e) => e.method).filter(Boolean))) as string[];
  const sections = run.narrative?.sections ?? [];
  const v = run.verifier;

  return (
    <details className="expl provenance" style={{ marginTop: 12 }}>
      <summary>{t("prov.title", lang)}</summary>
      <div className="expl-body">
        <section>
          <h4>{t("prov.data", lang)}</h4>
          <ul className="small">
            {[...groups.values()].map((g, i) => (
              <li key={i}><code>{g.source}</code>{g.window && <> · {t("proof.window", lang)} {g.window}</>}{g.asOf && <> · {t("expl.asOf", lang)} {g.asOf}</>} · {g.n} {t("prov.figures", lang)}</li>
            ))}
            <li>{t("prov.dataset", lang)} : <code>{run.datasetVersion}</code></li>
            <li className="muted">{t("prov.pricesNote", lang)}</li>
          </ul>
        </section>

        <section>
          <h4>{t("prov.assumptions", lang)}</h4>
          <ul className="small">
            {assumptions.map((e) => <li key={e.id}>{e.label}{e.formatted ? ` : ${e.formatted}` : ""}</li>)}
            {teamThresholds.map((v2, i) => <li key={`t${i}`}>{v2.rule} : {t("sim.rule.threshold", lang)} {v2.threshold!.value} ({t("app.teamAssumption", lang)})</li>)}
          </ul>
        </section>

        <section>
          <h4>{t("prov.rules", lang)}</h4>
          {raised.length === 0 ? <p className="muted small">{t("cards.review.none", lang)}</p> : (
            <ul className="small">{raised.map((r, i) => <li key={i}><strong>{r.rule}</strong> <span className={ruleBadgeClass(r.reasonCode, r.status)}>{ruleLabel(r.reasonCode, r.status, lang)}</span></li>)}</ul>
          )}
          {r10 && <p className="muted small">R10 : <span className={ruleBadgeClass(r10.reasonCode, r10.status)}>{ruleLabel(r10.reasonCode, r10.status, lang)}</span> — {t("prov.r10", lang)}</p>}
        </section>

        <section>
          <h4>{t("prov.sources", lang)}</h4>
          {regs.length === 0 ? <p className="muted small">{t("prov.noSources", lang)}</p> : (
            <ul className="small">{regs.map((e) => <li key={e.id}><strong>{e.id}</strong> · {e.document ?? e.label}{e.section ? ` · ${e.section}` : ""}{e.regulator ? ` · ${e.regulator}` : ""}{e.asOf ? ` · ${e.asOf}` : ""}</li>)}</ul>
          )}
        </section>

        <section>
          <h4>{t("prov.engine", lang)}</h4>
          <p className="muted small">{t("prov.engine.note", lang)}</p>
          <ul className="small">{labels.map((l) => <li key={l}>{l}</li>)}</ul>
          {methods.length > 0 && <details><summary className="small">{t("proof.method", lang)}</summary><ul className="small muted">{methods.map((m, i) => <li key={i}>{m}</li>)}</ul></details>}
        </section>

        <section>
          <h4>{t("prov.ai", lang)}</h4>
          <p className="muted small">{t("prov.ai.note", lang)}</p>
          <ul className="small">
            {sections.length > 0 && <li>{t("prov.ai.sections", lang)} : {sections.map((s) => t(`sim.section.${s.key}`, lang)).join(" · ")}</li>}
            <li>{t("prov.ai.translation", lang)}</li>
            {v && <li>{t("sim.verifier", lang)} : {v.placeholdersResolved}/{v.placeholdersTotal}, {t("sim.verifier.handwritten", lang)} {v.handwrittenNumbers}</li>}
            {run.narrative?.hiddenSentences?.length ? <li>{run.narrative.hiddenSentences.length} {t("prov.ai.hidden", lang)}</li> : null}
          </ul>
        </section>

        {run.explanation && <section><h4>{t("prov.trace", lang)}</h4><Explanation data={run.explanation} /></section>}
      </div>
    </details>
  );
}
