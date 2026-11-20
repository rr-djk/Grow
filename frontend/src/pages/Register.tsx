import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { signUp } from "../api/auth";
import { errorText } from "../api/errors";
import PublicHeader from "../components/PublicHeader";
import { colon } from "../lib/format";
import { useT } from "../lib/i18n";
import { useApp } from "../lib/store";

type Step = "account" | "done";

export default function Register() {
  const { status, login } = useApp();
  const { L } = useT();
  const nav = useNavigate();
  const [step, setStep] = useState<Step>("account");
  const [f, setF] = useState({ firstName: "", lastName: "", email: "", username: "", age: "", password: "", confirm: "" });
  const [terms, setTerms] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const finishing = useRef(false);

  if (status === "authed" && !finishing.current) return <Navigate to="/portefeuille" replace />;

  const set = (k: keyof typeof f) => (e: ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  async function create(e: FormEvent) {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!f.firstName.trim()) x.firstName = "required";
    if (!f.lastName.trim()) x.lastName = "required";
    if (!/^\S+@\S+\.\S+$/.test(f.email)) x.email = "email";
    if (!/^[a-zA-Z0-9_.-]{3,30}$/.test(f.username)) x.username = "username";
    const age = Number(f.age);
    if (!Number.isInteger(age) || age < 18 || age > 110) x.age = "age";
    if (f.password.length < 8) x.password = "password";
    if (f.confirm !== f.password) x.confirm = "confirm";
    if (!terms) x.terms = "terms";
    setErrs(x);
    if (Object.keys(x).length > 0) return;

    setBusy(true); setErr("");
    let accountCreated = false;
    try {
      await signUp(f.username.trim(), f.password, f.email.trim(), f.firstName.trim(), f.lastName.trim());
      accountCreated = true;
      finishing.current = true;
      await login(f.username, f.password);
      nav("/portefeuille", { replace: true });
    } catch (failure) {
      finishing.current = false;
      if (accountCreated) {
        setErr(`${L("Compte créé, mais la connexion a échoué", "Account created, but sign-in failed")}${colon()} ${errorText(failure)}`);
        setStep("done");
      } else {
        setErr(errorText(failure));
      }
    } finally {
      setBusy(false);
    }
  }

  const ERR: Record<string, [string, string]> = {
    required: ["Requis", "Required"],
    email: ["Courriel invalide", "Invalid email"],
    username: ["3 à 30 caractères (lettres, chiffres, _ . -)", "3 to 30 characters (letters, digits, _ . -)"],
    age: ["Vous devez avoir 18 ans ou plus", "You must be 18 or older"],
    password: ["Au moins 8 caractères", "At least 8 characters"],
    confirm: ["Les mots de passe diffèrent", "The passwords do not match"],
    terms: ["Vous devez accepter les conditions", "You must accept the terms"],
  };
  const errText = (k: string) => (ERR[k] ? L(ERR[k][0], ERR[k][1]) : k);
  const fld = (k: keyof typeof f, label: string, type = "text", auto?: string) => (
    <div className="field">
      <label htmlFor={k}>{label}</label>
      <input id={k} type={type} autoComplete={auto} value={f[k]} onChange={set(k)} aria-invalid={!!errs[k]} />
      {errs[k] && <span className="error">{errText(errs[k])}</span>}
    </div>
  );

  return (
    <>
      <PublicHeader />
      <main className="auth">
        <div className="auth-card">
          {step === "done" ? (
            <>
              <h1>{L("Compte créé", "Account created")}</h1>
              <div className="stack">
                <p className="error" role="alert">{err}</p>
                <p className="muted small">{L("Après la connexion, votre profil investisseur vous sera demandé lors de la création de votre portefeuille.", "After signing in, you will be asked for your investor profile when you create your portfolio.")}</p>
                <Link to="/login" className="btn">{L("Aller à la connexion", "Go to sign-in")}</Link>
              </div>
            </>
          ) : (
            <>
              <h1>{L("Créer un compte", "Create an account")}</h1>
              <form onSubmit={create} className="stack" noValidate>
                <div className="row2">{fld("firstName", L("Prénom", "First name"), "text", "given-name")}{fld("lastName", L("Nom", "Last name"), "text", "family-name")}</div>
                {fld("email", L("Courriel", "Email"), "email", "email")}
                <div className="row2">{fld("username", L("Nom d'utilisateur", "Username"), "text", "username")}{fld("age", L("Âge", "Age"))}</div>
                <div className="row2">{fld("password", L("Mot de passe", "Password"), "password", "new-password")}{fld("confirm", L("Confirmation", "Confirm password"), "password", "new-password")}</div>
                <label className="check"><input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} /> {L("J'ai lu et j'accepte les conditions et l'avis de non-responsabilité : cet outil est éducatif et ne constitue pas un conseil financier.", "I have read and accept the terms and the disclaimer: this tool is educational and is not financial advice.")}</label>
                {errs.terms && <span className="error">{errText(errs.terms)}</span>}
                {err && <p className="error" role="alert">{err}</p>}
                <button className="btn" disabled={busy}>{busy ? L("Création…", "Creating…") : L("Créer mon compte", "Create my account")}</button>
                <div className="auth-links"><Link to="/login" className="link">{L("Déjà inscrit ? Se connecter", "Already registered? Log in")}</Link></div>
              </form>
            </>
          )}
        </div>
      </main>
    </>
  );
}
