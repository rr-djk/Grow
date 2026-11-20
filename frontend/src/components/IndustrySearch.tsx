import { useState } from "react";
import { useT } from "../lib/i18n";
import { industryName, searchIndustries, type IndustryChoice } from "../lib/industries";

function Side({ side, title, placeholder, value, onChange }: {
  side: keyof IndustryChoice; title: string; placeholder: string; value: IndustryChoice; onChange: (v: IndustryChoice) => void;
}) {
  const { lang, L } = useT();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const other: keyof IndustryChoice = side === "liked" ? "avoided" : "liked";
  const results = searchIndustries(query, value[side]);
  const listId = `industry-${side}-list`;
  const add = (en: string) => {
    onChange({ [side]: [...value[side], en], [other]: value[other].filter((x) => x !== en) } as IndustryChoice);
    setQuery("");
    setActive(0);
  };
  const remove = (en: string) => onChange({ ...value, [side]: value[side].filter((x) => x !== en) });
  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" && results.length) { e.preventDefault(); setActive((a) => (a + 1) % results.length); }
    else if (e.key === "ArrowUp" && results.length) { e.preventDefault(); setActive((a) => (a - 1 + results.length) % results.length); }
    else if (e.key === "Enter" && results[active]) { e.preventDefault(); add(results[active].en); }
    else if (e.key === "Escape") setQuery("");
  };
  return (
    <div className={`industry-side ${side}`}>
      <div className="industry-head">
        <strong>{title}</strong>
        <span className="muted small">{value[side].length ? L(`${value[side].length} choisie(s)`, `${value[side].length} selected`) : L("Aucune pour l'instant", "None yet")}</span>
      </div>
      <div className="field industry-search">
        <input
          type="search" role="combobox" aria-expanded={results.length > 0} aria-controls={listId} aria-label={title}
          placeholder={placeholder} value={query} autoComplete="off"
          onChange={(e) => { setQuery(e.target.value); setActive(0); }} onKeyDown={onKey}
        />
        {query.trim() && (
          <ul className="results" id={listId} role="listbox">
            {results.length === 0 && <li className="muted">{L("Aucune industrie ne correspond.", "No matching industry.")}</li>}
            {results.map((r, idx) => (
              <li key={r.en} role="option" aria-selected={idx === active}>
                <button type="button" className={idx === active ? "active" : ""} onMouseDown={(e) => e.preventDefault()} onClick={() => add(r.en)}>
                  <strong>{lang === "en" ? r.en : r.fr}</strong>
                  <span>{lang === "en" ? r.fr : r.en}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {value[side].length > 0 && (
        <div className="chips">
          {value[side].map((en) => (
            <span key={en} className={`chip ${side === "liked" ? "like" : "avoid"}`}>
              {industryName(en, lang)}
              <button type="button" className="chip-remove" aria-label={L(`Retirer ${industryName(en, lang)}`, `Remove ${industryName(en, lang)}`)} onClick={() => remove(en)}>×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function IndustrySearch({ value, onChange }: { value: IndustryChoice; onChange: (v: IndustryChoice) => void }) {
  const { L } = useT();
  const placeholder = L("Rechercher (ex. pétrole, banques, oil)", "Search (e.g. oil, banks, pétrole)");
  return (
    <div className="industry-picker">
      <Side side="liked" title={L("Industries que j'aime", "Industries I like")} placeholder={placeholder} value={value} onChange={onChange} />
      <Side side="avoided" title={L("Industries à éviter", "Industries to avoid")} placeholder={placeholder} value={value} onChange={onChange} />
    </div>
  );
}
