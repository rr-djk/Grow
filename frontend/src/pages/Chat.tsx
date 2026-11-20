import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError, errorText } from "../api/errors";
import {
  createConversation, createMandate, createRun, deleteConversation, getRun, listConversations, listMandates, renameConversation,
  listMessages, listPortfolios, putHoldings, sendMessage,
} from "../api/endpoints";
import type { Conversation, Evidence, Mandate, MandateCreateRequest, Message, Run, Scenario } from "../api/types";
import AppHeader from "./../components/AppHeader";
import ConversationColumn from "./../components/chat/ConversationColumn";
import SimulationPanel from "./../components/chat/SimulationPanel";
import { LangContext, t, useT } from "./../lib/i18n";

const POLL_MS = 2000;
const tmpId = () => `tmp-${Date.now()}`;

function onboardingSeed(lang: "fr" | "en", amount?: number): string {
  const money = amount ? (lang === "en" ? `$${Math.round(amount).toLocaleString("en-CA")}` : `${Math.round(amount).toLocaleString("fr-CA")} $`) : "";
  if (lang === "en") return `Build me a first fictitious portfolio${money ? ` of ${money} CAD` : ""} from my profile, and explain how it works.`;
  return `Construis-moi un premier portefeuille fictif${money ? ` de ${money} CA` : ""}, et explique-moi comment ça fonctionne.`;
}

