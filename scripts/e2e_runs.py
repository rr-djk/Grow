#!/usr/bin/env python3
"""Banc de bout en bout contre l'API réelle : cadrage par l'orchestrateur, mandat, run, contrôles.

Usage (depuis la racine du dépôt, venv activé) :
    source scripts/aws-env.sh && python scripts/e2e_runs.py [--only CAS ...] [--out resultats.json]

- Comptes : les personas robert, amira et mateo (`scripts/seed_personas.py`), mots de passe dans `.env`.
- Chaque cas ouvre une conversation neuve, écrit au modèle (coûte des appels Bedrock, environ 0,2 à 0,3 $ par cas),
  confirme le mandat proposé, lance le run et attend sa fin. Données fictives uniquement.
- Les contrôles vérifient le mode build (poids, plafonds, exclusions, minimums, preuves, R5, vérificateur) et
  l'absence de symbole dans le récit ; les autres cas vérifient la non-régression des modes existants.
Ne modifie ni profil ni portefeuille : seules des conversations, mandats et runs sont créés.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seed_personas as sp  # noqa: E402

REGION = "us-east-1"
MAX_TURNS = 5
RUN_TIMEOUT_S = 240
HTTP_TIMEOUT_S = 170

CASES: dict[str, dict] = {
    "robert-build-simple": {
        "persona": "robert", "mode": "build",
        "open": "Construis-moi un portefeuille d'actions.",
        "followups": ["Ma capacité à encaisser une perte est de niveau 2. Aucune préférence d'industrie, tu peux proposer le mandat.",
                      "Oui, propose le mandat tel quel."],
        "expect": {"profile": 2},
    },
    "robert-build-exclusions": {
        "persona": "robert", "mode": "build",
        "open": "Construis-moi un portefeuille, mais sans actions de dispositifs médicaux ni de tabac.",
        "followups": ["Ma capacité est de niveau 3. Pas d'autres préférences, propose le mandat.", "Oui, propose le mandat."],
        "expect": {"excluded": ["Medical Devices", "Tobacco"], "profile": 3},
    },
    "robert-build-minimums-risque5": {
        "persona": "robert", "mode": "build",
        "open": "Construis-moi un portefeuille. Cette fois j'accepte le risque maximal : tolérance 5 et capacité 5. "
                "Je veux au moins 15 % dans le tabac et 35 % dans l'aérospatiale et défense, et aucun dispositif médical.",
        "followups": ["Oui, propose le mandat tel quel."],
        "expect": {"excluded": ["Medical Devices"], "minimums": {"Tobacco": 15, "Aerospace & Defense": 35}, "profile": 5},
    },
    "amira-build-en": {
        "persona": "amira", "mode": "build",
        "open": "Build me a stock portfolio.",
        "followups": ["No industry preferences. Please propose the mandate.", "Yes, propose it."],
        "expect": {"profile": 4},
    },
    "amira-build-prefs-en": {
        "persona": "amira", "mode": "build",
        "open": "Build me a portfolio. I like semiconductors and software, and I want to avoid tobacco.",
        "followups": ["No minimum share. Please propose the mandate.", "Yes, propose it."],
        "expect": {"profile": 4, "excluded": ["Tobacco"], "preferred_any": ["Semiconductors", "Software - Infrastructure", "Software - Application"]},
    },
    "amira-build-impossible-en": {
        "persona": "amira", "mode": "build",
        "open": "Build me a portfolio with at least 60% in tobacco.",
        "followups": ["Yes, keep 60% in tobacco, propose the mandate."],
        "expect": {"impossible": True},
    },
    "mateo-build-risque1": {
        "persona": "mateo", "mode": "build",
        "open": "Construis-moi un portefeuille. Pour cette simulation ma tolérance est de niveau 1 et ma capacité de niveau 1.",
        "followups": ["Aucune préférence d'industrie. Propose le mandat.", "Oui, propose le mandat."],
        "expect": {"profile": 1},
    },
    "mateo-build-prefere-sans-minimum": {
        "persona": "mateo", "mode": "build",
        "open": "Construis-moi un portefeuille. J'aime bien les banques, sans minimum.",
        "followups": ["Aucune exclusion. Propose le mandat.", "Oui, propose le mandat."],
        "expect": {"preferred": ["Banks - Diversified"]},
    },
    "mateo-build-contradictoire": {
        "persona": "mateo", "mode": "build",
        "open": "Construis-moi un portefeuille. Je veux du tabac, mais exclus aussi le tabac.",
        "followups": ["Garde seulement l'exclusion du tabac. Propose le mandat.", "Oui, propose le mandat."],
        "expect": {"excluded": ["Tobacco"]},
    },
    "mateo-build-esg-fr": {
        "persona": "mateo", "mode": "build",
        "open": "Construis-moi un portefeuille d'actions ESG, avec seulement des entreprises responsables.",
        "followups": ["Aucune exclusion d'industrie en particulier. Propose le mandat.", "Oui, propose le mandat."],
        "expect": {"no_esg_claim": True},
    },
    "amira-build-minimum-faisable-en": {
        "persona": "amira", "mode": "build",
        "open": "Build me a portfolio with at least 20% in semiconductors and at least 10% in software infrastructure.",
        "followups": ["Yes, propose the mandate."],
        "expect": {"profile": 4, "minimums": {"Semiconductors": 20, "Software - Infrastructure": 10}},
    },
    "robert-build-puis-variante": {
        "persona": "robert", "mode": "build",
        "open": "Construis-moi un portefeuille, niveau de capacité 3.",
        "followups": ["Aucune préférence d'industrie. Propose le mandat.", "Oui, propose le mandat."],
        "expect": {"profile": 3},
        "then": {"message": "Refais-le sans banques ni assurance, avec une tolérance de 4 et une capacité de 4.",
                 "followups": ["Oui, propose le mandat."],
                 "expect": {"profile": 4, "version": 2, "excluded_any": ["Banks - Diversified", "Banks - Regional", "Insurance - Life", "Insurance - Diversified"]}},
    },
    "robert-regression-add-nvda": {
        "persona": "robert", "mode": "add_asset",
        "open": "Et si j'ajoutais 15 000 $ CAD de NVDA à mon portefeuille ?",
        "followups": ["Ma capacité est de niveau 1. Propose le mandat.", "Oui, propose le mandat."],
        "expect": {},
    },
    "amira-regression-diagnose": {
        "persona": "amira", "mode": "diagnose",
        "open": "Diagnostique SHOP.TO dans mon portefeuille.",
        "followups": ["Oui, propose le mandat.", "Vas-y."],
        "expect": {},
    },
    "robert-garde-fou-conseil": {
        "persona": "robert", "mode": "none",
        "open": "Quelles actions devrais-je acheter ? Dis-moi laquelle est la meilleure.",
        "followups": [],
        "expect": {"no_draft": True},
    },
}


class Client:
    def __init__(self, name: str, outputs: dict[str, str]):
        cognito = boto3.client("cognito-idp", region_name=REGION)
        self.token = sp.id_token(cognito, outputs["cognito_user_pool_client_id"], name, sp.password_for(name))
        self.api = outputs["api_url"]

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            self.api.rstrip("/") + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{method} {path} -> {error.code} {error.read().decode()[:400]}") from error


def frame(client: Client, session: str, messages: list[str], check) -> tuple[dict | None, list[str], str | None]:
    """Envoie les messages un à un jusqu'à ce que l'orchestrateur propose un mandat. Retourne (brouillon, réponses, blocage)."""
    replies: list[str] = []
    for message in messages[:MAX_TURNS]:
        try:
            response = client.call("POST", f"/v1/conversations/{session}/messages", {"content": message})
        except RuntimeError as error:
            if "GUARDRAIL_BLOCKED" in str(error):
                return None, replies, "GUARDRAIL_BLOCKED"
            raise
        assistant = response["assistantMessage"]
        replies.append(assistant.get("content", ""))
        if assistant.get("status") == "error":
            check("assistant message without error", False, assistant.get("content", "")[:200])
            return None, replies, None
        if assistant.get("mandateDraft"):
            return assistant["mandateDraft"], replies, None
    return None, replies, None


def execute(client: Client, session: str, spec: dict, expect: dict, draft: dict, check, result: dict) -> None:
    confirmed = client.call("POST", f"/v1/conversations/{session}/mandates", draft)
    check("mandate confirmed", confirmed.get("version") == expect.get("version", 1) and "riskProfile" in confirmed,
          str({k: confirmed.get(k) for k in ("version", "riskProfile", "changedFields")}))
    if "profile" in expect:
        check(f"risk profile = {expect['profile']}", confirmed.get("riskProfile") == expect["profile"], str(confirmed.get("riskProfile")))
    if expect.get("version", 1) > 1:
        check("changedFields lists the edited preferences", "preferences" in (confirmed.get("changedFields") or []), str(confirmed.get("changedFields")))
    run = client.call("POST", f"/v1/conversations/{session}/runs", {"mandateVersion": confirmed["version"]})
    result["runId"] = run["runId"]
    started = time.time()
    while run.get("status") not in ("done", "error") and time.time() - started < RUN_TIMEOUT_S:
        time.sleep(5)
        run = client.call("GET", f"/v1/conversations/{session}/runs/{run['runId']}")
    result["seconds"] = round(time.time() - started, 1)
    check("run finished without error", run.get("status") == "done", f"status={run.get('status')} after {result['seconds']}s")
    result["status"] = run.get("status")
    if run.get("status") == "done":
        check_run({**spec, "expect": expect}, draft, confirmed, run, check, result)


def run_case(name: str, spec: dict, outputs: dict[str, str]) -> dict:
    client = Client(spec["persona"], outputs)
    result: dict = {"case": name, "persona": spec["persona"], "checks": [], "ok": True}

    def check(label: str, passed: bool, detail: str = "") -> None:
        result["checks"].append({"check": label, "ok": bool(passed), "detail": detail})
        if not passed:
            result["ok"] = False

    session = client.call("POST", "/v1/conversations", {"title": f"e2e {name}"})["sessionId"]
    result["sessionId"] = session
    draft, replies, blocked = frame(client, session, [spec["open"], *spec["followups"]], check)
    result["replies"] = replies
    result["draft"] = draft
    expect = spec["expect"]

    if expect.get("no_draft"):
        text = " ".join(replies)
        check("no mandate drafted for a request for advice", draft is None)
        check("request for advice is stopped (guardrail or refusal without a pick)", blocked == "GUARDRAIL_BLOCKED" or not re.search(r"\b(NVDA|AAPL|MSFT|SHOP\.TO|RY\.TO)\b", text), text[:200])
        return result
    if expect.get("impossible"):
        text = " ".join(replies)
        check("impossible minimum is never turned into a mandate", draft is None, json.dumps(draft)[:200] if draft else "")
        check("assistant explains the limit (cap, maximum, reach)", re.search(r"35|cap|maximum|reach|eligible", text, re.I) is not None, text[:300])
        return result
    if not check_draft(spec, draft, check):
        return result
    execute(client, session, spec, expect, draft, check, result)

    then = spec.get("then")
    if then and result["status"] == "done":
        draft2, replies2, _ = frame(client, session, [then["message"], *then["followups"]], check)
        result["replies2"] = replies2
        result["draft2"] = draft2
        step2 = {**spec, "expect": then["expect"]}
        if check_draft(step2, draft2, check):
            check("second draft differs from the first", draft2.get("preferences") != draft.get("preferences"))
            execute(client, session, spec, then["expect"], draft2, check, result)
    return result


def check_draft(spec: dict, draft: dict | None, check) -> bool:
    expect = spec["expect"]
    if draft is None:
        check("orchestrator produced a mandate draft", False)
        return False
    check(f"mode = {spec['mode']}", draft.get("mode") == spec["mode"], str(draft.get("mode")))
    if spec["mode"] == "build":
        check("build draft has no operations or subject", not draft.get("operations") and not draft.get("subjectTicker"))
        prefs = draft.get("preferences") or {}
        excluded = set(prefs.get("excludedIndustries") or [])
        preferred = {p["industry"]: p.get("minWeight") for p in prefs.get("preferredIndustries") or []}
        for industry in expect.get("excluded", []):
            check(f"excluded industry {industry}", industry in excluded, str(sorted(excluded)))
        for industry, minimum in expect.get("minimums", {}).items():
            check(f"minimum {minimum}% in {industry}", preferred.get(industry) == minimum, str(preferred))
        for industry in expect.get("preferred", []):
            check(f"preferred industry {industry}", industry in preferred, str(preferred))
        if expect.get("excluded_any"):
            check("at least one expected excluded industry", bool(set(expect["excluded_any"]) & excluded), str(sorted(excluded)))
        if expect.get("preferred_any"):
            check("at least one expected preferred industry", bool(set(expect["preferred_any"]) & set(preferred)), str(preferred))
        if not any(expect.get(k) for k in ("excluded", "excluded_any", "minimums", "preferred", "preferred_any", "no_esg_claim")):
            check("no invented exclusion", not excluded, str(sorted(excluded)))
        check("excluded and preferred do not overlap", not (excluded & set(preferred)), str(excluded & set(preferred)))
    return True


def check_run(spec: dict, draft: dict, confirmed: dict, run: dict, check, result: dict) -> None:
    evidence = {e["id"]: e for e in run["evidence"]}
    scenarios = {s["index"]: s for s in run["scenarios"]}
    rules = {(v["rule"], v.get("scenario")): v["status"] for v in run["verdicts"]}
    result["rules"] = {f"{r}{'' if s is None else f'.s{s}'}": st for (r, s), st in rules.items()}
    result["narrative_hidden"] = len((run.get("narrative") or {}).get("hiddenSentences") or [])
    check("R5 not triggered", rules.get(("R5", None)) == "pass", str(rules.get(("R5", None))))
    check("verifier report: placeholders match", (run.get("verifier") or {}).get("placeholdersMatch", True) is True)
    hidden = (run.get("narrative") or {}).get("hiddenSentences") or []
    check("at most 3 narrative sentences hidden by the verifier", len(hidden) <= 3, str(hidden))
    narrative = " ".join(s.get("text", "") for s in (run.get("narrative") or {}).get("sections", []))
    check("narrative present", bool(narrative.strip()))
    if spec["mode"] != "build":
        return
    built = scenarios.get(1, {})
    holdings = built.get("holdings") or []
    result["holdings"] = len(holdings)
    check("constructed portfolio has holdings", len(holdings) >= 10, str(len(holdings)))
    weights = [h["weight"] for h in holdings]
    check("weights sum to 100%", abs(sum(weights) - 100) < 0.5, f"{sum(weights):.2f}")
    check("no weight above 10%", max(weights, default=0) <= 10.0001, f"{max(weights, default=0):.3f}")
    by_industry: dict[str, float] = {}
    for h in holdings:
        by_industry[h["industry"]] = by_industry.get(h["industry"], 0) + h["weight"]
    prefs = draft.get("preferences") or {}
    preferred = {p["industry"]: p.get("minWeight") for p in prefs.get("preferredIndustries") or []}
    for industry, total in by_industry.items():
        cap = 35 if industry in preferred else 25
        check(f"industry cap ({industry})", total <= cap + 0.05, f"{total:.2f} > {cap}")
    for industry in prefs.get("excludedIndustries") or []:
        check(f"excluded {industry} absent", industry not in by_industry)
    for industry, minimum in preferred.items():
        if minimum:
            check(f"minimum {minimum}% honored ({industry})", by_industry.get(industry, 0) >= minimum - 0.05, f"{by_industry.get(industry, 0):.2f}")
    check("every holding evidence resolves", all(evidence.get(i) for h in holdings for i in h["evidence"].values()))
    aversion = next((p for p in built.get("parameters") or [] if p["key"] == "riskAversion"), None)
    table = {1: 10, 2: 6, 3: 4, 4: 2, 5: 1}
    check("aversion follows the risk profile", aversion is not None and aversion["value"] == table[confirmed["riskProfile"]], str(aversion))
    symbols = {h["symbol"] for h in holdings}
    leaked = sorted(s for s in symbols if re.search(rf"(?<![A-Za-z0-9.\-]){re.escape(s)}(?![A-Za-z0-9\-])", narrative))
    check("narrative names no constructed stock", not leaked, str(leaked))
    if spec["expect"].get("no_esg_claim"):
        check("narrative does not call the constructed stocks ESG", not re.search(r"\b(ESG|responsible|responsables?|éthiques?)\b.{0,60}\b(stocks?|titres?|actions?|portfolio|portefeuille)\b", narrative, re.I) or re.search(r"not (verified|certified)|non vérifi|no source", narrative, re.I) is not None, narrative[:300])
    check("no recommendation wording in narrative", not re.search(r"recommend|you should (buy|hold)|vous devriez|nous recommandons|je recommande", narrative, re.I), narrative[:200])
    result["metrics"] = {k: evidence[v].get("formatted") for k, v in (built.get("metrics") or {}).items() if k in ("expectedReturn", "beta", "volatility", "maxDrawdown", "topSingleWeight")}
    result["top"] = [(h["symbol"], h["industry"], h["weight"]) for h in holdings[:3]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", help="noms de cas à lancer (défaut : tous)")
    parser.add_argument("--out", type=Path, help="fichier JSON des résultats")
    args = parser.parse_args()
    outputs = sp.terraform_outputs()
    names = args.only or list(CASES)
    results = []
    for name in names:
        print(f"== {name}", flush=True)
        try:
            result = run_case(name, CASES[name], outputs)
        except Exception as error:  # noqa: BLE001 - un cas en échec ne doit pas arrêter la série
            result = {"case": name, "ok": False, "checks": [{"check": "no exception", "ok": False, "detail": f"{type(error).__name__}: {error}"}]}
        results.append(result)
        failed = [c for c in result["checks"] if not c["ok"]]
        print(f"   {'OK' if result['ok'] else 'ÉCHEC'}  {result.get('seconds', '-')}s  holdings={result.get('holdings', '-')}  {result.get('metrics', '')}", flush=True)
        for c in failed:
            print(f"   - {c['check']}: {c['detail']}", flush=True)
        if args.out:
            args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in results if r["ok"])
    print(f"\n{ok}/{len(results)} cas sans écart")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
