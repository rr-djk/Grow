"""Routes POST /conversations/{sessionId}/runs (api-runs-create) et GET …/runs/{runId} (api-runs-get)."""

from __future__ import annotations

from typing import Any, Callable

from backend.agents import pipeline, telemetry
from backend.agents.data.store import DataStore
from backend.agents.observability import log_event
from backend.agents.tools.context import RequestContext
from backend.common.http import ApiError, json_response
from backend.common.repositories import analyses as analyses_repo
from backend.common.repositories import conversations as conversations_repo
from backend.common.validation import parse_json_body, path_parameter, session_id

Dispatcher = Callable[[dict[str, Any]], None] | None


def _ensure_owner(user_id: str, session: str) -> None:
    if conversations_repo.get_conversation(user_id, session) is None:
        raise ApiError("CONVERSATION_NOT_FOUND", "Conversation inconnue.")


def create_run(event: dict[str, Any], user_id: str, store: DataStore, dispatcher: Dispatcher) -> dict[str, Any]:
    session = session_id(event)
    body = parse_json_body(event)
    unknown = sorted(set(body) - {"mandateVersion"})
    if unknown:
        raise ApiError("VALIDATION_ERROR", f"Champ(s) non prévu(s) : {', '.join(unknown)}.")
    version = body.get("mandateVersion")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ApiError("VALIDATION_ERROR", "mandateVersion doit être un entier supérieur ou égal à 1.")
    _ensure_owner(user_id, session)
    with telemetry.trace_span(
        "analysis-run",
        trace_name="analysis-run",
        observation_type="chain",
        session_id=session,
        user_id=user_id,
        tags=["feature:analysis-run"],
        input_data={"mandateVersion": version},
    ) as span:
        ctx = RequestContext(user_id=user_id, session_id=session, store=store)
        run = pipeline.start_run(ctx, version)
        telemetry.set_span_output(
            span,
            {
                "runId": run["runId"],
                "status": run["status"],
                "scenarioVerdicts": {str(s["index"]): s["verdict"] for s in run.get("scenarios", [])},
            },
        )
        trace_ctx = telemetry.inject_trace_context()
        payload = pipeline.completion_payload(user_id, session, run["runId"], trace_context=trace_ctx)
        if dispatcher is None:
            pipeline.complete_run(store, user_id, session, run["runId"], trace_context=trace_ctx)
        else:
            try:
                dispatcher(payload)
            except Exception as exc:
                log_event("run.dispatch_failed", sessionId=session, runId=run["runId"], error=type(exc).__name__)
                analyses_repo.update_run(session, user_id, run["runId"], {"status": "error"})
        return json_response(201, run)


def get_run(event: dict[str, Any], user_id: str) -> dict[str, Any]:
    session = session_id(event)
    run_id = path_parameter(event, "runId")
    _ensure_owner(user_id, session)
    run = analyses_repo.get_run(session, user_id, run_id)
    if run is None:
        raise ApiError("RUN_NOT_FOUND", "Run inconnu.")
    return json_response(200, run)
