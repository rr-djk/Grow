"""Route POST /v1/conversations/{sessionId}/messages (api-messages-create), synchrone.

Ordre : propriété → Guardrail sur le texte d'origine → orchestrateur (détection
de langue, traduction, cadrage, outils en lecture seule) → Guardrail sur la
traduction anglaise → Guardrail sur la réponse → écriture des deux messages.
Un message refusé n'est jamais écrit : il empoisonnerait l'historique de tous
les tours suivants. Les outils de l'orchestrateur ne modifient rien, donc
contrôler la traduction après coup ne laisse aucun effet de bord.
"""

from __future__ import annotations

import re
from typing import Any

from backend.agents import guardrails, telemetry
from backend.agents.data.store import DataStore
from backend.agents.llm.base import AgentFailure
from backend.agents.llm.orchestrator import agent as orchestrator
from backend.agents.observability import log_event
from backend.agents.pipeline import build_explanation
from backend.agents.tools.context import RequestContext
from backend.common.http import ApiError, json_response
from backend.common.ids import new_message_id
from backend.common.repositories import analyses as analyses_repo
from backend.common.repositories import conversations as conversations_repo
from backend.common.repositories import messages as messages_repo
from backend.common.repositories import portfolios as portfolios_repo
from backend.common.repositories import users as users_repo
from backend.common.validation import parse_json_body, session_id

MAX_CONTENT = 2000
ISO_RE = re.compile(r"^[a-z]{2}$")

TOPIC_KEYS = {
    "Trade execution orders": "orders",
    "Guaranteed or promised returns": "returns",
    "Personalized investment recommendation": "recommendation",
}
SIMULATE_FR = " Vous pouvez plutôt me demander de simuler une idée : indiquez les titres et les montants à tester."
SIMULATE_EN = " You can ask me to simulate an idea instead: name the securities and amounts you want to test."
REFUSAL_TEMPLATES = {
    "fr": {
        "pii": "Votre message semble contenir une donnée personnelle (numéro de compte, NAS ou autre). Retirez-la et reformulez votre demande.",
        "orders": "Cet outil ne passe aucun ordre : c'est une simulation éducative." + SIMULATE_FR,
        "returns": "Cet outil ne promet ni ne garantit aucun rendement : le passé ne prédit pas l'avenir." + SIMULATE_FR,
        "recommendation": "Cet outil ne dit pas quoi acheter, vendre ou conserver : il simule l'effet des changements que vous nommez." + SIMULATE_FR,
        "generic": "Cette demande sort de ce que peut faire cette simulation éducative." + SIMULATE_FR,
    },
    "en": {
        "pii": "Your message seems to contain personal information (account number, SIN or similar). Remove it and rephrase your request.",
        "orders": "This tool places no orders: it is an educational simulation." + SIMULATE_EN,
        "returns": "This tool does not promise or guarantee any return: the past does not predict the future." + SIMULATE_EN,
        "recommendation": "This tool does not say what to buy, sell or hold: it simulates the effect of the changes you name." + SIMULATE_EN,
        "generic": "This request is outside what this educational simulation can do." + SIMULATE_EN,
    },
}


def refusal_message(
    user_id: str, session: str, store: DataStore, check: guardrails.GuardrailResult, content: str, language: str, span: Any, stage: str,
) -> str:
    """Texte du refus affiché dans l'encart : rédigé par l'orchestrateur à partir du sujet bloqué,
    avec repli sur un gabarit. Une donnée personnelle ne quitte jamais le code (aucun appel de modèle)."""
    lang = language.lower() if ISO_RE.match(language.lower()) else "en"
    info = {"blocked": True, "stage": stage, "byPii": check.blocked_by_pii, "byTopic": check.blocked_by_topic, "topics": list(check.blocked_topics)}
    templates = REFUSAL_TEMPLATES.get(lang, REFUSAL_TEMPLATES["en"])
    topics = list(check.blocked_topics)
    if check.blocked_by_pii:
        telemetry.set_span_output(span, {**info, "refusal": "template"})
        return templates["pii"]
    key = next((TOPIC_KEYS[t] for t in topics if t in TOPIC_KEYS), "generic")
    fallback = templates[key]
    if not topics:
        telemetry.set_span_output(span, {**info, "refusal": "template"})
        return fallback
    ctx = RequestContext(user_id=user_id, session_id=session, store=store, user_language=lang)
    try:
        text = orchestrator.explain_refusal(ctx, topics, content, lang)
    except (AgentFailure, AssertionError):
        text = ""
    if text and not guardrails.apply(text, "OUTPUT").blocked:
        telemetry.set_span_output(span, {**info, "refusal": "llm"})
        return text
    telemetry.set_span_output(span, {**info, "refusal": "template"})
    return fallback


def _validate_content(body: dict[str, Any]) -> str:
    unknown = sorted(set(body) - {"content"})
    if unknown:
        raise ApiError("VALIDATION_ERROR", f"Champ(s) non prévu(s) : {', '.join(unknown)}.")
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError("VALIDATION_ERROR", "content doit être une chaîne non vide.")
    if len(content) > MAX_CONTENT:
        raise ApiError("VALIDATION_ERROR", f"content dépasse {MAX_CONTENT} caractères.")
    return content


