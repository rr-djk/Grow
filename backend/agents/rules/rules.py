"""module-rules : R1 à R10 (contrat rules_catalog, SOLUTION.md section 9), sans LLM.

Produit des verdicts schema-rule-verdict SANS citations : agent-auditor les
ajoute ensuite depuis la Knowledge Base. messageEn reçoit ici une phrase par
défaut, en anglais et sans chiffre (les chiffres sont dans evidence) : le
verdict reste lisible si l'auditeur échoue. Les seuils d'hypothèse viennent de
rules_config.json et sont marqués threshold.nature = team_assumption.
"""

from __future__ import annotations

from typing import Any

from backend.agents.engine.scenarios import EngineResult, ScenarioAnalysis, _crypto_refused
from backend.agents.engine.concentration import top_sector
from backend.agents.rules.settings import settings

ORDER = {"pass": 0, "not_verified": 0, "warn": 1, "fail": 2}

RULE_TOPICS = {
    "R1": "risk profile is the lower of risk tolerance and risk capacity",
    "R2": "investment time horizon and maximum acceptable loss in suitability",
    "R3": "impact of an investment on the client's overall account or portfolio",
    "R4": "reasonable range of alternative actions",
    "R5": "order-execution-only services must not recommend a specific security",
    "R6": "concentration and diversification of a portfolio",
    "R7": "crypto assets risks and platform registration",
    "R8": "investment funds presenting themselves as ESG",
    "R9": "protected titles financial planner and provincial regulator",
    "R10": "use of macroeconomic data only after its publication",
}

RULE_SUBJECTS = {
    "R1": ["profil_risque", "convenance"],
    "R2": ["kyc", "convenance"],
    "R3": ["profil_risque", "convenance"],
    "R4": ["profil_risque", "convenance"],
    "R5": ["oeo", "aide_decision", "recommandation"],
    "R6": ["convenance"],
    "R7": ["crypto"],
    "R8": ["esg"],
    "R9": ["titres_proteges"],
    "R10": [],
}


NO_SEARCH_REASONS = {"NO_CRYPTO_EXPOSURE", "ESG_NOT_REQUESTED"}


def needs_regulation(rule: str, reason_code: str, status: str) -> bool:
    """Une citation n'existe que pour une règle déclenchée (warn, fail) : un pass ou un not_verified
    n'a rien à fonder, et une citation à côté se lirait comme un accord sur l'idée (GN-3200-26-001, 2.1.1)."""
    return (
        status in ("warn", "fail")
        and bool(RULE_SUBJECTS.get(rule))
        and reason_code not in NO_SEARCH_REASONS
    )


def infer_subjects(query: str) -> list[str]:
    """Déduit les sujets KB d'une requête de l'auditeur si le modèle a omis subjects."""
    q = query.lower()
    for rule, subjects in RULE_SUBJECTS.items():
        if subjects and (rule.lower() in q.split() or f"{rule.lower()}:" in q):
            return list(subjects)
    words = set(q.replace("-", " ").split())
    best_rule, best_overlap = None, 0
    for rule, topic in RULE_TOPICS.items():
        if not RULE_SUBJECTS.get(rule):
            continue
        overlap = len(words & set(topic.lower().replace("-", " ").split()))
        if overlap > best_overlap:
            best_rule, best_overlap = rule, overlap
    return list(RULE_SUBJECTS[best_rule]) if best_rule else []


def _verdict(rule: str, scenario: int | None, status: str, reason: str, message: str,
             evidence: list[str] | None = None, threshold: dict[str, Any] | None = None) -> dict[str, Any]:
    verdict: dict[str, Any] = {
        "rule": rule, "status": status, "reasonCode": reason, "evidence": [e for e in (evidence or []) if e],
        "citations": [], "messageEn": message,
    }
    if scenario is not None:
        verdict["scenario"] = scenario
    if threshold is not None:
        verdict["threshold"] = threshold
    return verdict


def _ev(scenario: ScenarioAnalysis, *keys: str) -> list[str]:
    return [scenario.evidence[k] for k in keys if k in scenario.evidence]


