"""Contexte d'une requête, transmis aux outils hors de la vue du modèle.

userId, sessionId, runId, portfolioId et juridictions viennent d'ici, jamais
d'un paramètre fourni par le modèle (rule-identity-from-jwt). Le contexte
voyage dans l'invocation (invocation_state de Strands), jamais dans une
variable globale : deux invocations peuvent partager un conteneur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.agents.data.store import DataStore


@dataclass
class RequestContext:
    user_id: str
    session_id: str
    store: DataStore
    message_id: str | None = None
    run_id: str | None = None
    portfolio_id: str = "main"
    province: str | None = None
    user_language: str = "en"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    passages: dict[str, dict[str, Any]] = field(default_factory=dict)
    captured: dict[str, Any] = field(default_factory=dict)
    engine_result: Any = None
    mandate_item: dict[str, Any] | None = None
    clients: dict[str, Any] = field(default_factory=dict)

    @property
    def jurisdictions(self) -> list[str]:
        """Filtre de la KB : textes nationaux + province du mandat (contexte, jamais le modèle)."""
        return ["CA"] + ([self.province] if self.province and self.province != "CA" else [])
