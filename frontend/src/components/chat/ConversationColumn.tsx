import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { MandateCreateRequest, Message } from "../../api/types";
import { t, type Lang } from "../../lib/i18n";
import { PROVINCES } from "../../lib/risk";
import { appendSpeech } from "../../lib/speech";
import { useSpeechToText } from "../../lib/useSpeechToText";
import Explanation from "../Explanation";
import MandateCard from "./MandateCard";
import MessageText from "./MessageText";

const MAX_LEN = 2000;

const MODES = ["add_asset", "rebalance", "diagnose", "build"] as const;
const OBJECTIVES = ["growth", "income", "preservation", "project", "retirement"] as const;

function DraftEditor({ draft, lang, onConfirm }: { draft: MandateCreateRequest; lang: Lang; onConfirm: (m: MandateCreateRequest) => void }) {
  const [m, setM] = useState<MandateCreateRequest>(draft);
  const set = (patch: Partial<MandateCreateRequest>) => setM({ ...m, ...patch });
  const num = (v: string) => (v === "" ? undefined : Number(v));
  return (
    <div className="stack">
      <div className="row2">
        <div className="field"><label htmlFor="d-mode">{t("mandate.mode", lang)}</label>
          <select id="d-mode" className="input" value={m.mode} onChange={(e) => set({ mode: e.target.value as MandateCreateRequest["mode"] })}>
            {MODES.map((x) => <option key={x} value={x}>{t(`mandate.mode.${x}`, lang)}</option>)}
          </select></div>
        <div className="field"><label htmlFor="d-obj">{t("mandate.objective", lang)}</label>
          <select id="d-obj" className="input" value={m.objective} onChange={(e) => set({ objective: e.target.value as MandateCreateRequest["objective"] })}>
            {OBJECTIVES.map((x) => <option key={x} value={x}>{t(`mandate.objective.${x}`, lang)}</option>)}
          </select></div>
      </div>
      <div className="row2">
        <div className="field"><label htmlFor="d-hor">{t("mandate.horizon", lang)} ({t("mandate.years", lang)})</label>
          <input id="d-hor" className="input" inputMode="numeric" value={m.horizonYears} onChange={(e) => set({ horizonYears: num(e.target.value) ?? 0 })} /></div>
        <div className="field"><label htmlFor="d-sub">{t("mandate.subject", lang)}</label>
          <input id="d-sub" className="input" value={m.subjectTicker ?? ""} onChange={(e) => set({ subjectTicker: e.target.value.toUpperCase() || undefined })} /></div>
      </div>
      <div className="row2">
        <div className="field"><label htmlFor="d-tol">{t("mandate.riskTolerance", lang)} (1-5)</label>
          <input id="d-tol" className="input" inputMode="numeric" value={m.riskTolerance} onChange={(e) => set({ riskTolerance: num(e.target.value) ?? 1 })} /></div>
        <div className="field"><label htmlFor="d-cap">{t("mandate.riskCapacity", lang)} (1-5)</label>
          <input id="d-cap" className="input" inputMode="numeric" value={m.riskCapacity} onChange={(e) => set({ riskCapacity: num(e.target.value) ?? 1 })} /></div>
      </div>
      <div className="row2">
        <div className="field"><label htmlFor="d-loss">{t("col.sliderLoss", lang)}</label>
          <input id="d-loss" className="input" inputMode="numeric" value={m.maxAcceptableLossPct ?? ""} onChange={(e) => set({ maxAcceptableLossPct: num(e.target.value) })} /></div>
        <div className="field"><label htmlFor="d-prov">{t("mandate.province", lang)}</label>
          <select id="d-prov" className="input" value={m.province} onChange={(e) => set({ province: e.target.value as MandateCreateRequest["province"] })}>
            {PROVINCES.map((p) => <option key={p.code} value={p.code}>{p.label} ({p.code})</option>)}
          </select></div>
      </div>
      <div><button type="button" className="btn" onClick={() => onConfirm(m)}>{t("mandate.confirm", lang)}</button></div>
    </div>
  );
}

