import { useId } from "react";
import { ASSET_CLASSES, assetClassName } from "../lib/assetClasses";
import { useT } from "../lib/i18n";

export default function AssetClassPicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const { lang, L } = useT();
  const name = useId();
  const unknown = value.filter((v) => !ASSET_CLASSES.some((a) => a.code === v));
  const toggle = (code: string) => onChange(value.includes(code) ? value.filter((x) => x !== code) : [...value, code]);
  return (
    <div className="industry-side avoided asset-class-picker">
      <div className="industry-head">
        <strong>{L("Classes d'actifs à exclure", "Asset classes to exclude")}</strong>
        <span className="muted small">{value.length ? L(`${value.length} choisie(s)`, `${value.length} selected`) : L("Aucune pour l'instant", "None yet")}</span>
      </div>
      <div className="opts" role="group" aria-labelledby={name}>
        <span id={name} className="sr-only">{L("Classes d'actifs exclues", "Excluded asset classes")}</span>
        {[...ASSET_CLASSES.map((a) => a.code), ...unknown].map((code) => (
          <label key={code} className={`opt${value.includes(code) ? " on" : ""}`}>
            <input type="checkbox" checked={value.includes(code)} onChange={() => toggle(code)} />
            {assetClassName(code, lang)}
          </label>
        ))}
      </div>
    </div>
  );
}
