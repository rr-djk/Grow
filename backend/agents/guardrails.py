"""Bedrock Guardrails en entrée et en sortie (ApplyGuardrail), contrat srv-bedrock-guardrails.

- Fail-closed sur une décision explicite : un blocage n'est jamais ignoré.
- Fail-open sur une panne (Guardrail non configuré, erreur réseau) : la
  disponibilité de la démo prime ; le prompt de l'orchestrateur et le
  vérificateur restent en place. La panne est journalisée.
Un masquage (ANONYMIZE) n'est pas un blocage : le texte masqué est renvoyé.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.agents import telemetry
from backend.agents.observability import log_event
from backend.common import config

_CLIENT = None

INPUT_CONTEXT_PREFIX = "In the simulator: "


@dataclass
class GuardrailResult:
    blocked: bool
    text: str
    checked: bool
    blocked_by_pii: bool = False
    blocked_by_topic: bool = False
    blocked_topics: tuple[str, ...] = ()


def _client():
    global _CLIENT
    if _CLIENT is None:
        import boto3

        _CLIENT = boto3.client("bedrock-runtime", region_name="us-east-1")
    return _CLIENT


def _has_blocked_action(node: Any) -> bool:
    if isinstance(node, dict):
        if node.get("action") == "BLOCKED":
            return True
        return any(_has_blocked_action(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_blocked_action(v) for v in node)
    return False


def _policy_blocked(assessments: Any, policy_key: str) -> bool:
    if not isinstance(assessments, list):
        return False
    return any(_has_blocked_action(a.get(policy_key)) for a in assessments if isinstance(a, dict))


def _blocked_topic_names(assessments: Any) -> tuple[str, ...]:
    names: list[str] = []
    if isinstance(assessments, list):
        for a in assessments:
            topics = (a.get("topicPolicy") or {}).get("topics") if isinstance(a, dict) else None
            for t in topics or []:
                if isinstance(t, dict) and t.get("action") == "BLOCKED" and t.get("name") and t["name"] not in names:
                    names.append(str(t["name"]))
    return tuple(names)


def apply(text: str, source: str, client=None) -> GuardrailResult:
    """source = 'INPUT' (message utilisateur) ou 'OUTPUT' (texte affiché)."""
    guardrail_id, version = config.guardrail_id(), config.guardrail_version()
    if not text or not guardrail_id or not version:
        return GuardrailResult(False, text, False)
    guarded = INPUT_CONTEXT_PREFIX + text if source == "INPUT" else text
    with telemetry.trace_span(
        f"guardrail.{source.lower()}",
        observation_type="guardrail",
        input_data={"source": source, "textLength": len(text)},
    ) as span:
        try:
            response = (client or _client()).apply_guardrail(
                guardrailIdentifier=guardrail_id, guardrailVersion=version, source=source,
                content=[{"text": {"text": guarded}}],
            )
        except Exception as exc:
            log_event("guardrail.error", source=source, error=type(exc).__name__)
            res = GuardrailResult(False, text, False)
            telemetry.set_span_output(span, {"blocked": res.blocked, "checked": res.checked, "error": type(exc).__name__})
            return res
        outputs = response.get("outputs") or []
        replacement = outputs[0].get("text") if outputs else None
        if replacement and source == "INPUT" and replacement.startswith(INPUT_CONTEXT_PREFIX):
            replacement = replacement[len(INPUT_CONTEXT_PREFIX):]
        if response.get("action") != "GUARDRAIL_INTERVENED":
            res = GuardrailResult(False, text, True)
            telemetry.set_span_output(span, {"blocked": res.blocked, "checked": res.checked})
            return res
        assessments = response.get("assessments")
        if _has_blocked_action(assessments):
            by_pii = _policy_blocked(assessments, "sensitiveInformationPolicy")
            by_topic = _policy_blocked(assessments, "topicPolicy")
            topics = _blocked_topic_names(assessments)
            log_event("guardrail.blocked", source=source, byPii=by_pii, byTopic=by_topic, topics=list(topics))
            res = GuardrailResult(
                True,
                replacement or "This request is outside what this simulation can do.",
                True,
                blocked_by_pii=by_pii,
                blocked_by_topic=by_topic,
                blocked_topics=topics,
            )
            telemetry.set_span_output(
                span,
                {"blocked": res.blocked, "checked": res.checked, "byPii": by_pii, "byTopic": by_topic, "topics": list(topics)},
            )
            return res
        res = GuardrailResult(False, replacement or text, True)
        telemetry.set_span_output(span, {"blocked": res.blocked, "checked": res.checked, "anonymized": True})
        return res