def r1(mandate_item: dict[str, Any], scenario: ScenarioAnalysis) -> dict[str, Any]:
    profile = int(mandate_item["riskProfile"])
    excess_portfolio = (scenario.portfolio_band or 0) - profile if scenario.portfolio_band else 0
    excess_assets = max((a["band"] - profile for a in scenario.idea_assets if a["band"]), default=0)
    excess = max(excess_portfolio, excess_assets)
    evidence = _ev(scenario, "volatility")
    if scenario.index and excess_assets > 0 and excess_assets >= excess_portfolio:
        driving = [a["evidence"] for a in scenario.idea_assets if a["band"] and a["band"] - profile == excess_assets and a.get("evidence")]
        evidence = driving + evidence
    if scenario.index == 0:
        status = "warn" if excess >= 2 else "pass"
    else:
        status = "fail" if excess >= 2 else "warn" if excess == 1 else "pass"
    if status == "pass":
        reason, message = "RISK_PROFILE_RESPECTED", "The scenario's volatility band does not exceed the retained level (the lower of tolerance and capacity)."
    elif excess_assets >= excess_portfolio and scenario.index:
        reason, message = "IDEA_EXCEEDS_RISK_PROFILE", "The tested idea implies a higher risk profile than the retained one, which is the lower of risk tolerance and risk capacity."
    else:
        reason, message = "PORTFOLIO_EXCEEDS_RISK_PROFILE", "The portfolio's volatility implies a higher risk profile than the retained one."
    return _verdict("R1", scenario.index, status, reason, message, evidence,
                    {"value": profile, "nature": "text"})


def r2(mandate_item: dict[str, Any], scenario: ScenarioAnalysis) -> dict[str, Any]:
    limit = float(mandate_item["effectiveMaxLossPct"])
    user_set = "maxAcceptableLossPct" in mandate_item["mandate"]
    threshold = {"value": limit} if user_set else {"value": limit, "nature": "team_assumption"}
    if "maxDrawdown" not in scenario.metrics:
        return _verdict("R2", scenario.index, "not_verified", "DRAWDOWN_NOT_COMPUTED",
                        "The historical drawdown could not be computed for this scenario.", [], threshold)
    loss = abs(scenario.metrics["maxDrawdown"])
    evidence = _ev(scenario, "maxDrawdown", "stress2022", "stressRates", "stressCovid2020", "stressCrypto")
    ratio = float(settings()["maxLossWarnRatio"])
    if loss > limit:
        status, reason, message = "fail", "MAX_LOSS_EXCEEDED", "The worst simulated historical decline exceeds the maximum acceptable loss for this mandate."
    elif loss >= ratio * limit:
        status, reason, message = "warn", "MAX_LOSS_NEAR_LIMIT", "The worst simulated historical decline comes close to the maximum acceptable loss for this mandate."
    else:
        status, reason, message = "pass", "MAX_LOSS_WITHIN_LIMIT", "The worst simulated historical decline does not reach the warning threshold derived from the maximum acceptable loss of this mandate."
    return _verdict("R2", scenario.index, status, reason, message, evidence, threshold)


def r3(scenario: ScenarioAnalysis) -> dict[str, Any]:
    if not scenario.weights:
        return _verdict("R3", scenario.index, "warn", "EMPTY_PORTFOLIO",
                        "The portfolio is empty: the impact cannot be measured on an existing portfolio.")
    return _verdict("R3", scenario.index, "pass", "PORTFOLIO_LEVEL_IMPACT",
                    "The impact is measured on the whole portfolio, not on the added security alone; the rule was not triggered.",
                    _ev(scenario, "volatility", "maxDrawdown"))


