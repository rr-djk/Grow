import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import growLogo from "../assets/grow-logo.svg";
import { useT } from "../lib/i18n";
import LangSwitch from "./LangSwitch";

export default function PublicHeader({ actions = false }: { actions?: boolean }) {
  const { t, L } = useT();
  return (
    <header className="header">
      <div className="wrap">
        <Link to="/" className="logo" aria-label={L("Grow — Accueil", "Grow — Home")}>
          <img className="brand-logo" src={growLogo} alt="Grow" />
        </Link>
        <div className="header-right">
          <LangSwitch />
          {actions && (
            <>
              <Link to="/login" className="link">{t("nav.login")}</Link>
              <Link to="/inscription" className="btn">{t("nav.signup")}</Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

export function AuthShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <PublicHeader />
      <main className="auth"><div className="auth-card"><h1>{title}</h1>{children}</div></main>
    </>
  );
}