def _session_context(user_id: str, session: str, conversation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    mandate = analyses_repo.get_latest_mandate(session, user_id)
    run = analyses_repo.get_latest_run(session, user_id)
    profile = (users_repo.get_user(user_id) or {}).get("investorProfile")
    context: dict[str, Any] = {
        "knownUserLanguage": conversation.get("userLanguage"),
        "profileFilled": profile is not None,
        "portfolioEmpty": not ((portfolios_repo.get_portfolio(user_id, "main") or {}).get("holdings")),
        "province": (mandate or {}).get("mandate", {}).get("province") or (profile or {}).get("province"),
    }
    if mandate:
        m = mandate["mandate"]
        context["latestConfirmedMandate"] = {
            "version": mandate["version"], "mode": m["mode"], "objective": m["objective"], "horizonYears": m["horizonYears"],
            "riskProfile": mandate["riskProfile"], "operations": m.get("operations", []), "province": m["province"],
        }
    if run:
        context["latestRun"] = {
            "runId": run["runId"], "status": run["status"], "mandateVersion": run["mandateVersion"],
            "scenarioVerdicts": {str(s["index"]): s["verdict"] for s in run.get("scenarios", [])},
        }
    return context, mandate, run


def post_message(event: dict[str, Any], user_id: str, store: DataStore) -> dict[str, Any]:
    session = session_id(event)
    content = _validate_content(parse_json_body(event))
    conversation = conversations_repo.get_conversation(user_id, session)
    if conversation is None:
        raise ApiError("CONVERSATION_NOT_FOUND", "Conversation inconnue.")

    with telemetry.trace_span(
        "chat-message",
        trace_name="chat-message",
        observation_type="chain",
        session_id=session,
        user_id=user_id,
        tags=["feature:chat"],
        input_data={"content": content, "knownUserLanguage": conversation.get("userLanguage")},
    ) as span:
        check = guardrails.apply(content, "INPUT")
        if check.blocked and (check.blocked_by_pii or not check.blocked_by_topic):
            raise ApiError(
                "GUARDRAIL_BLOCKED",
                refusal_message(user_id, session, store, check, content, conversation.get("userLanguage") or "en", span, "input_original"),
            )

        session_context, mandate, run = _session_context(user_id, session, conversation)
        user_message_id = new_message_id()
        ctx = RequestContext(
            user_id=user_id, session_id=session, store=store, message_id=user_message_id,
            portfolio_id=(mandate or {}).get("mandate", {}).get("portfolioId", "main"),
            province=session_context.get("province"),
            user_language=conversation.get("userLanguage") or "en",
            evidence=(run or {}).get("evidence", []),
            verdicts=(run or {}).get("verdicts", []),
        )
        history = orchestrator.history_messages(messages_repo.list_messages(session, limit=50)["items"])
        try:
            turn = orchestrator.converse(ctx, session_context, content, history)
        except AgentFailure as failure:
            log_event("agent.failure", agentId=orchestrator.AGENT_ID, reason=failure.reason, sessionId=session)
            telemetry.set_span_output(span, {"error": failure.reason})
            if failure.reason == "timeout":
                raise ApiError("AGENT_TIMEOUT", "L'assistant n'a pas répondu à temps.") from failure
            raise ApiError("INTERNAL", "Erreur interne.") from failure

        language = turn.user_language.lower() if ISO_RE.match(turn.user_language.lower()) else ctx.user_language
        if language == "en" and check.blocked:
            raise ApiError("GUARDRAIL_BLOCKED", refusal_message(user_id, session, store, check, content, language, span, "input_original"))
        translated = guardrails.apply(turn.english_request, "INPUT")
        if translated.blocked:
            raise ApiError("GUARDRAIL_BLOCKED", refusal_message(user_id, session, store, translated, content, language, span, "input_translated"))
        reply = guardrails.apply(turn.reply, "OUTPUT").text

        draft = ctx.captured.get("mandateDraft")
        if draft is not None:
            draft = {**draft, "userLanguage": language}
        used_registry = any(c["tool"] == "read_evidence" for c in ctx.tool_calls)
        explanation = build_explanation(
            ctx,
            sources=[{"id": c["tool"], "note": c.get("source")} for c in ctx.tool_calls],
            verdicts=None,
            assumptions=[],
            limitations=["Educational simulation only: no order is placed and nothing here is personalized financial advice."],
        )
        user_message = messages_repo.put_message(session, user_id, "user", content, "done", message_id=user_message_id)
        assistant_message = messages_repo.put_message(
            session, user_id, "assistant", reply, "done", explanation=explanation,
            quick_replies=turn.quick_replies or None, mandate_draft=draft,
            run_id=run["runId"] if (run and used_registry) else None,
        )
        if language != conversation.get("userLanguage"):
            conversations_repo.set_user_language(user_id, session, language)
        conversations_repo.touch_conversation(user_id, session)
        telemetry.set_span_output(
            span,
            {
                "reply": reply,
                "userLanguage": language,
                "hasMandateDraft": draft is not None,
                "quickRepliesCount": len(turn.quick_replies or []),
            },
        )
        return json_response(200, {"userMessage": user_message, "assistantMessage": assistant_message})
