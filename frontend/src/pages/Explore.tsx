import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import PersonalQuestionnaire from "../components/PersonalQuestionnaire";
import PublicHeader from "../components/PublicHeader";
import { RiskResult } from "../components/RiskForm";
import { useT } from "../lib/i18n";
import { loadPersonalAnswers, savePersonalAnswers } from "../lib/personalDraft";
import { useApp } from "../lib/store";
export default function Explore() {
  const { status } = useApp();
  const { L } = useT();
  const [answers, setAnswers] = useState<Record<string, number> | null>(loadPersonalAnswers);
  const [editing, setEditing] = useState(false);
  if (status === "authed") return <Navigate to="/accueil" replace />;
  return (
    <>
      <PublicHeader actions />
      <main className="wrap" style={{ maxWidth: 760, padding: "40px 24px 80px" }}>
        <div className="eyebrow">{L("Sans compte", "No account")}<span className="tag">{L("Simulation", "Simulation")}</span></div>
        <h1 className="auth-h" style={{ marginTop: 8 }}>{L("Quel investisseur êtes-vous\u00a0?", "What kind of investor are you?")}</h1>
        <p className="muted" style={{ margin: "6px 0 24px" }}>
          {L("Cinq questions pour situer votre tolérance au risque. Vos réponses restent dans cet onglet et ne sont envoyées nulle part ; elles seront reprises si vous créez un compte.",
             "Five questions to place your risk tolerance. Your answers stay in this tab and are sent nowhere; they are reused if you create an account.")}
        </p>
        {answers && !editing ? (
          <>
            <RiskResult answers={answers} />
            <p className="muted small" style={{ marginTop: 12 }}>
              {L("Résultat indicatif d'un outil éducatif : ce n'est pas un conseil financier.", "Indicative result from an educational tool: this is not financial advice.")}
            </p>
            <div className="actions-row" style={{ marginTop: 20 }}>
              <Link to="/inscription" className="btn">{L("Créer un compte avec ce profil", "Create an account with this profile")}</Link>
              <button type="button" className="link" onClick={() => setEditing(true)}>{L("Modifier mes réponses", "Edit my answers")}</button>
            </div>
          </>
        ) : (
          <PersonalQuestionnaire
            initial={answers ?? {}}
            submitLabel={L("Voir mon profil", "See my profile")}
            onSubmit={(a) => { setAnswers(a); setEditing(false); savePersonalAnswers(a); window.scrollTo({ top: 0 }); }}
          />
        )}
      </main>
      <footer className="footer"><div className="wrap">{L("Outil éducatif. Aucune transaction réelle. Ne constitue pas un conseil financier.", "Educational tool. No real transactions. Not financial advice.")}</div></footer>
    </>
  );
}
