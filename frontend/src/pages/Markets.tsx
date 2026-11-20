import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import AppHeader from "../components/AppHeader";
import InfoTip from "../components/InfoTip";
import { searchAssets } from "../api/endpoints";
import { errorText } from "../api/errors";
import type { Asset } from "../api/types";
import TickerLogo from "../components/TickerLogo";
import { assetClassName } from "../lib/assetClasses";
import { t as tt, useT } from "../lib/i18n";
import "../markets.css";

const CLASS_TONE: Record<string, string> = { equity: "eq", etf: "etf", crypto: "cr" };
const FILTERS: { value: string; fr: string; en: string }[] = [
  { value: "", fr: "Tout", en: "All" },
  { value: "equity", fr: "Actions", en: "Stocks" },
  { value: "etf", fr: "FNB", en: "ETFs" },
  { value: "crypto", fr: "Crypto", en: "Crypto" },
];
const SUGGESTIONS = ["RY.TO", "NVDA", "XEQT", "BTC-USD"];

const toneOf = (a: Pick<Asset, "assetClass">) => CLASS_TONE[a.assetClass.split("_")[0]] ?? "eq";

export default function Markets() {
  const { lang, L } = useT();
  const labelOf = (a: Pick<Asset, "assetClass">) => assetClassName(a.assetClass, lang);
  const [q, setQ] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [items, setItems] = useState<Asset[]>([]);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const query = q.trim();
    if (!query && !assetClass) { setItems([]); setError(""); setLoading(false); return; }
    const ctrl = new AbortController();
    setLoading(true);
    const t = setTimeout(async () => {
      setError("");
      try {
        const res = await searchAssets(query, assetClass || undefined, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setItems(res.items);
        setSelected((cur) => (cur && res.items.some((a) => a.ticker === cur.ticker) ? cur : res.items[0] ?? null));
      } catch (x) {
        if (!ctrl.signal.aborted) { setItems([]); setError(errorText(x)); }
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    }, 300);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [q, assetClass]);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const i = items.findIndex((a) => a.ticker === selected?.ticker);
    const next = items[Math.min(items.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))];
    if (next) {
      setSelected(next);
      (e.currentTarget.querySelector(`[data-ticker="${CSS.escape(next.ticker)}"]`) as HTMLElement | null)?.focus();
    }
  };

  const query = q.trim();
  const idle = !query && !assetClass;
  const empty = !idle && !loading && !error && items.length === 0;

  return (
    <>
      <AppHeader />
      <main className="wrap mk">
        <section className="mk-top">
          <div className="mk-title">
            <h1>{L("Marchés", "Markets")}</h1>
            <p>{L("Actions, FNB et cryptomonnaies couverts par la simulation.", "Stocks, ETFs and cryptocurrencies covered by the simulation.")}</p>
          </div>

          <div className="mk-search">
            <svg className="mk-search-ico" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
            </svg>
            <input
              ref={inputRef}
              type="search"
              className="mk-input"
              placeholder={L("Rechercher un ticker ou un nom (ex. RY.TO, NVDA, XEQT)", "Search a ticker or a name (e.g. RY.TO, NVDA, XEQT)")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              aria-label={L("Recherche d'actif", "Asset search")}
              autoComplete="off"
              spellCheck={false}
            />
            {q ? (
              <button type="button" className="mk-clear" onClick={() => { setQ(""); inputRef.current?.focus(); }} aria-label={L("Effacer la recherche", "Clear the search")}>×</button>
            ) : (
              <kbd className="mk-kbd" aria-hidden="true">/</kbd>
            )}
          </div>

          <div className="mk-filters" role="group" aria-label={L("Catégorie", "Category")}>
            {FILTERS.map((f) => (
              <button
                key={f.value || "all"} type="button"
                className={`mk-chip${assetClass === f.value ? " on" : ""}`}
                aria-pressed={assetClass === f.value}
                onClick={() => setAssetClass(f.value)}
              >{f[lang]}</button>
            ))}
          </div>
        </section>

        {error && <div className="banner warn" role="status"><p>{error}</p></div>}

        {idle && (
          <section className="mk-empty">
            <div className="mk-empty-ico" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></svg>
            </div>
            <h2>{L("Explorez l'univers d'actifs", "Explore the asset universe")}</h2>
            <p>{L("Tapez quelques lettres d'un ticker ou d'un nom, ou choisissez une catégorie.", "Type a few letters of a ticker or a name, or pick a category.")}</p>
            <div className="mk-suggest">
              <span>{L("Essayez", "Try")}</span>
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="mk-chip ghost" onClick={() => { setQ(s); inputRef.current?.focus(); }}>
                  <TickerLogo ticker={s} size={18} />{s}
                </button>
              ))}
            </div>
          </section>
        )}

        {empty && (
          <section className="mk-empty">
            <h2>{L("Aucun résultat", "No results")}</h2>
            <p>{L("Aucun actif ne correspond à", "No asset matches")} « {query || labelOf({ assetClass })} ». {L("Vérifiez l'orthographe ou essayez un autre ticker.", "Check the spelling or try another ticker.")}</p>
          </section>
        )}

        {!idle && (loading || items.length > 0) && (
          <section className="mk-grid">
            <div className="mk-listcard">
              <div className="mk-listhead">
                <span>{loading ? L("Recherche…", "Searching…") : L(`${items.length} résultat${items.length > 1 ? "s" : ""}`, `${items.length} result${items.length > 1 ? "s" : ""}`)}</span>
                <span className="mk-hide-sm">{L("Marché · Devise", "Market · Currency")}</span>
              </div>
              {loading && items.length === 0 ? (
                <ul className="mk-list" aria-busy="true">
                  {[0, 1, 2, 3, 4].map((i) => <li key={i} className="mk-row skel"><span className="sk-c" /><span className="sk-l" /></li>)}
                </ul>
              ) : (
                <ul className={`mk-list${loading ? " stale" : ""}`} onKeyDown={onListKey} aria-label={L("Résultats de recherche", "Search results")}>
                  {items.map((a) => (
                    <li key={a.ticker}>
                      <button
                        type="button" data-ticker={a.ticker}
                        className={`mk-row${selected?.ticker === a.ticker ? " on" : ""}`}
                        aria-pressed={selected?.ticker === a.ticker}
                        onClick={() => setSelected(a)}
                      >
                        <TickerLogo ticker={a.ticker} size={36} />
                        <span className="mk-id">
                          <strong>{a.ticker}</strong>
                          <span>{a.name}</span>
                        </span>
                        <span className={`mk-badge ${toneOf(a)}`}>{labelOf(a)}</span>
                        <span className="mk-meta mk-hide-sm">{[a.market, a.currency].filter(Boolean).join(" · ") || "—"}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <aside className="mk-detail" aria-live="polite">
              {selected ? (
                <>
                  <div className="mk-detail-head">
                    <TickerLogo ticker={selected.ticker} size={52} />
                    <div>
                      <h2>{selected.ticker}</h2>
                      <p>{selected.name}</p>
                    </div>
                  </div>
                  <span className={`mk-badge ${toneOf(selected)}`}>{labelOf(selected)}</span>
                  <dl className="mk-facts">
                    <div><dt>{L("Marché", "Market")}</dt><dd>{selected.market ?? "—"}</dd></div>
                    <div><dt>{L("Devise", "Currency")}</dt><dd>{selected.currency ?? "—"}</dd></div>
                    <div className="wide"><dt>{L("Secteur", "Sector")}</dt><dd>{selected.sector ?? "—"}</dd></div>
                  </dl>
                  <p className="mk-note">
                    {L("Ajoutez ce titre à votre portefeuille, puis lancez une analyse depuis la session pour le voir étudié scénario par scénario.", "Add this holding to your portfolio, then start an analysis from the session to see it studied scenario by scenario.")}
                    <InfoTip text={tt("info.marketStats", lang)} />
                  </p>
                  <div className="mk-cta">
                    <Link className="btn" to={`/marches/${encodeURIComponent(selected.ticker)}`}>{L("Voir la fiche", "View details")}</Link>
                    <Link className="btn-ghost" to="/portefeuille">{L("Ajouter au portefeuille", "Add to portfolio")}</Link>
                    <Link className="btn-ghost" to="/chat">{L("Analyser en session", "Analyse in a session")}</Link>
                  </div>
                </>
              ) : (
                <p className="mk-note">{L("Sélectionnez un actif pour voir sa fiche.", "Select an asset to see its details.")}</p>
              )}
            </aside>
          </section>
        )}
      </main>
      <footer className="footer"><div className="wrap footer-row"><span>{L("Simulation pédagogique, pas un conseil financier. Les chiffres affichés ailleurs dans l'outil viennent de l'API et sont sourcés dans le registre de preuves.", "Educational simulation, not financial advice. The figures shown elsewhere in the tool come from the API and are sourced in the evidence registry.")}</span></div></footer>
    </>
  );
}