function Bubble({
  m, lang, evidence, onQuickReply, onConfirmDraft, busy,
}: {
  m: Message; lang: Lang; evidence: import("../../api/types").Evidence[]; busy: boolean;
  onQuickReply: (text: string) => void;
  onConfirmDraft: (m: MandateCreateRequest) => void;
}) {
  const [editing, setEditing] = useState(false);
  const draft = m.mandateDraft;
  return (
    <div className={`msg ${m.role}`}>
      <div className={`bubble${m.status === "error" ? " err" : ""}`}>
        {m.status === "pending" ? <span className="muted">{t("chat.thinking", lang)}</span> : (
          <>
            {m.role === "assistant"
              ? <MessageText text={m.content} evidence={evidence} lang={lang} resolve={!!m.runId} />
              : <p className="pre">{m.content}</p>}
            {m.role === "assistant" && m.explanation && <Explanation data={m.explanation} />}
            {m.quickReplies?.length ? (
              <div className="suggest" style={{ marginTop: 10 }}>
                {m.quickReplies.map((qr) => (
                  <button key={qr} type="button" className="chip" disabled={busy} onClick={() => onQuickReply(qr)}>{qr}</button>
                ))}
              </div>
            ) : null}
            {draft && !editing && (
              <div style={{ marginTop: 10 }}>
                <div className="eyebrow">{t("mandate.draftCard", lang)}</div>
                <p className="muted small">{t("mandate.draftHint", lang)}</p>
                <MandateCard mandate={draft} lang={lang} />
                <div className="row2" style={{ marginTop: 8 }}>
                  <button type="button" className="btn" disabled={busy} onClick={() => onConfirmDraft(draft)}>{t("mandate.confirm", lang)}</button>
                  <button type="button" className="btn-ghost" disabled={busy} onClick={() => setEditing(true)}>{t("mandate.edit", lang)}</button>
                </div>
              </div>
            )}
            {draft && editing && (
              <div style={{ marginTop: 10 }}>
                <div className="eyebrow">{t("mandate.edit", lang)}</div>
                <DraftEditor draft={draft} lang={lang} onConfirm={(x) => { setEditing(false); if (x) onConfirmDraft(x); }} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function ConversationColumn({
  messages, evidence, busy, lang, refusal, onDismissRefusal, onSend, onQuickReply, onConfirmDraft,
}: {
  messages: Message[];
  evidence: import("../../api/types").Evidence[];
  busy: boolean;
  lang: Lang;
  refusal: { id: number; sent: string; message: string } | null;
  onDismissRefusal: () => void;
  onSend: (text: string) => void;
  onQuickReply: (text: string) => void;
  onConfirmDraft: (m: MandateCreateRequest) => void;
}) {
  const [v, setV] = useState("");
  const [partial, setPartial] = useState("");
  const [dictated, setDictated] = useState(false);
  const speech = useSpeechToText(lang, (seg) => { setDictated(true); setV((cur) => appendSpeech(cur, seg, MAX_LEN)); }, setPartial);
  const dictating = speech.state === "listening" || speech.state === "finishing";
  const shown = appendSpeech(v, partial, MAX_LEN);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => { const el = field.current; if (el && partial) el.scrollLeft = el.scrollWidth; }, [partial]);
  useEffect(() => { if (refusal) { setV(refusal.sent); setDictated(false); field.current?.focus(); } }, [refusal?.id]);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [messages.length, busy]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const text = shown.trim();
    if (!text || busy) return;
    speech.abort();
    setPartial("");
    setV("");
    setDictated(false);
    onSend(text);
  }
  const key = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(e as unknown as FormEvent); }
  };

  return (
    <main className="chat-col chat-col-mid">
      <div className="chat-col-scroll">
        {messages.length === 0 && !busy && <p className="muted">{t("chat.empty", lang)}</p>}
        {messages.map((m) => (
          <Bubble key={m.messageId} m={m} lang={lang} evidence={evidence} busy={busy} onQuickReply={onQuickReply} onConfirmDraft={onConfirmDraft} />
        ))}
        {busy && <div className="msg assistant"><div className="bubble typing"><i /><i /><i /></div></div>}
        <div ref={end} />
      </div>
      <div className="chat-col-foot">
        <form className={`af-composer${partial ? " af-composer-live" : ""}`} onSubmit={submit}>
          {}
          <input ref={field} value={shown} onChange={(e) => { setV(e.target.value); if (refusal) onDismissRefusal(); }} onKeyDown={key} readOnly={dictating}
            placeholder={t("chat.placeholder", lang)} aria-label={t("chat.send", lang)} maxLength={MAX_LEN} />
          {speech.supported && (
            <button type="button" className={`af-mic${speech.state === "listening" ? " listening" : ""}`}
              disabled={busy || speech.state === "connecting" || speech.state === "finishing"} aria-pressed={speech.state === "listening"}
              aria-label={t(speech.state === "listening" ? "chat.mic.stop" : "chat.mic.start", lang)}
              title={t(speech.state === "listening" ? "chat.mic.stop" : "chat.mic.start", lang)}
              onClick={() => (speech.state === "listening" ? speech.stop() : void speech.start())}>
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
              </svg>
            </button>
          )}
          <button type="submit" className="af-send" disabled={busy || !shown.trim()} aria-label={t("chat.send", lang)}>↑</button>
        </form>
        {refusal && (
          <div className="af-refusal" role="status" aria-live="polite">
            <span className="af-refusal-icon" aria-hidden="true">⚠</span>
            <div>
              <strong>{lang === "en" ? "Request not supported" : "Demande non prise en charge"}</strong>
              <p>{refusal.message}</p>
            </div>
          </div>
        )}
        {(speech.state === "denied" || speech.state === "error") && (
          <p className="af-mic-note err" role="status">
            {speech.state === "denied" ? t("chat.mic.denied", lang) : t("chat.mic.error", lang)}
          </p>
        )}
        {speech.supported && !dictating && dictated && !!v && <p className="af-mic-note" role="status">{t("chat.mic.review", lang)}</p>}
        <p className="af-disclaimer">{t("app.disclaimer", lang)}</p>
      </div>
    </main>
  );
}
