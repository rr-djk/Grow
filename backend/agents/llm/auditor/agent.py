"""agent-auditor : rattache chaque règle déclenchée à un passage de la KB (citations KB-nn) et formule messageEn.

Le CODE lance les recherches, pas le modèle. Pour chaque règle (R1…R9) il y a une
recherche par sujet de la règle (RULE_SUBJECTS, exactement, un sujet par
recherche), dont la phrase vient du titre de la règle (RULE_TOPICS) et du motif
déjà calculé par module-rules. Le moteur renvoie ainsi les passages les plus
proches de la RÈGLE, pas de la phrase d'un modèle. Les passages de tous les
sujets sont fusionnés (un par sujet d'abord), dédoublonnés, plafonnés à 5, et
seuls ceux dont la juridiction est dans {CA, province} sont gardés.

Seules les règles déclenchées (warn, fail) sont auditées (lot A) : un pass ou un
not_verified n'a ni recherche ni citation, car un extrait du régulateur à côté
d'une règle « non déclenchée » se lirait comme un accord sur l'idée
(GN-3200-26-001, 2.1.1). Une citation nomme le principe dont la règle s'inspire.

Le modèle ne reçoit aucun outil : il lit les passages de chaque groupe de
verdicts (règle, statut) et répond « P2 soutient la règle » ou « aucun ». Le
code reconstruit la citation à partir de ce que la KB a réellement renvoyé ; une
référence qui n'est pas dans les candidats du groupe est ignorée. Aucun passage
retenu : pas de citation, motif par défaut.
"""

from __future__ import annotations

import contextvars
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from backend.agents.engine.registry import EvidenceRegistry
from backend.agents.llm.auditor import prompts
from backend.agents.llm.auditor.schemas import AuditReport
from backend.agents.llm.base import AgentFailure, run_agent
from backend.agents.observability import log_event
from backend.agents.rules.rules import RULE_SUBJECTS, RULE_TOPICS, needs_regulation
from backend.agents.toolbox import MAX_TOOL_CALLS, TOOLBOX
from backend.agents.tools import kb
from backend.agents.tools.context import RequestContext
from backend.agents.verifier.verifier import forbidden_phrases, handwritten_numbers

AGENT_ID = "agent-auditor"
SEARCH_WORKERS = 4
_SEVERITY = {"fail": 0, "warn": 1, "not_verified": 2, "pass": 3}


