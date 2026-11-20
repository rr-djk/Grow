"""Point d'entrée de la Lambda agents (provider srv-agent-runtime) : assemblage seulement.

Deux sortes d'événements :
- HTTP API payload v2 (routeKey) : les routes du contrat ;
- événement interne {"internal": "complete_run", ...} : complétion asynchrone
  d'un run, envoyé par la Lambda elle-même (InvocationType=Event). API Gateway
  ne peut pas produire cet événement : un corps HTTP arrive en chaîne dans
  event["body"], jamais à la racine de l'événement.
"""

from __future__ import annotations

from typing import Any, Callable

from backend.agents import pipeline, telemetry
from backend.agents.data.store import DataStore, default_store
from backend.agents.observability import log_event
from backend.agents.routes import asset_detail, market_search, messages, portfolio_summary, runs
from backend.common.auth import get_user_id
from backend.common.http import ApiError, error_response, request_id_from_event

ROUTES = {
    "POST /v1/conversations/{sessionId}/messages": "messages",
    "POST /v1/conversations/{sessionId}/runs": "create_run",
    "GET /v1/conversations/{sessionId}/runs/{runId}": "get_run",
    "GET /v1/portfolios/{portfolioId}/summary": "summary",
    "GET /v1/market/search": "search",
    "GET /v1/market/assets/{ticker}": "asset_detail",
}


def handle_request(event: dict[str, Any], *, store: DataStore | None = None,
                   dispatcher: Callable[[dict[str, Any]], None] | None | str = "default") -> dict[str, Any]:
    """Exécute une requête HTTP ; `store` et `dispatcher` sont injectables pour les tests."""
    request_id = request_id_from_event(event)
    try:
        user_id = get_user_id(event)
        route = ROUTES.get(event.get("routeKey"))
        if route is None:
            raise ApiError("VALIDATION_ERROR", "Route ou méthode non prise en charge.", request_id)
        if route == "get_run":
            return runs.get_run(event, user_id)
        data = store or default_store()
        if route == "messages":
            return messages.post_message(event, user_id, data)
        if route == "create_run":
            chosen = pipeline.default_dispatcher() if dispatcher == "default" else dispatcher
            return runs.create_run(event, user_id, data, chosen)
        if route == "summary":
            return portfolio_summary.portfolio_summary(event, user_id, data)
        if route == "asset_detail":
            return asset_detail.asset_detail(event, user_id, data)
        return market_search.market_search(event, user_id, data)
    except ApiError as error:
        if error.request_id is None:
            error.request_id = request_id
        return error_response(error)
    except Exception as exc:
        log_event("request.error", requestId=request_id, route=event.get("routeKey"), error=type(exc).__name__)
        return error_response(ApiError("INTERNAL", "Erreur interne.", request_id))


def handle_internal(event: dict[str, Any], *, store: DataStore | None = None) -> dict[str, Any]:
    if event.get("internal") != pipeline.INTERNAL_EVENT:
        log_event("internal.unknown", kind=str(event.get("internal")))
        return {"ok": False}
    run = pipeline.complete_run(
        store or default_store(),
        event["userId"],
        event["sessionId"],
        event["runId"],
        trace_context=event.get("traceContext"),
    )
    return {"ok": True, "status": run.get("status")}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Entrée Lambda attendue par l'infra (backend/agents/app.handler)."""
    try:
        if "internal" in event and "requestContext" not in event:
            return handle_internal(event)
        return handle_request(event)
    finally:
        telemetry.flush_telemetry()