def r6(scenario: ScenarioAnalysis) -> dict[str, Any]:
    conf = settings()["singleSecurity"]
    threshold = {"value": conf["warnPct"], "nature": "team_assumption"}
    top = (scenario.concentration or {}).get("topSingle") or {}
    weight = float(top.get("weight") or 0.0)
    evidence = _ev(scenario, "topSingleWeight")
    if weight > conf["failPct"]:
        threshold = {"value": conf["failPct"], "nature": "team_assumption"}
        status, reason, message = "fail", "CONCENTRATION_HIGH", "A single security, including through fund holdings, carries a very large share of the portfolio."
    elif weight > conf["warnPct"]:
        status, reason, message = "warn", "CONCENTRATION_ELEVATED", "A single security, including through fund holdings, carries a large share of the portfolio."
    else:
        status, reason, message = "pass", "CONCENTRATION_OK", "No single security, including through fund holdings, exceeds the concentration warning threshold."
    sector_label, sector_weight = top_sector(scenario.concentration)
    sector_warn = float(conf.get("sectorWarnPct", 0) or 0)
    if sector_warn and status == "pass" and sector_weight > sector_warn:
        threshold = {"value": sector_warn, "nature": "team_assumption"}
        status, reason = "warn", "SECTOR_CONCENTRATION_ELEVATED"
        message = "A single sector, including through fund holdings, carries a large share of the portfolio."
        evidence = _ev(scenario, "topSectorWeight") or evidence
    if scenario.concentration and not scenario.concentration.get("lookThroughComplete", True):
        message += " Fund look-through is incomplete for some funds."
    return _verdict("R6", scenario.index, status, reason, message, evidence, threshold)


def r7(mandate_item: dict[str, Any], scenario: ScenarioAnalysis) -> dict[str, Any]:
    caps = settings()["cryptoCapPct"]
    profile = int(mandate_item["riskProfile"])
    if _crypto_refused(mandate_item["mandate"]):
        cap = caps["excluded"]
    else:
        cap = caps["profileUpTo3"] if profile <= 3 else caps["profileAbove3"]
    weight = float((scenario.concentration or {}).get("cryptoWeight") or 0.0)
    evidence = _ev(scenario, "cryptoWeight", "stressCrypto")
    threshold = {"value": cap, "nature": "team_assumption"}
    if weight <= 0:
        return _verdict("R7", scenario.index, "pass", "NO_CRYPTO_EXPOSURE", "The scenario holds no crypto assets: the rule does not apply.", evidence, threshold)
    if weight > cap:
        return _verdict("R7", scenario.index, "fail", "CRYPTO_CAP_EXCEEDED",
                        "Crypto-asset exposure exceeds the cap for this mandate; crypto assets carry specific platform and custody risks.",
                        evidence, threshold)
    return _verdict("R7", scenario.index, "warn", "CRYPTO_WITHIN_CAP",
                    "Crypto-asset exposure stays within the cap for this mandate, but crypto assets carry specific platform and custody risks.",
                    evidence, threshold)


def r8(store, mandate_item: dict[str, Any], scenario: ScenarioAnalysis) -> dict[str, Any]:
    preferences = mandate_item["mandate"].get("preferences") or {}
    if not preferences.get("esg"):
        return _verdict("R8", scenario.index, "pass", "ESG_NOT_REQUESTED", "The mandate has no ESG preference: the rule does not apply.")
    enriched = store.etf_enriched()
    unverified = []
    for ticker in scenario.weights:
        asset_class = (store.asset(ticker).get("asset_class") or "").lower()
        sheet = enriched.get(ticker) or {}
        if asset_class.startswith("etf") and (sheet.get("exclusions") or sheet.get("esgMethodologyUrl")):
            continue
        unverified.append(ticker)
    if not unverified:
        return _verdict("R8", scenario.index, "pass", "ESG_SOURCED",
                        "Every holding has a published issuer ESG methodology: the rule was not triggered.")
    return _verdict("R8", scenario.index, "warn", "ESG_NOT_VERIFIED",
                    "Some holdings have no published ESG methodology: for equities only the sector is known and controversies are not verified.")


def visible_texts(result: EngineResult) -> list[str]:
    """Texte lisible sans clic : libellés, descriptions et notes des scénarios, libellés de preuve (R5, lot B)."""
    texts: list[str] = []
    for scenario in result.scenarios:
        texts += [scenario.label, scenario.description or "", scenario.proxy_note or ""] + list(scenario.notes)
    texts += [str(item.get("label", "")) for item in result.registry.items]
    return texts


