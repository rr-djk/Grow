export type VolatilityBand = { maxVolatilityPct?: number; band: number };

export const RISK_BANDS: VolatilityBand[] = [
  { maxVolatilityPct: 10, band: 1 },
  { maxVolatilityPct: 14, band: 2 },
  { maxVolatilityPct: 18, band: 3 },
  { maxVolatilityPct: 25, band: 4 },
  { band: 5 },
];

export function bandOfVolatility(volatilityPct: number): number {
  const b = RISK_BANDS.find((b) => b.maxVolatilityPct === undefined || volatilityPct <= b.maxVolatilityPct);
  return b?.band ?? 5;
}

export const retainedLevel = (tolerance: number, capacity: number): number => Math.min(tolerance, capacity);

const LEVELS: Record<number, { fr: string; en: string }> = {
  1: { fr: "1 — Très prudent", en: "1 — Very cautious" },
  2: { fr: "2 — Prudent", en: "2 — Cautious" },
  3: { fr: "3 — Équilibré", en: "3 — Balanced" },
  4: { fr: "4 — Orienté croissance", en: "4 — Growth-oriented" },
  5: { fr: "5 — Très orienté croissance", en: "5 — Very growth-oriented" },
};

export const levelLabel = (level: number, lang: "fr" | "en"): string => LEVELS[level]?.[lang] ?? String(level);

export const levelName = (level: number, lang: "fr" | "en"): string => (LEVELS[level]?.[lang] ?? String(level)).replace(/^\d\s—\s/, "");

const LEVEL_TEXT: Record<number, { fr: string; en: string }> = {
  1: { fr: "Vous privilégiez la stabilité : vous acceptez très peu de variations de la valeur de vos placements.", en: "You favour stability: you accept very little variation in the value of your investments." },
  2: { fr: "Vous acceptez des baisses limitées en échange d'une progression plus régulière.", en: "You accept limited drops in exchange for steadier progress." },
  3: { fr: "Vous acceptez des hauts et des bas modérés pour viser une croissance raisonnable.", en: "You accept moderate ups and downs in pursuit of reasonable growth." },
  4: { fr: "Vous acceptez des baisses marquées pour viser une croissance plus élevée à long terme.", en: "You accept marked drops in pursuit of higher long-term growth." },
  5: { fr: "Vous acceptez de fortes variations, y compris de lourdes pertes temporaires, pour maximiser la croissance.", en: "You accept large swings, including heavy temporary losses, to maximise growth." },
};
export const levelText = (level: number, lang: "fr" | "en"): string => LEVEL_TEXT[level]?.[lang] ?? "";

export const VOLATILITY_ASSUMPTION: Record<"fr" | "en", string> = {
  fr: "Niveau de risque déduit de la volatilité annualisée : ≤ 10 % → 1, ≤ 14 % → 2, ≤ 18 % → 3, ≤ 25 % → 4, au-delà → 5. Hypothèse d'équipe (R1).",
  en: "Risk level implied by annualized volatility: ≤ 10% → 1, ≤ 14% → 2, ≤ 18% → 3, ≤ 25% → 4, above → 5. Team assumption (R1).",
};
