"""Accès à la table Conversations (contrat : db-conversations).

Clé : partition userId, tri sessionId. Index local sur updatedAt pour trier
par récence (contrat : api-conversations-list, plus récentes d'abord).
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from backend.common import config
from backend.common.http import ApiError
from backend.common.ids import new_session_id
from backend.common.repositories import _dynamo

UPDATED_AT_INDEX = "updatedAt-index"

_NOT_FOUND_MESSAGE = "Conversation inconnue."


def _to_conversation(item: dict[str, Any]) -> dict[str, Any]:
    """Item DynamoDB -> schema-conversation (userId n'est pas exposé)."""
    conversation = {
        "sessionId": item["sessionId"],
        "title": item.get("title"),
        "createdAt": item["createdAt"],
        "updatedAt": item["updatedAt"],
    }
    if item.get("userLanguage"):
        conversation["userLanguage"] = item["userLanguage"]
    return conversation


def _raise_not_found(exc: ClientError) -> None:
    """Échec conditionnel -> CONVERSATION_NOT_FOUND ; autre erreur relancée telle quelle."""
    if _dynamo.is_conditional_failure(exc):
        raise ApiError("CONVERSATION_NOT_FOUND", _NOT_FOUND_MESSAGE) from exc
    raise exc


def list_conversations(user_id: str, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
    """Liste les conversations de l'utilisateur, plus récentes d'abord.

    Retourne { items: [schema-conversation], nextCursor: str | None }.
    `cursor` est la chaîne opaque de la page précédente (None = première page).
    """
    params: dict[str, Any] = {
        "IndexName": UPDATED_AT_INDEX,
        "KeyConditionExpression": "userId = :u",
        "ExpressionAttributeValues": {":u": user_id},
        "ScanIndexForward": False,
        "Limit": _dynamo.clamp_limit(limit, 20),
    }
    start_key = _dynamo.decode_cursor(cursor, {"userId", "sessionId", "updatedAt"})
    if start_key is not None:
        if start_key["userId"] != user_id:
            raise ApiError("VALIDATION_ERROR", "Curseur de pagination invalide.")
        params["ExclusiveStartKey"] = start_key
    response = _dynamo.table(config.conversations_table()).query(**params)
    return {
        "items": [_to_conversation(item) for item in response.get("Items", [])],
        "nextCursor": _dynamo.encode_cursor(response.get("LastEvaluatedKey")),
    }


def create_conversation(user_id: str, title: str | None = None) -> dict[str, Any]:
    """Crée une conversation (sessionId = new_session_id()) et la retourne."""
    now = _dynamo.now_iso()
    item: dict[str, Any] = {
        "userId": user_id,
        "sessionId": new_session_id(),
        "createdAt": now,
        "updatedAt": now,
    }
    if title is not None:
        item["title"] = title
    _dynamo.table(config.conversations_table()).put_item(
        Item=item, ConditionExpression="attribute_not_exists(sessionId)"
    )
    return _to_conversation(item)


def get_conversation(user_id: str, session_id: str) -> dict[str, Any] | None:
    """Retourne la conversation si elle appartient à user_id, sinon None.

    Une conversation d'un autre utilisateur est invisible (comme inexistante).
    """
    item = (
        _dynamo.table(config.conversations_table())
        .get_item(Key={"userId": user_id, "sessionId": session_id})
        .get("Item")
    )
    return _to_conversation(item) if item else None


def rename_conversation(user_id: str, session_id: str, title: str) -> dict[str, Any]:
    """Renomme la conversation et la retourne (updatedAt inchangé : le
    renommage ne fait pas remonter la conversation dans la liste).

    Lève ApiError('CONVERSATION_NOT_FOUND') si absente ou non possédée.
    """
    try:
        response = _dynamo.table(config.conversations_table()).update_item(
            Key={"userId": user_id, "sessionId": session_id},
            UpdateExpression="SET title = :t",
            ConditionExpression="attribute_exists(sessionId)",
            ExpressionAttributeValues={":t": title},
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        _raise_not_found(exc)
    return _to_conversation(response["Attributes"])


def touch_conversation(user_id: str, session_id: str) -> None:
    """Met à jour updatedAt (appelé après l'ajout d'un message, contrat :
    srv-agent-runtime a le mode read_update sur db-conversations).

    Lève ApiError('CONVERSATION_NOT_FOUND') si absente ou non possédée
    (l'écriture conditionnelle évite de créer un item fantôme).
    """
    try:
        _dynamo.table(config.conversations_table()).update_item(
            Key={"userId": user_id, "sessionId": session_id},
            UpdateExpression="SET updatedAt = :now",
            ConditionExpression="attribute_exists(sessionId)",
            ExpressionAttributeValues={":now": _dynamo.now_iso()},
        )
    except ClientError as exc:
        _raise_not_found(exc)


def set_user_language(user_id: str, session_id: str, user_language: str) -> None:
    """Enregistre userLanguage (ISO 639-1, détecté par agent-orchestrator).

    updatedAt n'est pas modifié (touch_conversation s'en charge).
    Lève ApiError('CONVERSATION_NOT_FOUND') si absente ou non possédée.
    """
    try:
        _dynamo.table(config.conversations_table()).update_item(
            Key={"userId": user_id, "sessionId": session_id},
            UpdateExpression="SET userLanguage = :lang",
            ConditionExpression="attribute_exists(sessionId)",
            ExpressionAttributeValues={":lang": user_language},
        )
    except ClientError as exc:
        _raise_not_found(exc)


def delete_conversation(user_id: str, session_id: str) -> None:
    """Supprime la conversation (pas ses messages : voir messages.delete_messages).

    Lève ApiError('CONVERSATION_NOT_FOUND') si absente ou non possédée.
    """
    try:
        _dynamo.table(config.conversations_table()).delete_item(
            Key={"userId": user_id, "sessionId": session_id},
            ConditionExpression="attribute_exists(sessionId)",
        )
    except ClientError as exc:
        _raise_not_found(exc)
