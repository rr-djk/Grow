"""Accès à la table Users (contrat : db-users, partition : userId).

Un utilisateur est créé au premier appel de GET /me (contrat : api-me-get) ;
aucun mot de passe n'est stocké ici, Cognito s'en charge.
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from backend.common import config
from backend.common.http import ApiError
from backend.common.repositories import _dynamo


def _to_user(item: dict[str, Any]) -> dict[str, Any]:
    """Item DynamoDB -> schema-user (createdAt est stocké mais pas exposé)."""
    item = _dynamo.from_dynamo(item)
    return {
        "userId": item["userId"],
        "username": item["username"],
        "displayName": item.get("displayName"),
        "baseCurrency": item.get("baseCurrency"),
        "investorProfile": item.get("investorProfile"),
    }


def get_user(user_id: str) -> dict[str, Any] | None:
    """Retourne l'utilisateur (schema-user), ou None s'il n'existe pas encore."""
    item = _dynamo.table(config.users_table()).get_item(Key={"userId": user_id}).get("Item")
    return _to_user(item) if item else None


def put_user_if_absent(
    user_id: str,
    username: str,
    display_name: str | None = None,
    base_currency: str = "CAD",
) -> dict[str, Any]:
    """Crée l'utilisateur au premier appel, sans écraser un profil existant.

    Écriture conditionnelle (attribute_not_exists), donc idempotent.
    Retourne l'utilisateur créé ou celui déjà présent.
    """
    item: dict[str, Any] = {
        "userId": user_id,
        "username": username,
        "baseCurrency": base_currency,
        "createdAt": _dynamo.now_iso(),
    }
    if display_name is not None:
        item["displayName"] = display_name
    try:
        _dynamo.table(config.users_table()).put_item(
            Item=item, ConditionExpression="attribute_not_exists(userId)"
        )
    except ClientError as exc:
        if not _dynamo.is_conditional_failure(exc):
            raise
        existing = get_user(user_id)
        if existing is not None:
            return existing
        raise
    return _to_user(item)


def update_investor_profile(user_id: str, investor_profile: dict[str, Any]) -> dict[str, Any]:
    """Remplace le profil investisseur (schema-investor-profile) en mise à jour
    partielle (les autres attributs sont conservés) et retourne l'utilisateur.

    Lève ApiError('INTERNAL') si l'utilisateur n'existe pas (il doit être créé
    par put_user_if_absent ; le contrat n'a pas de code « utilisateur inconnu »).
    """
    try:
        response = _dynamo.table(config.users_table()).update_item(
            Key={"userId": user_id},
            UpdateExpression="SET investorProfile = :p",
            ConditionExpression="attribute_exists(userId)",
            ExpressionAttributeValues={":p": _dynamo.to_dynamo(investor_profile)},
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if _dynamo.is_conditional_failure(exc):
            raise ApiError("INTERNAL", "Utilisateur inconnu : appeler GET /me d'abord.") from exc
        raise
    return _to_user(response["Attributes"])