def verdict_groups(verdicts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for verdict in verdicts:
        key = f"{verdict['rule']}:{verdict['status']}"
        group = groups.setdefault(key, {
            "key": key, "rule": verdict["rule"], "status": verdict["status"], "reasonCode": verdict["reasonCode"],
            "defaultMessage": verdict["messageEn"], "scenarios": [],
            "thresholdNature": (verdict.get("threshold") or {}).get("nature"),
        })
        if "scenario" in verdict:
            group["scenarios"].append(verdict["scenario"])
    return groups


def _safe_message(message: str, fallback: str) -> str:
    """Un motif avec un chiffre ou une formule interdite retombe sur la phrase par défaut."""
    if not message.strip() or handwritten_numbers(message, set()) or forbidden_phrases(message):
        return fallback
    return message.strip()


def rule_query(rule: str, motive: str) -> str:
    """Phrase de recherche : titre de la règle + motif déjà calculé (anglais, sans chiffre)."""
    return f"{RULE_TOPICS[rule]}. {motive}"[:500]


def _passage_key(passage: dict[str, Any]) -> tuple[str, str]:
    return (passage.get("file") or passage["document"], " ".join(passage["excerpt"].split()))


def merge_passages(per_subject: list[list[tuple[str, dict[str, Any]]]]) -> list[tuple[str, dict[str, Any]]]:
    """Fusionne les résultats des sujets : le meilleur de chaque sujet d'abord, doublons écartés, 5 au plus."""
    merged: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    depth = max((len(found) for found in per_subject), default=0)
    for rank in range(depth):
        for found in per_subject:
            if rank >= len(found):
                continue
            ref, passage = found[rank]
            if _passage_key(passage) in seen:
                continue
            seen.add(_passage_key(passage))
            merged.append((ref, passage))
            if len(merged) == kb.MAX_PASSAGES:
                return merged
    return merged


def _candidates_for(ctx: RequestContext, groups: dict[str, dict[str, Any]]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Passages candidats par règle. Les recherches (une par sujet) tournent en parallèle, 16 au plus."""
    motive: dict[str, tuple[int, str]] = {}
    for group in groups.values():
        rank = _SEVERITY.get(group["status"], 2)
        if group["rule"] not in motive or rank < motive[group["rule"]][0]:
            motive[group["rule"]] = (rank, group["defaultMessage"])
    rules = [r for r in motive if RULE_SUBJECTS.get(r)]
    budget = MAX_TOOL_CALLS.get(AGENT_ID, 16)
    searches = [(r, s) for r in rules for s in RULE_SUBJECTS[r]][:budget]

    def run(item: tuple[str, str]) -> tuple[str, str, list[tuple[str, dict[str, Any]]]]:
        rule, subject = item
        try:
            result = TOOLBOX.call(AGENT_ID, "search_regulation", ctx, query=rule_query(rule, motive[rule][1]), subjects=[subject])
        except Exception as exc:
            log_event("agent.failure", agentId=AGENT_ID, reason=f"search:{type(exc).__name__}", sessionId=ctx.session_id)
            return rule, subject, []
        refs = [p["ref"] for p in result.get("passages", [])]
        return rule, subject, sorted([(ref, ctx.passages[ref]) for ref in refs], key=lambda rp: -rp[1]["score"])

    with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as pool:
        futures = [pool.submit(contextvars.copy_context().run, run, item) for item in searches]
        results = [future.result() for future in futures]
    by_rule: dict[str, list[list[tuple[str, dict[str, Any]]]]] = {}
    for rule, _subject, found in results:
        by_rule.setdefault(rule, []).append(found)
    return {rule: merge_passages(found) for rule, found in by_rule.items()}


def _prompt_groups(groups: dict[str, dict[str, Any]], candidates: dict[str, list[tuple[str, dict[str, Any]]]]) -> list[dict[str, Any]]:
    shown = []
    for group in groups.values():
        shown.append({
            "key": group["key"], "rule": group["rule"], "ruleTitle": RULE_TOPICS[group["rule"]], "status": group["status"],
            "reasonCode": group["reasonCode"], "defaultMessage": group["defaultMessage"],
            "thresholdNature": group["thresholdNature"], "scenarios": group["scenarios"],
            "passages": [
                {"ref": ref, "document": p["document"], "section": p.get("section"), "jurisdiction": p.get("jurisdiction"),
                 "excerpt": kb.neutralize(p["excerpt"])}
                for ref, p in candidates.get(group["rule"], [])
            ],
        })
    return shown


def audit(ctx: RequestContext, verdicts: list[dict[str, Any]], registry: EvidenceRegistry) -> list[dict[str, Any]]:
    """Renvoie les verdicts enrichis (citations, messageEn) ; inscrit les KB-nn au registre."""
    groups = {k: g for k, g in verdict_groups(verdicts).items() if needs_regulation(g["rule"], g["reasonCode"], g["status"])}
    if not groups:
        return verdicts
    candidates = _candidates_for(ctx, groups)
    if not any(candidates.get(g["rule"]) for g in groups.values()):
        return verdicts
    shown = _prompt_groups(groups, candidates)
    try:
        report = run_agent(AGENT_ID, prompts.SYSTEM_PROMPT, prompts.audit_prompt(json.dumps(shown, ensure_ascii=False)), ctx,
                           AuditReport, with_tools=False)
    except AgentFailure as failure:
        log_event("agent.failure", agentId=AGENT_ID, reason=failure.reason, sessionId=ctx.session_id)
        return verdicts
    kb_by_ref: dict[str, str] = {}
    by_key: dict[str, tuple[list[str], str]] = {}
    for item in report.items:
        group = groups.get(item.key)
        if group is None:
            continue
        allowed = dict(candidates.get(group["rule"], []))
        citations: list[str] = []
        for ref in item.passage_refs:
            passage = allowed.get(ref)
            if passage is None:
                continue
            if ref not in kb_by_ref:
                kb_by_ref[ref] = registry.add_regulation(
                    document=passage["document"], section=passage.get("section"), excerpt=passage["excerpt"],
                    jurisdiction=passage["jurisdiction"], url=passage.get("url"),
                    as_of=passage.get("version"), document_type=passage.get("documentType"), regulator=passage.get("regulator"),
                    status=passage.get("status"), section_title=passage.get("sectionTitle"), language=passage.get("language"),
                    source=f"Bedrock Knowledge Base: {passage.get('file') or passage['document']}",
                )
            if kb_by_ref[ref] not in citations:
                citations.append(kb_by_ref[ref])
        by_key[item.key] = (citations, _safe_message(item.message_en, group["defaultMessage"]))
    enriched = []
    for verdict in verdicts:
        citations, message = by_key.get(f"{verdict['rule']}:{verdict['status']}", ([], verdict["messageEn"]))
        enriched.append({**verdict, "citations": citations, "messageEn": message})
    return enriched
