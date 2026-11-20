"""Point d'entrée de la Lambda API légère (provider srv-api-light).

Le handler reçoit un événement API Gateway HTTP API payload v2, extrait
l'identité du JWT et route selon `routeKey`. Les routes de srv-agent-runtime
(POST /messages, POST/GET /runs, /summary, /market/search) appartiennent à WS5
et ne sont pas ici.
"""

from __future__ import annotations

from typing import Any, Callable

from backend.api import universe
from backend.api.routes import agents, conversations, mandates, portfolios, speech, users
from backend.common.auth import get_user_id
from backend.common.http import ApiError, error_response, request_id_from_event

ROUTES: dict[str, Callable[..., dict[str, Any]]] = {
    "GET /v1/me": users.get_me,
    "PUT /v1/me/profile": users.put_profile,
    "GET /v1/conversations": conversations.list_conversations,
    "POST /v1/conversations": conversations.create_conversation,
    "PATCH /v1/conversations/{sessionId}": conversations.rename_conversation,
    "DELETE /v1/conversations/{sessionId}": conversations.delete_conversation,
    "GET /v1/conversations/{sessionId}/messages": conversations.list_messages,
    "POST /v1/conversations/{sessionId}/mandates": mandates.create_mandate,
    "GET /v1/conversations/{sessionId}/mandates": mandates.list_mandates,
    "GET /v1/portfolios": portfolios.list_portfolios,
    "PUT /v1/portfolios/{portfolioId}/holdings": portfolios.put_holdings,
    "GET /v1/agents": agents.get_registry,
    "POST /v1/speech/session": speech.create_session,
}


def handle_request(
    event: dict[str, Any], ticker_validator: Callable[[list[str]], None] | None = None
) -> dict[str, Any]:
    """Exécute une requête ; `ticker_validator` est injectable pour les tests."""
    request_id = request_id_from_event(event)
    try:
        user_id = get_user_id(event)
        route = ROUTES.get(event.get("routeKey"))
        if route is None:
            raise ApiError(
                "VALIDATION_ERROR",
                "Route ou méthode non prise en charge.",
                request_id,
            )
        if route in (portfolios.put_holdings, mandates.create_mandate):
            return route(
                event, user_id, ticker_validator or universe.validate_tickers
            )
        return route(event, user_id)
    except ApiError as error:
        if error.request_id is None:
            error.request_id = request_id
        return error_response(error)
    except Exception:
        return error_response(ApiError("INTERNAL", "Erreur interne.", request_id))


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Entrée Lambda attendue par l'infra (backend/api/app.handler)."""
    return handle_request(event)
