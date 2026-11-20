"""Réponses HTTP JSON et erreurs au format du contrat (schema-error).

Format d'erreur du contrat : { error: { code, message, requestId } }.
Les codes et leurs statuts HTTP viennent de `contract/knowledge-graph.yaml`
(section conventions.error_codes) : c'est la seule source de vérité.
"""

from __future__ import annotations

import json
from typing import Any

HTTP_STATUS_BY_CODE: dict[str, int] = {
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "VALIDATION_ERROR": 400,
    "CONVERSATION_NOT_FOUND": 404,
    "PORTFOLIO_NOT_FOUND": 404,
    "ASSET_NOT_FOUND": 404,
    "MANDATE_NOT_FOUND": 404,
    "RUN_NOT_FOUND": 404,
    "MANDATE_NOT_CONFIRMED": 409,
    "GUARDRAIL_BLOCKED": 422,
    "AGENT_TIMEOUT": 504,
    "INTERNAL": 500,
}

CORS_HEADERS: dict[str, str] = {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Authorization,Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,PUT,DELETE,OPTIONS",
}


class ApiError(Exception):
    """Erreur métier portant un code du contrat, convertie en réponse HTTP standard.

    Le handler d'une Lambda rattrape ApiError et appelle error_response().
    Exemple : raise ApiError("CONVERSATION_NOT_FOUND", "Conversation inconnue.")
    """

    def __init__(self, code: str, message: str, request_id: str | None = None):
        if code not in HTTP_STATUS_BY_CODE:
            raise ValueError(f"Code d'erreur inconnu du contrat : {code}")
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"{code}: {message}")


def json_response(status: int, body: Any) -> dict[str, Any]:
    """Construit une réponse API Gateway HTTP API (JSON, CORS de base)."""
    return {
        "statusCode": status,
        "headers": dict(CORS_HEADERS),
        "body": json.dumps(body, ensure_ascii=False),
    }


def error_response(error: ApiError) -> dict[str, Any]:
    """Construit la réponse d'erreur au format schema-error du contrat."""
    return json_response(
        HTTP_STATUS_BY_CODE[error.code],
        {
            "error": {
                "code": error.code,
                "message": error.message,
                "requestId": error.request_id,
            }
        },
    )


def request_id_from_event(event: dict[str, Any]) -> str | None:
    """RequestId de l'API Gateway (payload v2), pour tracer les erreurs."""
    request_context = event.get("requestContext") or {}
    return request_context.get("requestId")
