import { useState } from "react";
import type { Evidence } from "../../api/types";
import { t, type Lang } from "../../lib/i18n";

const PLACEHOLDER = /\{(EV|KB)-(\d+)\}/g;

const REGISTRANT_OBLIGATION = /31-103|31-103CP|31-368/;

function statusLabel(ev: Evidence, lang: Lang): string | undefined {
  if (ev.status !== "projet") return undefined;
  const year = ev.asOf ? ev.asOf.slice(0, 4) : "";
  return (t("proof.regulationTypeProposed", lang) as string).replace("{year}", year);
}

export function EvidenceBadge({ ev, lang }: { ev: Evidence | undefined; lang: Lang }) {
  const [open, setOpen] = useState(false);
  const label = ev ? ev.id : "id inconnu";
  const known = !!ev;
  return (
    <>
      <button
        type="button"
        className={`chip ev-badge${ev?.kind === "regulation" ? " kb" : ""}${known ? "" : " unknown"}`}
        onClick={() => known && setOpen(true)}
        title={known ? ev!.label : t("app.unresolved", lang)}
        aria-haspopup="dialog"
      >
        {label}
      </button>
      {open && known && <ProofCard ev={ev!} lang={lang} onClose={() => setOpen(false)} />}
    </>
  );
}

export function ProofCard({ ev, lang, onClose }: { ev: Evidence; lang: Lang; onClose: () => void }) {
  const row = (key: string, value?: React.ReactNode) =>
    value ? <div className="proof-row"><span className="muted small">{t(`proof.${key}`, lang)}</span><span className="pre">{value}</span></div> : null;
  const value = ev.formatted ?? (ev.value !== undefined ? String(ev.value) : undefined);
  return (
    <div className="af-overlay open proof-overlay" role="dialog" aria-modal="true" aria-label={t("proof.title", lang)} onClick={onClose}>
      <div className="af-shell proof-card" onClick={(e) => e.stopPropagation()}>
        <header className="af-head">
          <strong>{ev.id} · {t(`proof.kind.${ev.kind}`, lang)}</strong>
          <button type="button" className="af-act" onClick={onClose} aria-label={t("proof.close", lang)}>✕</button>
        </header>
        <div className="af-messages" style={{ padding: 16 }}>
          <div className="profile-card" style={{ padding: 16 }}>
            <div className="eyebrow">{t("proof.title", lang)}</div>
            <div className="big filled" style={{ fontSize: 24 }}>{ev.label}</div>
            {row("value", value)}
            {row("scenario", ev.scenario !== undefined ? String(ev.scenario) : undefined)}
            {row("method", ev.method)}
            {row("window", ev.window)}
            {row("currency", ev.currency)}
            {row("source", ev.source)}
            {row("asOf", ev.asOf)}
            {ev.kind === "regulation" && (
              <>
                <div className="proof-row">
                  <span className="muted small" />
                  <span className="pre"><strong>{t("sim.notice.principleTitle", lang)}</strong></span>
                </div>
                {row("document", ev.document)}
                {row("documentType", ev.documentType ? t(`proof.regulationType.${ev.documentType}`, lang) : undefined)}
                {row("regulator", ev.regulator)}
                {row("status", statusLabel(ev, lang))}
                {row("section", ev.section)}
                {ev.sectionTitle && (
                  <div className="proof-row">
                    <span className="muted small" />
                    <span className="pre muted small">{ev.sectionTitle}</span>
                  </div>
                )}
                {REGISTRANT_OBLIGATION.test(ev.document ?? "") && (
                  <div className="proof-row">
                    <span className="muted small" />
                    <p className="small notice pre" style={{ margin: 0 }}>{t("sim.notice.registeredObligation", lang)}</p>
                  </div>
                )}
                {ev.excerpt && (
                  <div className="proof-row">
                    <span className="muted small">{t("proof.excerpt", lang)}</span>
                    <blockquote className="kb-excerpt">
                      <span className="tag">{t("app.kbExcerpt", lang)}</span>
                      <p className="pre">{ev.excerpt}</p>
                    </blockquote>
                  </div>
                )}
                {row("jurisdiction", ev.jurisdiction)}
                {ev.url && (
                  <div className="proof-row">
                    <span className="muted small">{t("proof.url", lang)}</span>
                    <a href={ev.url} target="_blank" rel="noreferrer">{ev.url}</a>
                  </div>
                )}
              </>
            )}
            {ev.caveats?.length ? (
              <div className="proof-row">
                <span className="muted small">{t("proof.caveats", lang)}</span>
                <ul className="proof-caveats">{ev.caveats.map((c, i) => <li key={i} className="small">{c}</li>)}</ul>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function EvidenceText({ text, evidence, lang }: { text: string; evidence: Evidence[]; lang: Lang }) {
  const map = new Map(evidence.map((e) => [e.id, e]));
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(PLACEHOLDER)) {
    const i = m.index ?? 0;
    if (i > last) parts.push(text.slice(last, i));
    const id = `${m[1]}-${m[2]}`;
    parts.push(<EvidenceBadge key={`${id}-${i}`} ev={map.get(id)} lang={lang} />);
    last = i + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <span className="ev-text">{parts}</span>;
}
