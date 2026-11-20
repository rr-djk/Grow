"""Chaîne d'un run (contrat api-runs-create) : module-engine → module-rules → [partial]
→ agent-auditor (KB) → agent-writer → traduction (Amazon Translate, section par section) → module-verifier → [done].

La partie déterministe est écrite tout de suite (status = partial) ; la suite est
exécutée par une invocation asynchrone de la Lambda elle-même (événement
interne, pas une route), décision WS5. Le schéma du run ne change pas.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from backend.agents import guardrails, telemetry
from backend.agents.data.store import DataStore
from backend.agents.engine.registry import EvidenceRegistry
from backend.agents.engine.scenarios import attach_allocations, public_scenarios
from backend.agents.llm import base
from backend.agents.llm.auditor import agent as auditor
from backend.agents.llm.orchestrator import agent as orchestrator
from backend.agents.llm.writer import agent as writer
from backend.agents.observability import log_event
from backend.agents.rules.rules import jurisdiction_notices, scenario_verdicts
from backend.agents.rules.settings import settings
from backend.agents.toolbox import TOOLBOX
from backend.agents.tools import notices
from backend.agents.tools.context import RequestContext
from backend.agents.translate import RunTranslator
from backend.agents.verifier.verifier import SECTION_KEYS, verify_narrative
from backend.common.http import ApiError
from backend.common.ids import new_run_id
from backend.common.repositories import analyses as analyses_repo
from backend.common.repositories import portfolios as portfolios_repo

INTERNAL_EVENT = "complete_run"

RULES_VERSION = 2

GENERAL_LIMITATIONS = [
    "Past performance describes the past; it does not predict future returns.",
    "Survivorship bias: the asset universe was selected in 2026.",
    "Educational simulation only: no order is placed and nothing here is personalized financial advice.",
    "The result would be the same for anyone who gives the same answers; Grow takes no position on what is suitable for the user.",
]


def _held_tickers(user_id: str, mandate: dict[str, Any]) -> set[str]:
    """Symboles détenus par l'utilisateur : le récit peut les nommer. Illisible : aucun (le contrôle masque davantage)."""
    try:
        portfolio = portfolios_repo.get_portfolio(user_id, mandate["portfolioId"]) or {}
    except Exception:  # noqa: BLE001 - fail-closed sur le texte, jamais sur le run
        return set()
    return {h["ticker"] for h in portfolio.get("holdings", [])}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def team_assumptions(mandate_item: dict[str, Any]) -> list[str]:
    conf = settings()
    items = [
        f"Analysis window: trailing {conf['windowYears']} years (team assumption).",
        "Risk level implied by annualized volatility bands (team assumption, R1).",
        f"Single-security concentration: warning above {conf['singleSecurity']['warnPct']}%, failure above {conf['singleSecurity']['failPct']}% (team assumption, R6).",
        f"Single-sector concentration (look-through): warning above {conf['singleSecurity'].get('sectorWarnPct', 'n/a')}% (team assumption, R6).",
        "Resampling ranges (90%) come from a moving-block bootstrap with a fixed seed: they show sensitivity to the observed period, not a forecast.",
        "Crypto-asset caps by risk profile (team assumption, R7).",
    ]
    if "maxAcceptableLossPct" not in mandate_item["mandate"]:
        items.append(f"Maximum acceptable loss defaulted to {mandate_item['effectiveMaxLossPct']}% for the horizon (team assumption, R2).")
    return items


def build_explanation(ctx: RequestContext, sources: list[dict[str, Any]], verdicts: list[dict[str, Any]] | None,
                      assumptions: list[str], limitations: list[str]) -> dict[str, Any]:
    """schema-explanation à partir du journal réel de l'exécution (rule-explanation-from-trace)."""
    steps = [
        {k: call[k] for k in ("agentId", "tool", "params", "status", "durationMs") if k in call}
        for call in ctx.tool_calls
    ]
    checks = [
        {"agentId": "agent-auditor" if v.get("citations") else "module-rules", "rule": v["rule"], "status": v["status"],
         "message": v.get("messageEn", ""), "citations": v.get("citations", []), "reasonCode": v["reasonCode"],
         **({"scenario": v["scenario"]} if v.get("scenario") is not None else {})}
        for v in verdicts or []
    ]
    return {"sources": sources, "assumptions": assumptions, "limitations": limitations, "steps": steps, "checks": checks}



