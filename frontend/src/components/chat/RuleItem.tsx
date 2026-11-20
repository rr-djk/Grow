import { useId, useState, type ReactNode } from "react";
import { ruleName, t, type Lang } from "../../lib/i18n";
import { ruleBadgeClass, ruleLabel, type RuleStatus } from "../../lib/ruleLabels";

export function MoreToggle({ open, onToggle, controls, lang }: { open: boolean; onToggle: () => void; controls: string; lang: Lang }) {
  return (
    <button type="button" className="more-toggle" aria-expanded={open} aria-controls={controls} onClick={onToggle}>
      {t(open ? "app.showLess" : "app.showMore", lang)}
    </button>
  );
}

export default function RuleItem({ rule, reasonCode, status, lang, context, children }: {
  rule: string;
  reasonCode: string;
  status: RuleStatus;
  lang: Lang;
  context?: string;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const name = ruleName(rule, lang);
  return (
    <li className={`rule-item${open ? " open" : ""}`}>
      <div className="rule-head">
        <strong className="rule-id">{rule}</strong>
        <span className="rule-main">
          {name && <span className="rule-name">{name}</span>}
          {context && <span className="rule-context">{context}</span>}
          <span className={ruleBadgeClass(reasonCode, status)}>{ruleLabel(reasonCode, status, lang)}</span>
        </span>
        {children ? <MoreToggle open={open} onToggle={() => setOpen((o) => !o)} controls={id} lang={lang} /> : null}
      </div>
      {children ? <div className="rule-more" id={id} hidden={!open}>{children}</div> : null}
    </li>
  );
}
