export type RuleStatus = "pass" | "warn" | "fail" | "not_verified";
export type RuleFamily = "not_triggered" | "to_check" | "triggered";
export type Lang = "fr" | "en";

type Labels = { fr: string; en: string };

const CODES: Record<string, Labels> = {
  COMPARISON_NOT_REQUESTED: { fr: "pas de comparaison demandée", en: "no comparison requested" },
  COMPARISON_SHOWN: { fr: "comparaison affichée", en: "comparison shown" },
  COMPARISON_UNAVAILABLE: { fr: "comparaison indisponible", en: "comparison unavailable" },
  RISK_PROFILE_RESPECTED: { fr: "non déclenchée", en: "not triggered" },
  IDEA_EXCEEDS_RISK_PROFILE: { fr: "au-dessus du niveau retenu", en: "above the retained level" },
  PORTFOLIO_EXCEEDS_RISK_PROFILE: { fr: "au-dessus du niveau retenu", en: "above the retained level" },
  DRAWDOWN_NOT_COMPUTED: { fr: "non vérifiée", en: "not verified" },
  MAX_LOSS_WITHIN_LIMIT: { fr: "non déclenchée", en: "not triggered" },
  MAX_LOSS_NEAR_LIMIT: { fr: "seuil proche", en: "threshold close" },
  MAX_LOSS_EXCEEDED: { fr: "seuil dépassé", en: "threshold exceeded" },
  EMPTY_PORTFOLIO: { fr: "à vérifier", en: "to check" },
  PORTFOLIO_LEVEL_IMPACT: { fr: "non déclenchée", en: "not triggered" },
  CONCENTRATION_OK: { fr: "non déclenchée", en: "not triggered" },
  CONCENTRATION_ELEVATED: { fr: "seuil d'attention dépassé", en: "attention threshold exceeded" },
  SECTOR_CONCENTRATION_ELEVATED: { fr: "seuil d'attention dépassé", en: "attention threshold exceeded" },
  CONCENTRATION_HIGH: { fr: "seuil dépassé", en: "threshold exceeded" },
  NO_CRYPTO_EXPOSURE: { fr: "non déclenchée", en: "not triggered" },
  CRYPTO_WITHIN_CAP: { fr: "à vérifier", en: "to check" },
  CRYPTO_CAP_EXCEEDED: { fr: "seuil dépassé", en: "threshold exceeded" },
  ESG_NOT_REQUESTED: { fr: "non déclenchée", en: "not triggered" },
  ESG_SOURCED: { fr: "non déclenchée", en: "not triggered" },
  ESG_NOT_VERIFIED: { fr: "à vérifier", en: "to check" },
  NO_SECURITY_RECOMMENDED: { fr: "non déclenchée", en: "not triggered" },
  SECURITY_NAMED: { fr: "déclenchée", en: "triggered" },
  PROVINCE_NOTICES_ADDED: { fr: "non déclenchée", en: "not triggered" },
  MACRO_PUBLICATION_RESPECTED: { fr: "non déclenchée", en: "not triggered" },
  MACRO_USED_BEFORE_PUBLICATION: { fr: "déclenchée", en: "triggered" },
};

const R4_CODES = new Set(["COMPARISON_NOT_REQUESTED", "COMPARISON_SHOWN", "COMPARISON_UNAVAILABLE"]);

const FAMILY_OF_CODE: Record<string, RuleFamily> = {
  COMPARISON_NOT_REQUESTED: "not_triggered",
  COMPARISON_SHOWN: "not_triggered",
  COMPARISON_UNAVAILABLE: "to_check",
  DRAWDOWN_NOT_COMPUTED: "to_check",
  EMPTY_PORTFOLIO: "to_check",
  CRYPTO_WITHIN_CAP: "to_check",
  ESG_NOT_VERIFIED: "to_check",
  SECURITY_NAMED: "triggered",
  MACRO_USED_BEFORE_PUBLICATION: "triggered",
  IDEA_EXCEEDS_RISK_PROFILE: "triggered",
  PORTFOLIO_EXCEEDS_RISK_PROFILE: "triggered",
  MAX_LOSS_EXCEEDED: "triggered",
  CONCENTRATION_HIGH: "triggered",
  CRYPTO_CAP_EXCEEDED: "triggered",
};

const STATUS_FALLBACK: Record<Exclude<RuleStatus, "pass">, Labels> = {
  warn: { fr: "à vérifier", en: "to check" },
  fail: { fr: "déclenchée", en: "triggered" },
  not_verified: { fr: "non vérifiée", en: "not verified" },
};

const PASS_LABEL: Labels = { fr: "non déclenchée", en: "not triggered" };

export function ruleLabel(reasonCode: string, status: RuleStatus, lang: Lang): string {
  const known = CODES[reasonCode];
  if (known) return known[lang];
  if (status === "pass") return PASS_LABEL[lang];
  return STATUS_FALLBACK[status][lang];
}

export function ruleFamily(reasonCode: string, status: RuleStatus): RuleFamily {
  const byCode = FAMILY_OF_CODE[reasonCode];
  if (byCode) return byCode;
  if (status === "pass") return "not_triggered";
  if (status === "not_verified") return "to_check";
  return status === "warn" ? "to_check" : "triggered";
}

export function ruleBadgeClass(reasonCode: string, status: RuleStatus): string {
  const family = ruleFamily(reasonCode, status);
  return family === "not_triggered" ? "badge" : family === "to_check" ? "badge warn" : "badge fail";
}

type VerdictLike = { rule: string; scenario?: number; status: RuleStatus; reasonCode: string };

export function scenarioRuleSummary(verdicts: VerdictLike[], scenarioIndex: number, lang: Lang): string {
  const forScenario = verdicts.filter((v) => v.scenario === scenarioIndex);
  const counts: Record<RuleFamily, number> = { not_triggered: 0, to_check: 0, triggered: 0 };
  for (const v of forScenario) counts[ruleFamily(v.reasonCode, v.status)] += 1;
  const parts: string[] = [];
  const n = forScenario.length;
  if (counts.triggered) parts.push(lang === "fr" ? `${counts.triggered} règle${counts.triggered > 1 ? "s" : ""} déclenchée${counts.triggered > 1 ? "s" : ""}` : `${counts.triggered} rule${counts.triggered > 1 ? "s" : ""} triggered`);
  if (counts.to_check) parts.push(lang === "fr" ? `${counts.to_check} à vérifier` : `${counts.to_check} to check`);
  if (!parts.length) {
    return lang === "fr" ? (n ? "aucune règle déclenchée" : "aucune règle applicable") : (n ? "no rule triggered" : "no rule applies");
  }
  return parts.join(lang === "fr" ? ", " : ", ");
}
