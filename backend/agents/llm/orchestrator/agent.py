"""agent-orchestrator : tour de conversation (cadrage), refus expliqué et correction des traductions signalées."""

from __future__ import annotations

import json
from typing import Any

from backend.agents import models
from backend.agents.llm.base import run_agent
from backend.agents.llm.orchestrator import prompts
from backend.agents.llm.orchestrator.schemas import OrchestratorTurn, Refusal, TranslationFixes
from backend.agents.tools.context import RequestContext
from backend.agents.verifier.verifier import placeholders

AGENT_ID = "agent-orchestrator"


def history_messages(items: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    """Historique Strands reconstruit depuis la table Messages (texte seulement).

    Les rôles doivent alterner et commencer par l'utilisateur ; un message refusé
    n'est jamais dans la table, donc jamais dans l'historique.
    """
    messages: list[dict[str, Any]] = []
    for item in items[-limit:]:
        role = item.get("role")
        text = (item.get("content") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        if not messages and role != "user":
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"][0]["text"] += "\n" + text
            continue
        messages.append({"role": role, "content": [{"text": text}]})
    if messages and messages[-1]["role"] == "user":
        messages.pop()
    return messages


def converse(ctx: RequestContext, session_context: dict[str, Any], user_message: str,
             history: list[dict[str, Any]]) -> OrchestratorTurn:
    prompt = prompts.turn_prompt(json.dumps(session_context, ensure_ascii=False), user_message)
    output = run_agent(AGENT_ID, prompts.SYSTEM_PROMPT, prompt, ctx, OrchestratorTurn, messages=history)
    assert isinstance(output, OrchestratorTurn)
    return output


def explain_refusal(ctx: RequestContext, topics: list[str], user_message: str, language: str) -> str:
    """Refus expliqué d'une demande bloquée par le Guardrail ; lève AgentFailure en cas d'échec."""
    output = run_agent(
        AGENT_ID, prompts.REFUSAL_SYSTEM_PROMPT, prompts.refusal_prompt(topics, user_message, language),
        ctx, Refusal, with_tools=False, spec=models.TRANSLATION_SPEC,
    )
    assert isinstance(output, Refusal)
    return output.reply.strip()


def fix_translations(ctx: RequestContext, flagged: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Corrections des traductions Amazon Translate signalées par le code : un seul appel pour toutes, sans outil.

    `flagged` : [{item, source, translation, problem}]. Renvoie [{item, find, replace}] ; le code les applique puis
    contrôle de nouveau. Lève AgentFailure en cas d'échec (l'appelant replie sur l'anglais)."""
    if not flagged:
        return []
    output = run_agent(
        AGENT_ID, prompts.TRANSLATE_FIX_PROMPT, prompts.translate_fix_prompt(json.dumps(flagged, ensure_ascii=False)),
        ctx, TranslationFixes, with_tools=False, spec=models.TRANSLATION_SPEC,
    )
    assert isinstance(output, TranslationFixes)
    return [{"item": e.item, "find": e.find, "replace": e.replace} for e in output.fixes]


def placeholders_preserved(source: str, target: str) -> bool:
    return sorted(placeholders(source)) == sorted(placeholders(target))
