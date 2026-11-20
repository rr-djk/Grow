"""agent-writer : 4 sections en anglais (textEn), avec emplacements {EV-nn}/{KB-nn} seulement.

Fail-open : en cas d'échec, le run reste utilisable (scénarios, verdicts,
citations) et le texte narratif est absent (contrat agents.agent-writer.fail_mode).
"""

from __future__ import annotations

import contextvars
import copy
import json
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

from backend.agents.engine.scenarios import HOLDING_LABEL_PREFIX
from backend.agents.llm.base import run_agent
from backend.agents.llm.writer import prompts
from backend.agents.llm.writer.schemas import SectionText
from backend.agents.toolbox import MAX_TOOL_CALLS
from backend.agents.tools.context import RequestContext
from backend.agents.verifier.verifier import SECTION_KEYS

AGENT_ID = "agent-writer"

EARLY_KEYS = ("data_used", "limits")
LATE_KEYS = ("why", "what_would_change")


def analysis_record(mandate: dict[str, Any], scenarios: list[dict[str, Any]], verdicts: list[dict[str, Any]],
                    evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Ce que lit le rédacteur : tout en anglais, valeurs incluses pour comparer, jamais pour recopier."""
    return {
        "mandate": {k: mandate.get(k) for k in ("mode", "objective", "objectiveDetail", "horizonYears", "province",
                                                 "operations", "subjectTicker", "compareCategory", "preferences", "fieldSources") if mandate.get(k) is not None},
        "scenarios": [{k: s.get(k) for k in ("index", "label", "description", "proxyNote", "verdict", "metrics", "parameters") if s.get(k) is not None} for s in scenarios],
        "verdicts": [{k: v.get(k) for k in ("rule", "scenario", "status", "reasonCode", "messageEn", "evidence", "citations", "threshold") if v.get(k) is not None} for v in verdicts],
        "evidence": [{k: e.get(k) for k in ("id", "kind", "label", "scenario", "value", "window", "currency", "document", "section", "caveats") if e.get(k) is not None}
                     for e in evidence if not str(e.get("label", "")).startswith(HOLDING_LABEL_PREFIX)],
    }


def _write_section(ctx: RequestContext, key: str, record_json: str, *, with_citations: bool, tool_calls: int) -> str:
    output = run_agent(
        AGENT_ID, prompts.section_system_prompt(key, with_citations=with_citations, tool_calls=tool_calls),
        prompts.write_section_prompt(key, record_json), ctx, SectionText, label=key, tool_call_limit=tool_calls,
    )
    return output.text.strip()


@dataclass
class SectionCalls:
    """Un groupe d'appels lancés ensemble : leur contexte propre (journal d'outils à part) et leurs futures."""

    ctx: RequestContext
    futures: dict[str, Future]


def submit(pool: Executor, ctx: RequestContext, record: dict[str, Any], verdicts: list[dict[str, Any]],
           keys: tuple[str, ...], *, with_citations: bool) -> SectionCalls:
    """Lance un appel par section dans `pool`.

    - Le groupe reçoit son propre contexte : journal d'outils à part, registre et verdicts figés (copie) à cet instant.
      Un auditeur qui écrit dans le registre en même temps ne change donc pas ce que lit read_evidence.
      `collect` rapatrie le journal du groupe dans le contexte du run.
    - Plafond d'appels à read_evidence : MAX_TOOL_CALLS['agent-writer'] se partage entre les 4 sections (1 chacune).
    - Le contexte OpenTelemetry est copié dans le thread : les spans restent sous l'analyse (sinon traces orphelines).
    """
    record_json = json.dumps(record, ensure_ascii=False)
    tool_calls = max(1, MAX_TOOL_CALLS[AGENT_ID] // len(SECTION_KEYS))
    group_ctx = replace(ctx, evidence=copy.deepcopy(ctx.evidence), verdicts=copy.deepcopy(verdicts), tool_calls=[])
    return SectionCalls(group_ctx, {
        key: pool.submit(contextvars.copy_context().run, _write_section, group_ctx, key, record_json,
                         with_citations=with_citations, tool_calls=tool_calls)
        for key in keys
    })


def collect(ctx: RequestContext, *groups: SectionCalls) -> list[dict[str, str]]:
    """Attend tous les appels, rapatrie leurs journaux d'outils dans `ctx`, renvoie [{key, textEn}] dans l'ordre de
    SECTION_KEYS. Lève la première erreur (AgentFailure : fail-open côté appelant) une fois tous les appels terminés."""
    texts: dict[str, str] = {}
    failure: BaseException | None = None
    for group in groups:
        for key, future in group.futures.items():
            try:
                texts[key] = future.result()
            except BaseException as exc:  # noqa: BLE001 - tous les appels sont attendus avant de lever
                failure = failure or exc
        ctx.tool_calls.extend(group.ctx.tool_calls)
    if failure is not None:
        raise failure
    return [{"key": key, "textEn": texts[key]} for key in SECTION_KEYS]


def write(ctx: RequestContext, record: dict[str, Any]) -> list[dict[str, str]]:
    """Les 4 sections d'un seul coup, toutes avec le même enregistrement (hors pipeline : tests, banc)."""
    with ThreadPoolExecutor(max_workers=len(SECTION_KEYS)) as pool:
        return collect(ctx, submit(pool, ctx, record, ctx.verdicts, SECTION_KEYS, with_citations=True))