def start_run(ctx: RequestContext, mandate_version: int) -> dict[str, Any]:
    """Calcule scénarios, preuves et verdicts ; écrit le run en status = partial et le renvoie."""
    mandate_item = analyses_repo.get_mandate(ctx.session_id, ctx.user_id, mandate_version)
    if mandate_item is None:
        raise ApiError("MANDATE_NOT_FOUND", "Mandat inconnu pour cette conversation.")
    if not mandate_item.get("confirmedAt"):
        raise ApiError("MANDATE_NOT_CONFIRMED", "Le mandat doit être confirmé avant l'analyse.")
    mandate = mandate_item["mandate"]
    ctx.run_id = ctx.run_id or new_run_id()
    ctx.portfolio_id = mandate["portfolioId"]
    ctx.province = mandate["province"]
    ctx.user_language = mandate["userLanguage"]

    TOOLBOX.call("module-engine", "get_portfolio", ctx)
    impact = TOOLBOX.call("module-engine", "portfolio_impact", ctx, mandate_version=mandate_version)
    if "error" in impact:
        raise ApiError("MANDATE_NOT_FOUND", "Mandat inconnu pour cette conversation.")
    result = ctx.engine_result
    with telemetry.trace_span(
        "module-rules.check_rules",
        observation_type="evaluator",
        session_id=ctx.session_id,
        user_id=ctx.user_id,
        input_data={"mandateVersion": mandate_version, "riskProfile": mandate_item["riskProfile"]},
    ) as rules_span:
        verdicts = TOOLBOX.call("module-rules", "check_rules", ctx)["verdicts"]
        telemetry.set_span_output(
            rules_span,
            [{"rule": v["rule"], "scenario": v.get("scenario"), "status": v["status"], "reasonCode": v["reasonCode"]} for v in verdicts],
        )
    if mandate["userLanguage"] == "en":
        verdicts = [{**v, "message": v["messageEn"]} for v in verdicts]
    scenarios = public_scenarios(result, scenario_verdicts(verdicts))
    attach_allocations(ctx.store, result, scenarios)

    limitations = list(GENERAL_LIMITATIONS) + result.warnings + [n for s in result.scenarios for n in s.notes]
    run = {
        "runId": ctx.run_id,
        "sessionId": ctx.session_id,
        "mandateVersion": mandate_version,
        "status": "partial",
        "rulesVersion": RULES_VERSION,
        "datasetVersion": ctx.store.version,
        "userLanguage": mandate["userLanguage"],
        "scenarios": scenarios,
        "verdicts": verdicts,
        "evidence": result.registry.public_items(),
        "jurisdictionNotices": jurisdiction_notices(mandate["province"]),
        "explanation": build_explanation(ctx, result.sources, verdicts, team_assumptions(mandate_item), limitations),
        "createdAt": _now(),
    }
    return analyses_repo.put_run(ctx.session_id, ctx.user_id, run)



def _apply_translations(translator: RunTranslator, sections: list[dict[str, Any]], verdicts: list[dict[str, Any]],
                        notices: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], bool]:
    """Texte affiché de chaque section, motif et mention (traduits par `translator`, déjà lancés pendant le run).

    Renvoie aussi `match` : faux si une section est affichée en anglais parce que sa traduction a échoué
    (erreur de Translate, emplacements perdus, formule interdite ou chiffre ajouté non corrigés)."""
    sections_t, match = [], True
    for section in sections:
        item = translator.section(section["key"], section["textEn"])
        match = match and (item.translated or not translator.active)
        sections_t.append({**section, "text": item.text})
    verdicts_t = [{**v, "message": translator.text(v["messageEn"]).text} for v in verdicts]
    return sections_t, verdicts_t, [translator.text(n).text for n in notices], match


