import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { deleteOwnAccount } from "../api/auth";
import { deleteConversation, getSummary, listConversations, listPortfolios, putHoldings } from "../api/endpoints";
import { errorText } from "../api/errors";
import type { Portfolio } from "../api/types";
import { cad } from "../lib/format";
import { useT } from "../lib/i18n";
import { useApp } from "../lib/store";
const INSTITUTIONS = [
  "Banque Nationale Courtage direct", "Desjardins Courtage en ligne (Disnat)", "RBC Placements en Direct",
  "TD Placements directs", "BMO Ligne d'action", "Scotia iTRADE", "CIBC Pro-Investisseurs", "Questrade", "Wealthsimple",
];
type Step = "closed" | "transfer" | "confirm" | "deleting";
export default function CloseAccount() {
  const { user, logout } = useApp();
  const { L } = useT();
  const nav = useNavigate();
  const [step, setStep] = useState<Step>("closed");
  const [portfolios, setPortfolios] = useState<Portfolio[] | null>(null);
  const [value, setValue] = useState<number | null>(null);
  const [institution, setInstitution] = useState("");
  const [other, setOther] = useState("");
  const [transferred, setTransferred] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (step !== "transfer" || portfolios) return;
    listPortfolios().then(async ({ items }) => {
      setPortfolios(items);
      let total = 0;
      for (const p of items.filter((x) => x.holdings.length)) total += (await getSummary(p.portfolioId, "1m")).totals.value;
      setValue(total);
    }).catch((e) => setErr(errorText(e)));
  }, [step, portfolios]);
  const hasFunds = !!portfolios?.some((p) => p.holdings.length);
  const target = institution === "other" ? other.trim() : institution;
  async function transfer() {
    if (!target) return setErr(L("Choisissez l'institution qui recevra vos fonds.", "Choose the institution that will receive your funds."));
    setBusy(true); setErr("");
    try {
      for (const p of portfolios ?? []) if (p.holdings.length) await putHoldings(p.portfolioId, []);
      setPortfolios((list) => (list ?? []).map((p) => ({ ...p, holdings: [] })));
      setTransferred(target);
      setStep("confirm");
    } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  }
  async function remove() {
    if (!user || typed.trim() !== user.username) return;
    setStep("deleting"); setErr("");
    try {
      let cursor: string | undefined;
      do {
        const page = await listConversations(cursor, 50);
        for (const c of page.items) await deleteConversation(c.sessionId);
        cursor = page.nextCursor ?? undefined;
      } while (cursor);
      for (const k of [`af.risk.${user.userId}`, `af.risk.latest.${user.userId}`]) localStorage.removeItem(k);
      await deleteOwnAccount();
      logout();
      nav("/", { replace: true });
    } catch (e) { setErr(errorText(e)); setStep("confirm"); }
  }
  return (
    <div className="dcard danger-zone" style={{ marginTop: 16 }}>
      <div className="dcard-head"><div>
        <div className="dcard-title">{L("Fermer mon compte", "Close my account")}</div>
        <div className="muted small">{L("Transférez d'abord vos fonds, puis supprimez le compte. Action définitive.", "Transfer your funds first, then delete the account. This cannot be undone.")}</div>
      </div></div>
      {step === "closed" && (
        <button type="button" className="btn-ghost danger" onClick={() => setStep("transfer")}>{L("Fermer mon compte…", "Close my account…")}</button>
      )}
      {step === "transfer" && (
        <div className="stack">
          <div className="eyebrow">{L("Étape 1 sur 2 · Transfert des fonds", "Step 1 of 2 · Transfer your funds")}</div>
          {portfolios === null && !err ? <p className="muted small">{L("Chargement…", "Loading…")}</p> : hasFunds ? (
            <>
              <p className="small">
                {L("Avant de fermer le compte, vos positions doivent être transférées vers une autre institution.", "Before closing the account, your holdings must be transferred to another institution.")}
                {value !== null && <> {L("Valeur à transférer :", "Value to transfer:")} <strong>{cad(value, 0)}</strong>.</>}
              </p>
              <div className="field"><label htmlFor="inst">{L("Institution qui recevra vos fonds", "Receiving institution")}</label>
                <select id="inst" className="input" value={institution} onChange={(e) => setInstitution(e.target.value)}>
                  <option value="">{L("Sélectionner…", "Select…")}</option>
                  {INSTITUTIONS.map((i) => <option key={i} value={i}>{i}</option>)}
                  <option value="other">{L("Autre institution", "Other institution")}</option>
                </select></div>
              {institution === "other" && (
                <div className="field"><label htmlFor="inst-other">{L("Nom de l'institution", "Institution name")}</label>
                  <input id="inst-other" maxLength={80} value={other} onChange={(e) => setOther(e.target.value)} /></div>
              )}
              <p className="muted small">{L("Transfert simulé : aucun fonds réel n'est déplacé. N'entrez aucun numéro de compte réel.", "Simulated transfer: no real funds move. Do not enter a real account number.")}</p>
              <div className="actions-row">
                <button type="button" className="btn" disabled={busy} onClick={transfer}>{busy ? L("Transfert…", "Transferring…") : L("Transférer mes fonds", "Transfer my funds")}</button>
                <button type="button" className="link" onClick={() => { setStep("closed"); setErr(""); }}>{L("Annuler", "Cancel")}</button>
              </div>
            </>
          ) : (
            <>
              <p className="small">{L("Aucun fonds à transférer : vos portefeuilles sont vides.", "No funds to transfer: your portfolios are empty.")}</p>
              <div className="actions-row">
                <button type="button" className="btn" onClick={() => setStep("confirm")}>{L("Continuer", "Continue")}</button>
                <button type="button" className="link" onClick={() => setStep("closed")}>{L("Annuler", "Cancel")}</button>
              </div>
            </>
          )}
        </div>
      )}
      {(step === "confirm" || step === "deleting") && user && (
        <div className="stack">
          <div className="eyebrow">{L("Étape 2 sur 2 · Suppression du compte", "Step 2 of 2 · Delete the account")}</div>
          {transferred && <div className="banner ok">{L(`Transfert vers ${transferred} enregistré (simulation). Vos portefeuilles sont vides.`, `Transfer to ${transferred} recorded (simulation). Your portfolios are empty.`)}</div>}
          <p className="small">{L("Seront supprimés : vos sessions et leurs messages, vos résultats de questionnaire sur cet appareil et votre identifiant de connexion. Vous ne pourrez plus vous connecter.", "Will be deleted: your sessions and their messages, your questionnaire results on this device and your sign-in identity. You will no longer be able to sign in.")}</p>
          <div className="field"><label htmlFor="confirm-user">{L(`Pour confirmer, tapez votre nom d'utilisateur : ${user.username}`, `To confirm, type your username: ${user.username}`)}</label>
            <input id="confirm-user" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} disabled={step === "deleting"} /></div>
          <div className="actions-row">
            <button type="button" className="btn danger" disabled={step === "deleting" || typed.trim() !== user.username} onClick={remove}>
              {step === "deleting" ? L("Suppression…", "Deleting…") : L("Supprimer définitivement mon compte", "Permanently delete my account")}
            </button>
            <button type="button" className="link" disabled={step === "deleting"} onClick={() => { setStep("closed"); setTyped(""); setErr(""); }}>{L("Annuler", "Cancel")}</button>
          </div>
        </div>
      )}
      {err && <p className="error" role="alert" style={{ marginTop: 8 }}>{err}</p>}
    </div>
  );
}
