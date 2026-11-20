"""Accès à la table Messages (contrat : db-messages).

Clé : partition sessionId, tri messageId (ULID, donc ordre chronologique).
Le message de l'assistant porte son `explanation` (contrat : schema-message) ;
si un item approche 400 Ko, déplacer explanation dans une table à part.

Les fonctions de ce module ne prennent pas user_id pour lire ou supprimer :
l'appelant vérifie d'abord la propriété avec conversations.get_conversation.
"""

from __future__ import annotations

from typing import Any

from backend.common import config
from backend.common.http import ApiError
from backend.common.ids import new_message_id
from backend.common.repositories import _dynamo

ROLES = ("user", "assistant")
STATUSES = ("done", "pending", "error")

OPTIONAL_ASSISTANT_FIELDS = ("explanation", "quickReplies", "mandateDraft", "runId")


def _to_message(item: dict[str, Any]) -> dict[str, Any]:
    """Item DynamoDB -> schema-message (userId n'est pas exposé)."""
    item = _dynamo.from_dynamo(item)
    message = {
        "messageId": item["messageId"],
        "sessionId": item["sessionId"],
        "role": item["role"],
        "content": item["content"],
        "status": item["status"],
        "createdAt": item["createdAt"],
    }
    for key in OPTIONAL_ASSISTANT_FIELDS:
        if item.get(key) is not None:
            message[key] = item[key]
    return message


def list_messages(session_id: str, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    """Liste les messages d'une conversation, ordre chronologique (par messageId).

    Retourne { items: [schema-message], nextCursor: str | None }.
    `cursor` est la chaîne opaque de la page précédente (None = première page).
    """
    params: dict[str, Any] = {
        "KeyConditionExpression": "sessionId = :s",
        "ExpressionAttributeValues": {":s": session_id},
        "ScanIndexForward": True,
        "Limit": _dynamo.clamp_limit(limit, 50),
    }
    start_key = _dynamo.decode_cursor(cursor, {"sessionId", "messageId"})
    if start_key is not None:
        if start_key["sessionId"] != session_id:
            raise ApiError("VALIDATION_ERROR", "Curseur de pagination invalide.")
        params["ExclusiveStartKey"] = start_key
    response = _dynamo.table(config.messages_table()).query(**params)
    return {
        "items": [_to_message(item) for item in response.get("Items", [])],
        "nextCursor": _dynamo.encode_cursor(response.get("LastEvaluatedKey")),
    }


def put_message(
    session_id: str,
    user_id: str,
    role: str,
    content: str,
    status: str,
    explanation: dict[str, Any] | None = None,
    message_id: str | None = None,
    quick_replies: list[str] | None = None,
    mandate_draft: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Écrit un message (messageId = new_message_id() si non fourni) et le retourne.

    role : 'user' ou 'assistant'. status : 'done', 'pending' ou 'error'.
    explanation, quick_replies, mandate_draft et run_id (schema-message :
    explanation, quickReplies, mandateDraft, runId) ne sont autorisés que pour
    role = 'assistant'.
    Lève ValueError si ces règles ne sont pas respectées (erreur de programmation).
    """
    if role not in ROLES:
        raise ValueError(f"role invalide : {role!r}")
    if status not in STATUSES:
        raise ValueError(f"status invalide : {status!r}")
    optional = {
        "explanation": explanation,
        "quickReplies": quick_replies,
        "mandateDraft": mandate_draft,
        "runId": run_id,
    }
    if role != "assistant":
        for key, value in optional.items():
            if value is not None:
                raise ValueError(f"{key} n'est autorisé que pour role = 'assistant'")
    item: dict[str, Any] = {
        "sessionId": session_id,
        "messageId": message_id or new_message_id(),
        "userId": user_id,
        "role": role,
        "content": content,
        "status": status,
        "createdAt": _dynamo.now_iso(),
    }
    for key, value in optional.items():
        if value is not None:
            item[key] = _dynamo.to_dynamo(value)
    _dynamo.table(config.messages_table()).put_item(Item=item)
    return _to_message(item)


def delete_messages(session_id: str) -> None:
    """Supprime tous les messages d'une conversation (avec la conversation,
    contrat : api-conversations-delete)."""
    table = _dynamo.table(config.messages_table())
    params: dict[str, Any] = {
        "KeyConditionExpression": "sessionId = :s",
        "ExpressionAttributeValues": {":s": session_id},
        "ProjectionExpression": "sessionId, messageId",
    }
    with table.batch_writer() as batch:
        while True:
            response = table.query(**params)
            for key in response.get("Items", []):
                batch.delete_item(Key={"sessionId": key["sessionId"], "messageId": key["messageId"]})
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            params["ExclusiveStartKey"] = last_key