export default function Chat() {
  const nav = useNavigate();
  const location = useLocation();
  const seeded = useRef(false);
  const [sessions, setSessions] = useState<Conversation[]>([]);
  const [q, setQ] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const activeRef = useRef<string | null>(null);
  activeRef.current = activeId;

  const [messages, setMessages] = useState<Message[]>([]);
  const [mandate, setMandate] = useState<Mandate | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const { lang } = useT();
  const [mobilePanel, setMobilePanel] = useState<"history" | "conversation" | "simulation">("conversation");

  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refusal, setRefusal] = useState<{ id: number; sent: string; message: string } | null>(null);

  useEffect(() => {
    listConversations().then((p) => setSessions(p.items)).catch(() => {  });
  }, []);

  const refreshMandate = useCallback(async (sessionId: string) => {
    try {
      const { items } = await listMandates(sessionId);
      setMandate(items[0] ?? null);
      return items[0] ?? null;
    } catch { setMandate(null); return null; }
  }, []);

  const openSession = useCallback(async (sessionId: string | null) => {
    setActiveId(sessionId); activeRef.current = sessionId;
    setMessages([]); setMandate(null); setRun(null); setRunId(null); setError(""); setRefusal(null);
    if (!sessionId) return;
    setLoading(true);
    try {
      const all: Message[] = [];
      let cursor: string | undefined;
      for (let i = 0; i < 20; i++) {
        const p = await listMessages(sessionId, cursor);
        all.push(...p.items);
        if (!p.nextCursor) break;
        cursor = p.nextCursor;
      }
      if (activeRef.current !== sessionId) return;
      setMessages(all);

      await refreshMandate(sessionId);

      const lastRunId = [...all].reverse().find((m) => m.role === "assistant" && m.runId)?.runId;
      if (lastRunId) {
        const r = await getRun(sessionId, lastRunId).catch(() => null);
        if (r && activeRef.current === sessionId) { setRun(r); setRunId(r.runId); }
      }
      await refreshMandate(sessionId);
    } catch (e) {
      if (activeRef.current === sessionId) setError(errorText(e));
      if (e instanceof ApiError && e.code === "CONVERSATION_NOT_FOUND") {
        setSessions((s) => s.filter((x) => x.sessionId !== sessionId));
      }
    } finally {
      if (activeRef.current === sessionId) setLoading(false);
    }
  }, [refreshMandate, sessions]);

  const send = useCallback(async (text: string) => {
    if (!text.trim() || busy) return;
    setError(""); setRefusal(null); setBusy(true);
    let sid = activeRef.current;
    const optimistic: Message = { messageId: tmpId(), sessionId: sid ?? "", role: "user", content: text, status: "done", createdAt: new Date().toISOString() };
    try {
      if (!sid) {
        const c = await createConversation(text.slice(0, 40));
        sid = c.sessionId;
        activeRef.current = sid;
        setActiveId(sid);
        setSessions((l) => [c, ...l]);
        setMessages([]);
      }
      setMessages((m) => [...m, optimistic]);
      const r = await sendMessage(sid, text);
      if (activeRef.current !== sid) return;
      setMessages((m) => [...m.filter((x) => x.messageId !== optimistic.messageId), r.userMessage, r.assistantMessage]);
      if (r.assistantMessage.runId) setRunId(r.assistantMessage.runId);
      setSessions((l) => l.map((c) => (c.sessionId === sid ? { ...c, updatedAt: r.assistantMessage.createdAt } : c)));
    } catch (e) {
      if (activeRef.current === sid) setMessages((m) => m.filter((x) => x.messageId !== optimistic.messageId));
      if (e instanceof ApiError && e.code === "GUARDRAIL_BLOCKED") setRefusal({ id: Date.now(), sent: text, message: errorText(e) });
      else setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, [busy]);

  useEffect(() => {
    const onboarding = (location.state as { onboarding?: { amount?: number } } | null)?.onboarding;
    if (!onboarding || seeded.current) return;
    seeded.current = true;
    nav(location.pathname, { replace: true, state: null });
    void send(onboardingSeed(lang === "en" ? "en" : "fr", onboarding.amount));
  }, [location, nav, send, lang]);

  const adopt = useCallback(async (s: Scenario) => {
    if (busy) return;
    const holdings = (s.holdings ?? []).filter((h) => h.quantity && h.price).map((h) => ({ ticker: h.symbol, quantity: h.quantity!, avgCost: h.price! }));
    if (!holdings.length) return;
    setError(""); setBusy(true);
    try {
      const main = (await listPortfolios()).items.find((p) => p.portfolioId === "main");
      if (main?.holdings.length && !window.confirm(t("sim.adopt.replace", lang))) return;
      await putHoldings("main", holdings);
      nav("/portefeuille");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, [busy, lang, nav]);

  const confirmMandate = useCallback(async (m: MandateCreateRequest) => {
    const sid = activeRef.current;
    if (!sid || busy) return;
    setError(""); setBusy(true);
    try {
      const full: MandateCreateRequest = {
        ...m,
        portfolioId: m.portfolioId || "main",
        userLanguage: m.userLanguage || (lang === "en" ? "en" : "fr"),
      };
      const created = await createMandate(sid, full);
      if (activeRef.current !== sid) return;
      setMandate(created);
      const r = await createRun(sid, created.version);
      if (activeRef.current !== sid) return;
      setRun(r); setRunId(r.runId);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, [busy, lang]);

  useEffect(() => {
    const sid = activeRef.current;
    if (!runId || !sid || run?.status !== "partial") return;
    const timer = setTimeout(async () => {
      try {
        const r = await getRun(sid, runId);
        if (activeRef.current !== sid) return;
        setRun(r);
        if (r.status === "done") {
          setMessages((ms) => ms.map((m) => (m.runId === runId ? { ...m } : m)));
        }
      } catch {  }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [run, runId]);

  const runCompare = useCallback(async (req: { compareCategory?: import("./../lib/comparisonCategories").ComparisonCategoryId }) => {
    const sid = activeRef.current;
    const base = mandate?.mandate;
    if (!sid || !base || busy) return;
    const next: MandateCreateRequest = { ...base, ...req };
    if (!req.compareCategory) delete (next as { compareCategory?: string }).compareCategory;
    await confirmMandate(next);
  }, [mandate, busy, confirmMandate]);

  const rerunOld = useCallback(async (mandateVersion: number) => {
    const sid = activeRef.current;
    if (!sid || busy) return;
    setBusy(true);
    try {
      const r = await createRun(sid, mandateVersion);
      if (activeRef.current !== sid) return;
      setRun(r); setRunId(r.runId);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }, [busy]);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [railError, setRailError] = useState("");
  const startRename = (c: Conversation) => { setConfirmId(null); setRailError(""); setEditingId(c.sessionId); setDraftTitle(c.title ?? ""); };
  const saveRename = useCallback(async (sessionId: string) => {
    const title = draftTitle.trim().slice(0, 120);
    setEditingId(null);
    const before = sessions.find((x) => x.sessionId === sessionId);
    if (!title || title === (before?.title ?? "")) return;
    setSessions((list) => list.map((x) => (x.sessionId === sessionId ? { ...x, title } : x)));
    try {
      const updated = await renameConversation(sessionId, title);
      setSessions((list) => list.map((x) => (x.sessionId === sessionId ? { ...x, ...updated } : x)));
    } catch (e) {
      setSessions((list) => list.map((x) => (x.sessionId === sessionId && before ? before : x)));
      setRailError(errorText(e));
    }
  }, [draftTitle, sessions]);
  const removeSession = useCallback(async (sessionId: string) => {
    setConfirmId(null); setRailError("");
    try {
      await deleteConversation(sessionId);
      setSessions((list) => list.filter((x) => x.sessionId !== sessionId));
      if (activeRef.current === sessionId) void openSession(null);
    } catch (e) {
      if (e instanceof ApiError && e.code === "CONVERSATION_NOT_FOUND") {
        setSessions((list) => list.filter((x) => x.sessionId !== sessionId));
        if (activeRef.current === sessionId) void openSession(null);
      } else setRailError(errorText(e));
    }
  }, [openSession]);
  const evidence: Evidence[] = run?.evidence ?? [];
  const filtered = sessions.filter((c) => (c.title ?? "").toLowerCase().includes(q.trim().toLowerCase()));

  return (
    <LangContext.Provider value={lang}>
      <AppHeader />
      <main className={`chat-page mobile-${mobilePanel}`}>
        <nav className="chat-mobile-tabs" aria-label={t("chat.panels", lang)}>
          {([
            ["history", t("chat.history", lang)],
            ["conversation", "Conversation"],
            ["simulation", t("sim.title", lang)],
          ] as const).map(([panel, label]) => (
            <button
              key={panel}
              type="button"
              className={mobilePanel === panel ? "on" : undefined}
              aria-pressed={mobilePanel === panel}
              onClick={() => setMobilePanel(panel)}
            >
              {label}
            </button>
          ))}
        </nav>
        <aside className="af-side chat-rail">
          <button type="button" className="af-new" onClick={() => { void openSession(null); setMobilePanel("conversation"); }}>+ {t("chat.new", lang)}</button>
          <input className="af-search" placeholder={t("chat.search", lang)} aria-label={t("chat.search", lang)} value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="af-lists">
            <h3 className="af-label">{t("chat.history", lang)}</h3>
            <ul className="af-list">
              {filtered.map((c) => c.sessionId === editingId ? (
                <li key={c.sessionId} className="af-row editing">
                  <input
                    className="af-rename" autoFocus maxLength={120} value={draftTitle}
                    aria-label={t("chat.renameLabel", lang)}
                    onChange={(e) => setDraftTitle(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") void saveRename(c.sessionId); if (e.key === "Escape") setEditingId(null); }}
                    onBlur={() => void saveRename(c.sessionId)}
                  />
                </li>
              ) : c.sessionId === confirmId ? (
                <li key={c.sessionId} className="af-row confirm" role="alertdialog" aria-label={t("chat.deleteConfirm", lang)}>
                  <span style={{ flexBasis: "100%" }}>{t("chat.deleteConfirm", lang)} <strong>{c.title || t("chat.untitled", lang)}</strong></span>
                  <button type="button" className="btn" style={{ padding: "6px 12px" }} onClick={() => void removeSession(c.sessionId)}>{t("chat.delete", lang)}</button>
                  <button type="button" className="link" onClick={() => setConfirmId(null)}>{t("chat.cancel", lang)}</button>
                </li>
              ) : (
                <li key={c.sessionId} className={`af-row${c.sessionId === activeId ? " sel" : ""}`}>
                  <button type="button" className="af-conv" onClick={() => { void openSession(c.sessionId); setMobilePanel("conversation"); }}>
                    <strong>{c.title || t("chat.untitled", lang)}</strong>
                    <span>{new Date(c.updatedAt).toLocaleDateString()}</span>
                  </button>
                  <span className="af-acts">
                    <button type="button" className="af-act" title={t("chat.rename", lang)} aria-label={`${t("chat.rename", lang)} : ${c.title || t("chat.untitled", lang)}`} onClick={() => startRename(c)}>✎</button>
                    <button type="button" className="af-act" title={t("chat.delete", lang)} aria-label={`${t("chat.delete", lang)} : ${c.title || t("chat.untitled", lang)}`} onClick={() => { setEditingId(null); setRailError(""); setConfirmId(c.sessionId); }}>🗑</button>
                  </span>
                </li>
              ))}
              {railError && <li className="af-empty error" role="alert">{railError}</li>}
              {!filtered.length && <li className="af-empty">{q ? "—" : t("chat.history", lang)}</li>}
            </ul>
          </div>
        </aside>

        <div className="chat-grid">
          <ConversationColumn messages={messages} evidence={evidence} busy={busy} lang={lang} refusal={refusal} onDismissRefusal={() => setRefusal(null)}
            onSend={(text) => void send(text)} onQuickReply={(text) => void send(text)}
            onConfirmDraft={(m) => void confirmMandate(m)} />
          <SimulationPanel run={run} lang={lang} busy={busy}
            compareCategory={mandate?.mandate.compareCategory}
            horizonYears={mandate?.mandate.horizonYears}
            onCompare={(req) => void runCompare(req)}
            onAdopt={(s) => void adopt(s)} onAdoptLater={() => nav("/portefeuille")}
            onRerun={run ? () => void rerunOld(run.mandateVersion) : undefined} />
        </div>
        {loading && <p className="muted small chat-loading">{lang === "en" ? "Loading…" : "Chargement…"}</p>}
        {error && <div className="chat-error" role="alert"><p className="error">{error}</p></div>}
      </main>
    </LangContext.Provider>
  );
}
