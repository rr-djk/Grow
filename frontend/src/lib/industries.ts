import DATA from "./industries.json";

export type IndustryEntry = { en: string; fr: string };
export const INDUSTRIES: IndustryEntry[] = DATA;

const LIKED = "Industrie : ";
const AVOIDED = "Industrie à éviter : ";
export type IndustryChoice = { liked: string[]; avoided: string[] };
export const EMPTY_INDUSTRIES: IndustryChoice = { liked: [], avoided: [] };
export const industryPrefs = ({ liked, avoided }: IndustryChoice) => [
  ...liked.map((l) => LIKED + l),
  ...avoided.map((l) => AVOIDED + l),
];
export function splitPreferences(prefs: string[] = []): IndustryChoice & { others: string[] } {
  const known = new Set(INDUSTRIES.map((i) => i.en));
  const liked: string[] = [], avoided: string[] = [], others: string[] = [];
  for (const p of prefs) {
    if (p.startsWith(AVOIDED) && known.has(p.slice(AVOIDED.length))) avoided.push(p.slice(AVOIDED.length));
    else if (p.startsWith(LIKED) && known.has(p.slice(LIKED.length))) liked.push(p.slice(LIKED.length));
    else others.push(p);
  }
  return { liked, avoided, others };
}

export const industryName = (en: string, lang: "fr" | "en") =>
  lang === "fr" ? INDUSTRIES.find((i) => i.en === en)?.fr ?? en : en;

export const normalizeSearch = (text: string) =>
  text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ").trim();

const INDEX = INDUSTRIES.map((i) => ({ ...i, keys: [normalizeSearch(i.en), normalizeSearch(i.fr)] }));

export function searchIndustries(query: string, exclude: string[] = [], limit = 8): IndustryEntry[] {
  const q = normalizeSearch(query);
  if (!q) return [];
  const rank = (keys: string[]) => {
    let best = 99;
    for (const k of keys) {
      if (k.startsWith(q)) best = Math.min(best, 0);
      else if (` ${k}`.includes(` ${q}`)) best = Math.min(best, 1);
      else if (k.includes(q)) best = Math.min(best, 2);
    }
    return best;
  };
  return INDEX.filter((i) => !exclude.includes(i.en))
    .map((i) => ({ i, r: rank(i.keys) }))
    .filter((x) => x.r < 99)
    .sort((a, b) => a.r - b.r || a.i.en.localeCompare(b.i.en))
    .slice(0, limit)
    .map(({ i }) => ({ en: i.en, fr: i.fr }));
}