def run_level_rules(result: EngineResult, scenario_verdicts: list[dict[str, Any]], mandate_item: dict[str, Any],
                    universe_tickers: set[str]) -> list[dict[str, Any]]:
    verdicts = []
    mandate = mandate_item["mandate"]
    has_comparison = any(s.index == 2 for s in result.scenarios)
    if not mandate.get("compareCategory"):
        verdicts.append(_verdict("R4", None, "pass", "COMPARISON_NOT_REQUESTED", "No comparison by asset category was requested."))
    elif has_comparison:
        verdicts.append(_verdict("R4", None, "pass", "COMPARISON_SHOWN", "A comparison by asset category is shown as an additional scenario."))
    else:
        verdicts.append(_verdict("R4", None, "not_verified", "COMPARISON_UNAVAILABLE",
                                 "The requested comparison could not be built from the dataset."))

    own = set(result.scenarios[0].positions_cad) | {op["ticker"] for op in mandate.get("operations") or []}
    own |= {mandate["subjectTicker"]} if mandate.get("subjectTicker") else set()
    if mandate.get("mode") == "build":
        own |= {symbol for scenario in result.scenarios if scenario.index == 1 for symbol in scenario.positions_cad}
    texts = " ".join(visible_texts(result))
    named = sorted(t for t in universe_tickers if t and t not in own and _contains_ticker(texts, t))
    if named:
        verdicts.append(_verdict("R5", None, "fail", "SECURITY_NAMED", "A security symbol appears in the visible scenario texts."))
    else:
        verdicts.append(_verdict("R5", None, "pass", "NO_SECURITY_RECOMMENDED",
                                 "No security symbol appears in the visible scenario texts: the rule was not triggered."))

    verdicts.append(_verdict("R9", None, "pass", "PROVINCE_NOTICES_ADDED",
                             "Province notices name the regulator and the protected titles this tool does not use."))

    late = [u for u in result.macro_usage if u.get("publication") is not None and u["publication"] > u["asOf"]]
    if late:
        verdicts.append(_verdict("R10", None, "fail", "MACRO_USED_BEFORE_PUBLICATION", "A macroeconomic value was used before its publication date."))
    else:
        verdicts.append(_verdict("R10", None, "pass", "MACRO_PUBLICATION_RESPECTED",
                                 "Only daily macroeconomic series, known on their observation date, were used: the rule was not triggered."))
    return verdicts


def _contains_ticker(text: str, ticker: str) -> bool:
    import re

    return re.search(rf"(?<![A-Za-z0-9.\-]){re.escape(ticker)}(?![A-Za-z0-9\-])", text) is not None


def check_rules(store, mandate_item: dict[str, Any], result: EngineResult) -> list[dict[str, Any]]:
    """Applique R1-R10 ; renvoie la liste des verdicts (sans citations)."""
    scenario_verdicts: list[dict[str, Any]] = []
    for scenario in result.scenarios:
        scenario_verdicts.extend([
            r1(mandate_item, scenario), r2(mandate_item, scenario), r3(scenario),
            r6(scenario), r7(mandate_item, scenario), r8(store, mandate_item, scenario),
        ])
    universe = set(store.universe().index)
    return scenario_verdicts + run_level_rules(result, scenario_verdicts, mandate_item, universe)


def scenario_verdicts(verdicts: list[dict[str, Any]]) -> dict[int, str]:
    """Verdict d'un scénario = le pire statut de ses règles (not_verified ne compte pas)."""
    worst: dict[int, int] = {}
    for verdict in verdicts:
        if "scenario" not in verdict:
            continue
        worst[verdict["scenario"]] = max(worst.get(verdict["scenario"], 0), ORDER[verdict["status"]])
    names = {0: "pass", 1: "warn", 2: "fail"}
    return {index: names[level] for index, level in worst.items()}


def jurisdiction_notices(province: str) -> list[str]:
    conf = settings()
    notices = conf["provinceNotices"]
    return [notices.get(province, notices["default"]), conf["baseNotice"]]