def complete_run(
    store: DataStore,
    user_id: str,
    session_id: str,
    run_id: str,
    *,
    kb_client=None,
    translate_client=None,
    trace_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    run = analyses_repo.get_run(session_id, user_id, run_id)
    if run is None:
        raise ApiError("RUN_NOT_FOUND", "Run inconnu.")
    mandate_item = analyses_repo.get_mandate(session_id, user_id, run["mandateVersion"])
    mandate = mandate_item["mandate"]
    language = run["userLanguage"]
    registry = EvidenceRegistry(language, run["evidence"])
    ctx = RequestContext(user_id=user_id, session_id=session_id, store=store, run_id=run_id,
                         portfolio_id=mandate["portfolioId"], province=mandate["province"], user_language=language,
                         evidence=registry.items,
                         clients={k: c for k, c in (("kb", kb_client), ("translate", translate_client)) if c})
    steps_before = run.get("explanation", {}).get("steps", [])
    with telemetry.trace_span(
        "analysis-complete-run",
        trace_name="analysis-run",
        observation_type="chain",
        session_id=session_id,
        user_id=user_id,
        tags=["feature:analysis-run", f"mode:{mandate['mode']}", f"province:{mandate['province']}"],
        parent_carrier=trace_context,
        input_data={"runId": run_id, "mandateVersion": run["mandateVersion"], "mode": mandate["mode"], "province": mandate["province"]},
    ) as span:
        try:
            narrative: dict[str, Any] | None = None
            verifier_report = None
            notices_en = run.get("jurisdictionNotices", [])
            with RunTranslator(ctx, language) as translator:
                for index, notice in enumerate(notices_en):
                    translator.submit_text(notice, "notice", f"notice:{index}")
                with ThreadPoolExecutor(max_workers=len(SECTION_KEYS)) as pool:
                    early = writer.submit(pool, ctx, writer.analysis_record(mandate, run["scenarios"], run["verdicts"], registry.items),
                                          run["verdicts"], writer.EARLY_KEYS, with_citations=False)
                    translator.follow_sections(early)
                    verdicts = auditor.audit(ctx, run["verdicts"], registry)
                    for verdict in verdicts:
                        translator.submit_text(verdict["messageEn"], "message", f"{verdict['rule']}:{verdict['status']}")
                    late = writer.submit(pool, ctx, writer.analysis_record(mandate, run["scenarios"], verdicts, registry.items),
                                         verdicts, writer.LATE_KEYS, with_citations=True)
                    translator.follow_sections(late)
                    try:
                        sections = writer.collect(ctx, early, late)
                    except base.AgentFailure as failure:
                        log_event("agent.failure", agentId=writer.AGENT_ID, reason=failure.reason, sessionId=session_id)
                        sections = None
                translator.finalize()
                sections_t, verdicts_t, notices_t, match = _apply_translations(translator, sections or [], verdicts, notices_en)
            status = "done"
            if sections is not None:
                with telemetry.trace_span(
                    "module-verifier.verify_narrative",
                    observation_type="evaluator",
                    session_id=session_id,
                    user_id=user_id,
                ) as verifier_span:
                    cleaned, hidden, verifier_report = verify_narrative(
                        sections_t, registry.ids(), mandate, set(store.universe().index), _held_tickers(user_id, mandate),
                        {h["symbol"] for s in run["scenarios"] for h in s.get("holdings") or []})
                    verifier_report["placeholdersMatch"] = verifier_report["placeholdersMatch"] and match
                    telemetry.set_span_output(verifier_span, verifier_report)
                shown = " ".join(s["text"] for s in cleaned)
                check = guardrails.apply(shown, "OUTPUT")
                if check.blocked:
                    hidden = hidden + [{"section": s["key"], "reason": "guardrail"} for s in cleaned if s["text"]]
                    cleaned = [{**s, "text": ""} for s in cleaned]
                narrative = {
                    "sections": [{"key": s["key"], "textEn": s["textEn"], "text": s["text"]} for s in cleaned],
                    "language": language,
                    "hiddenSentences": hidden,
                }
            else:
                status = "error"
            explanation = run.get("explanation", {})
            explanation = {
                **explanation,
                "steps": steps_before + [
                    {k: c[k] for k in ("agentId", "tool", "params", "status", "durationMs") if k in c} for c in ctx.tool_calls
                ],
                "checks": build_explanation(ctx, [], verdicts_t, [], [])["checks"],
            }
            notice_citations = notices.register(registry, mandate["province"])
            fields: dict[str, Any] = {
                "status": status, "verdicts": verdicts_t, "evidence": registry.public_items(),
                "jurisdictionNotices": notices_t, "explanation": explanation, "completedAt": _now(),
            }
            if notice_citations:
                fields["noticeCitations"] = notice_citations
            if narrative is not None:
                fields["narrative"] = narrative
                fields["verifier"] = verifier_report
            telemetry.set_span_output(
                span,
                {
                    "status": status,
                    "citationsCount": sum(1 for item in registry.items if str(item.get("id", "")).startswith("KB-")),
                    "verifier": verifier_report,
                },
            )
            return analyses_repo.update_run(session_id, user_id, run_id, fields)
        except Exception as exc:
            log_event("run.error", sessionId=session_id, runId=run_id, error=type(exc).__name__)
            telemetry.set_span_output(span, {"status": "error", "error": type(exc).__name__})
            return analyses_repo.update_run(session_id, user_id, run_id, {"status": "error", "completedAt": _now()})



def _lambda_invoke(payload: dict[str, Any]) -> None:
    import boto3

    boto3.client("lambda").invoke(
        FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"], InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def default_dispatcher() -> Callable[[dict[str, Any]], None]:
    """Dans Lambda : auto-invocation asynchrone. En local (banc) : None = complétion dans la requête."""
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return _lambda_invoke
    return None  # type: ignore[return-value]


def completion_payload(
    user_id: str,
    session_id: str,
    run_id: str,
    *,
    trace_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"internal": INTERNAL_EVENT, "userId": user_id, "sessionId": session_id, "runId": run_id}
    if trace_context:
        payload["traceContext"] = trace_context
    return payload

