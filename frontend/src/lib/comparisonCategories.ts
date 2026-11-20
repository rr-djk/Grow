export type ComparisonCategoryId =
  | "short-term-bonds" | "aggregate-bonds" | "balanced-allocation"
  | "canadian-equity" | "us-equity" | "global-equity";

export type ComparisonCategory = { id: ComparisonCategoryId; level: number; label: { fr: string; en: string } };

export const COMPARISON_CATEGORIES: ComparisonCategory[] = [
  { id: "short-term-bonds", level: 1, label: { fr: "Obligations canadiennes court terme", en: "Canadian short-term bonds" } },
  { id: "aggregate-bonds", level: 2, label: { fr: "Obligations canadiennes générales", en: "Canadian aggregate bonds" } },
  { id: "balanced-allocation", level: 3, label: { fr: "Répartition d'actifs équilibrée", en: "Balanced asset allocation" } },
  { id: "canadian-equity", level: 3, label: { fr: "Actions canadiennes larges", en: "Broad Canadian equity" } },
  { id: "us-equity", level: 4, label: { fr: "Actions américaines larges", en: "Broad U.S. equity" } },
  { id: "global-equity", level: 4, label: { fr: "Actions mondiales larges", en: "Broad global equity" } },
];

export const categoriesByLevel = (): ComparisonCategory[] =>
  [...COMPARISON_CATEGORIES].sort((a, b) => a.level - b.level || a.id.localeCompare(b.id));

export const isCategoryId = (v: string | undefined | null): v is ComparisonCategoryId =>
  COMPARISON_CATEGORIES.some((c) => c.id === v);

export const categoryOf = (id: string | undefined | null): ComparisonCategory | undefined =>
  COMPARISON_CATEGORIES.find((c) => c.id === id);
