import { Link, Navigate } from "react-router-dom";
import PublicHeader from "../components/PublicHeader";
import { useT } from "../lib/i18n";
import { useApp } from "../lib/store";

export default function Landing() {
  const { status } = useApp();
  const { L } = useT();
  if (status === "authed") return <Navigate to="/accueil" replace />;

  return (
    <>
      <PublicHeader actions />
      <main className="wrap landing-page">
        <section className="landing-hero">
          <div className="landing-hero-content">
            <div className="eyebrow">Grow<span className="tag">{L("Analyse quantitative", "Quantitative analysis")}</span></div>
            <h1 className="big filled">{L("L'analyse quantitative pour tous\u00a0!", "Quantitative analysis for everyone!")}</h1>
            <p className="lead">{L("Générez votre propre portefeuille diversifié en fonction de vos valeurs et de votre tolérance au risque, car chez Grow, nous sommes convaincus que chaque investisseur mérite son portefeuille.", "Generate your own diversified portfolio based on your values and your risk tolerance, because at Grow we believe every investor deserves their own portfolio.")}</p>
            <div className="actions-row">
              <Link to="/inscription" className="btn">{L("Créer un compte", "Create an account")}</Link>
              <Link to="/explorer" className="btn-ghost">{L("Explorer sans compte", "Explore without an account")}</Link>
            </div>
          </div>
        </section>
      </main>
      <footer className="footer"><div className="wrap">{L("Outil éducatif. Aucune transaction réelle. Ne constitue pas un conseil financier.", "Educational tool. No real transactions. Not financial advice.")}</div></footer>
    </>
  );
}
