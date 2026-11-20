import { EMPTY_INDUSTRIES, industryPrefs, type IndustryChoice } from "./industries";
import { EMPTY_ESG_MARKET, esgMarketPrefs, type EsgMarketChoice } from "./esgMarket";
import type { InvestorProfile, Jurisdiction } from "../api/types";

export type Question = { id: string; label: string; options: string[]; labelEn: string; optionsEn: string[] };
type Lang = "fr" | "en";
export const qLabel = (q: Question, lang: Lang) => (lang === "en" ? q.labelEn : q.label);
export const qOptions = (q: Question, lang: Lang) => (lang === "en" ? q.optionsEn : q.options);

export const QUESTIONS: Question[] = [
  { id: "horizon", label: "Horizon d'investissement",
    options: ["Moins de 2 ans", "2 à 5 ans", "5 à 10 ans", "10 à 20 ans", "Plus de 20 ans"],
    labelEn: "Investment horizon", optionsEn: ["Less than 2 years", "2 to 5 years", "5 to 10 years", "10 to 20 years", "More than 20 years"] },
  { id: "maxLoss", label: "Perte maximale acceptable sur un an",
    options: ["5 %", "10 %", "20 %", "30 %", "40 % ou plus"],
    labelEn: "Maximum acceptable loss over one year", optionsEn: ["5%", "10%", "20%", "30%", "40% or more"] },
  { id: "reaction", label: "Si votre portefeuille perd 20 %, que faites-vous ?",
    options: ["Je vends tout", "Je vends une partie", "J'attends sans rien changer", "Je conserve et je rééquilibre", "J'investis davantage"],
    labelEn: "If your portfolio loses 20%, what do you do?", optionsEn: ["I sell everything", "I sell part of it", "I wait and change nothing", "I hold and rebalance", "I invest more"] },
  { id: "goal", label: "Objectif financier principal",
    options: ["Préserver mon capital", "Obtenir un revenu stable", "Croissance modérée", "Croissance à long terme", "Maximiser la croissance"],
    labelEn: "Main financial goal", optionsEn: ["Preserve my capital", "Earn a steady income", "Moderate growth", "Long-term growth", "Maximise growth"] },
  { id: "capacity", label: "Capacité financière à absorber une perte",
    options: [
      "Très faible : mes dépenses essentielles seraient touchées",
      "Faible : je devrais modifier mes projets",
      "Moyenne : je pourrais absorber une perte limitée",
      "Élevée : peu d'impact sur mes projets",
      "Très élevée : aucun impact significatif sur mes finances",
    ],
    labelEn: "Financial capacity to absorb a loss",
    optionsEn: [
      "Very low: my essential expenses would be affected",
      "Low: I would have to change my plans",
      "Medium: I could absorb a limited loss",
      "High: little impact on my plans",
      "Very high: no significant impact on my finances",
    ] },
];

export const SCORE_MIN = QUESTIONS.length;
export const SCORE_MAX = QUESTIONS.length * 5;

export const PROVINCES: { code: Jurisdiction; label: string; en: string }[] = [
  { code: "QC", label: "Québec", en: "Quebec" }, { code: "ON", label: "Ontario", en: "Ontario" }, { code: "BC", label: "Colombie-Britannique", en: "British Columbia" },
  { code: "AB", label: "Alberta", en: "Alberta" }, { code: "SK", label: "Saskatchewan", en: "Saskatchewan" }, { code: "MB", label: "Manitoba", en: "Manitoba" },
  { code: "NB", label: "Nouveau-Brunswick", en: "New Brunswick" }, { code: "NS", label: "Nouvelle-Écosse", en: "Nova Scotia" },
  { code: "PE", label: "Île-du-Prince-Édouard", en: "Prince Edward Island" }, { code: "NL", label: "Terre-Neuve-et-Labrador", en: "Newfoundland and Labrador" },
  { code: "YT", label: "Yukon", en: "Yukon" }, { code: "NT", label: "Territoires du Nord-Ouest", en: "Northwest Territories" }, { code: "NU", label: "Nunavut", en: "Nunavut" },
];

export const provinceName = (code: Jurisdiction, lang: Lang) => PROVINCES.find((p) => p.code === code)?.[lang === "en" ? "en" : "label"] ?? code;

export const PROVINCE_LABELS: Record<Jurisdiction, string> =
  Object.fromEntries(PROVINCES.map((p) => [p.code, p.label])) as Record<Jurisdiction, string>;

export function totalScore(answers: Record<string, number>): number {
  return QUESTIONS.reduce((sum, q) => sum + answers[q.id] + 1, 0);
}

export type PortfolioRisk = { score: number; answers: Record<string, number>; province?: Jurisdiction; computedAt: string };

const key = (userId: string) => `af.risk.${userId}`;

export function loadRisk(userId: string): Record<string, PortfolioRisk> {
  try {
    const v = JSON.parse(localStorage.getItem(key(userId)) ?? "{}");
    return v && typeof v === "object" && !Array.isArray(v) ? v : {};
  } catch { return {}; }
}

const latestKey = (userId: string) => `af.risk.latest.${userId}`;

export function loadLatestRisk(userId: string): PortfolioRisk | null {
  try {
    const v = JSON.parse(localStorage.getItem(latestKey(userId)) ?? "null");
    return v && typeof v === "object" && v.answers && isComplete(v.answers) ? v : null;
  } catch { return null; }
}

export function saveRisk(userId: string, portfolioIds: string[], answers: Record<string, number>, province?: Jurisdiction): PortfolioRisk {
  const result: PortfolioRisk = { score: totalScore(answers), answers, ...(province ? { province } : {}), computedAt: new Date().toISOString() };
  const all = loadRisk(userId);
  for (const id of portfolioIds) all[id] = result;
  localStorage.setItem(key(userId), JSON.stringify(all));
  localStorage.setItem(latestKey(userId), JSON.stringify(result));
  return result;
}

export function syncRisk(userId: string, portfolioIds: string[]): Record<string, PortfolioRisk> {
  const all = loadRisk(userId);
  const latest = loadLatestRisk(userId);
  const missing = portfolioIds.filter((id) => !all[id]);
  if (latest && missing.length) {
    for (const id of missing) all[id] = latest;
    localStorage.setItem(key(userId), JSON.stringify(all));
  }
  return all;
}

const HORIZONS: [number, number | null][] = [[0, 2], [2, 5], [5, 10], [10, 20], [20, null]];

export function isComplete(answers: Record<string, number>) {
  return QUESTIONS.every((q) => answers[q.id] !== undefined);
}

export type ProfileChoices = EsgMarketChoice & { industries: IndustryChoice };
export const EMPTY_CHOICES: ProfileChoices = { ...EMPTY_ESG_MARKET, industries: EMPTY_INDUSTRIES };

export function profileFromAnswers(answers: Record<string, number>, province?: Jurisdiction, choices: ProfileChoices = EMPTY_CHOICES): InvestorProfile {
  const [min, max] = HORIZONS[answers.horizon];
  const goal = QUESTIONS.find((q) => q.id === "goal")!.options[answers.goal];
  return {
    riskTolerance: answers.maxLoss + 1,
    riskCapacity: answers.capacity + 1,
    ...(province ? { province } : {}),
    horizonMinYears: min,
    ...(max !== null ? { horizonMaxYears: max } : {}),
    objective: goal,
    constraints: [], preferences: [...esgMarketPrefs(choices), ...industryPrefs(choices.industries)], excludedAssetClasses: [],
  };
}
