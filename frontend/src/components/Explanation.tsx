import type { Explanation as Expl } from "../api/types";
import { useT } from "../lib/i18n";
import { ruleBadgeClass, ruleLabel } from "../lib/ruleLabels";
import RuleItem from "./chat/RuleItem";

export default function Explanation({ data, defaultOpen = false }: { data: Expl; defaultOpen?: boolean }) {
  const { t, lang } = useT();
  const checks = data.checks ?? [];
  return (
    <details className="expl" open={defaultOpen}>
      <summary>
        {t("expl.title")}
        {checks.length > 0 && checks.map((c, i) => {
          const status = c.status;
          return <span key={i} className={ruleBadgeClass(c.reasonCode ?? "", status)} title={c.message}>{ruleLabel(c.reasonCode ?? "", status, lang)}</span>;
        })}
      </summary>
      <div className="expl-body">
        {checks.length > 0 && (
          <section>
            <h4>{t("expl.checks")}</h4>
            <ul className="rule-list">{checks.map((c, i) => (
              <RuleItem key={i} rule={c.rule} reasonCode={c.reasonCode ?? ""} status={c.status} lang={lang}
                context={c.scenario !== undefined ? `${t("proof.scenario")} ${c.scenario}` : undefined}>
                {c.message ? <p>{c.message}</p> : null}
              </RuleItem>
            ))}</ul>
          </section>
        )}
        {data.sources.length > 0 && (
          <section>
            <h4>{t("expl.sources")}</h4>
            <ul>{data.sources.map((s) => <li key={s.id}><strong>{s.id}</strong>{s.dataset && <> · <code>{s.dataset}</code></>}{s.asOf && <> · {t("expl.asOf")} {s.asOf}</>}{s.note && <> · {s.note}</>}</li>)}</ul>
          </section>
        )}
        {data.steps.length > 0 && (
          <section>
            <h4>{t("expl.steps")}</h4>
            <ul>{data.steps.map((s, i) => (
              <li key={i}><code>{s.agentId}</code> → <code>{s.tool}</code>{s.params && Object.keys(s.params).length > 0 && <> <span className="muted">{JSON.stringify(s.params)}</span></>} · {t(`expl.step.${s.status}`)}{s.durationMs != null && <> · {s.durationMs} ms</>}</li>
            ))}</ul>
          </section>
        )}
        {!!data.assumptions?.length && (
          <section><h4>{t("expl.assumptions")}</h4><ul>{data.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></section>
        )}
        {!!data.limitations?.length && (
          <section><h4>{t("expl.limitations")}</h4><ul>{data.limitations.map((a, i) => <li key={i}>{a}</li>)}</ul></section>
        )}
      </div>
    </details>
  );
}
