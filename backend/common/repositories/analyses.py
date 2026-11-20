"""Accès à la table Analyses (contrat v0.4.0 : db-analyses).

WS0b fixe ici les signatures, les docstrings et le comportement attendu.
WS2b (branche ws/db-v4) implémente ce module sans changer les signatures.

Clé : partition sessionId, tri itemKey.
- Mandat : itemKey = "MANDATE#<version sur 3 chiffres>" (ex. MANDATE#001), type = "mandate".
- Run    : itemKey = "RUN#<runId>" (runId = ULID, voir backend.common.ids.new_run_id), type = "run".

Chaque item porte userId. Toute lecture vérifie que userId correspond :
une ressource d'un autre utilisateur se comporte comme inexistante (None).

Les objets échangés suivent les schémas du contrat (camelCase) :
schema-mandate pour un mandat, schema-run pour un run.
"""

from __future__ import annotations

from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from backend.common import config
from backend.common.http import ApiError
from backend.common.repositories import _dynamo

MANDATE_PREFIX = "MANDATE#"
RUN_PREFIX = "RUN#"

TYPE_MANDATE = "mandate"
TYPE_RUN = "run"

MAX_VERSION_ATTEMPTS = 5

_INTERNAL_FIELDS = ("userId", "type", "itemKey")

_IMMUTABLE_RUN_FIELDS = frozenset({"sessionId", "itemKey", "userId", "type", "runId"})


def mandate_item_key(version: int) -> str:
    """Clé de tri d'un mandat : MANDATE#001, MANDATE#002…"""
    return f"{MANDATE_PREFIX}{version:03d}"


def run_item_key(run_id: str) -> str:
    """Clé de tri d'un run : RUN#<runId>."""
    return f"{RUN_PREFIX}{run_id}"


def _table() -> Any:
    return _dynamo.table(config.analyses_table())


def _public(item: dict[str, Any]) -> dict[str, Any]:
    """Item DynamoDB -> objet du contrat (sans userId, type ni itemKey)."""
    item = _dynamo.from_dynamo(item)
    return {k: v for k, v in item.items() if k not in _INTERNAL_FIELDS}


def _owned(item: dict[str, Any] | None, user_id: str) -> dict[str, Any] | None:
    """L'item s'il existe et appartient à user_id, sinon None."""
    if not item or item.get("userId") != user_id:
        return None
    return item


def _get_item(session_id: str, item_key: str) -> dict[str, Any] | None:
    return _table().get_item(Key={"sessionId": session_id, "itemKey": item_key}).get("Item")


def _latest_mandate_item(session_id: str) -> dict[str, Any] | None:
    """Dernier mandat de la session, tous utilisateurs confondus (la version est
    partagée par la partition). Le tri sur 3 chiffres suit l'ordre des versions."""
    response = _table().query(
        KeyConditionExpression=Key("sessionId").eq(session_id)
        & Key("itemKey").begins_with(MANDATE_PREFIX),
        ScanIndexForward=False,
        Limit=1,
    )
    items = response.get("Items", [])
    return items[0] if items else None


def _query_all(session_id: str, prefix: str | None, newest_first: bool) -> list[dict[str, Any]]:
    """Tous les items de la session (éventuellement filtrés par préfixe), pagination incluse."""
    condition = Key("sessionId").eq(session_id)
    if prefix:
        condition = condition & Key("itemKey").begins_with(prefix)
    params: dict[str, Any] = {
        "KeyConditionExpression": condition,
        "ScanIndexForward": not newest_first,
    }
    items: list[dict[str, Any]] = []
    while True:
        response = _table().query(**params)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        params["ExclusiveStartKey"] = last_key


def put_mandate(session_id: str, user_id: str, mandate: dict[str, Any]) -> dict[str, Any]:
    """Enregistre une nouvelle version de mandat et la retourne (schema-mandate).

    - version = dernière version de la session + 1 (1 pour le premier mandat) ;
    - écriture conditionnelle (attribute_not_exists sur la clé) pour qu'un appel
      concurrent ne crée jamais deux fois la même version ;
    - `mandate` contient les champs calculés par l'appelant (mandate, riskProfile,
      effectiveMaxLossPct, warnings, changedFields, confirmedAt) ; cette fonction
      ajoute sessionId, version, userId, type et itemKey.
    """
    fields = {k: v for k, v in mandate.items() if k not in ("sessionId", "version", *_INTERNAL_FIELDS)}
    fields.setdefault("confirmedAt", _dynamo.now_iso())
    for _ in range(MAX_VERSION_ATTEMPTS):
        latest = _latest_mandate_item(session_id)
        version = int(latest["version"]) + 1 if latest else 1
        item = {
            **fields,
            "sessionId": session_id,
            "itemKey": mandate_item_key(version),
            "version": version,
            "userId": user_id,
            "type": TYPE_MANDATE,
        }
        try:
            _table().put_item(
                Item=_dynamo.to_dynamo(item),
                ConditionExpression="attribute_not_exists(itemKey)",
            )
        except ClientError as exc:
            if _dynamo.is_conditional_failure(exc):
                continue
            raise
        return _public(item)
    raise ApiError("INTERNAL", "Conflit de version du mandat, réessayez.")


def get_mandate(session_id: str, user_id: str, version: int) -> dict[str, Any] | None:
    """Retourne la version demandée du mandat (schema-mandate), ou None si absente ou non possédée."""
    item = _owned(_get_item(session_id, mandate_item_key(int(version))), user_id)
    return _public(item) if item else None


def get_latest_mandate(session_id: str, user_id: str) -> dict[str, Any] | None:
    """Retourne la version la plus récente du mandat, ou None s'il n'y en a pas."""
    item = _owned(_latest_mandate_item(session_id), user_id)
    return _public(item) if item else None


def list_mandates(session_id: str, user_id: str) -> list[dict[str, Any]]:
    """Retourne toutes les versions du mandat de la session, la plus récente d'abord (schema-mandate-list.items)."""
    return [
        _public(item)
        for item in _query_all(session_id, MANDATE_PREFIX, newest_first=True)
        if item.get("userId") == user_id
    ]


def put_run(session_id: str, user_id: str, run: dict[str, Any]) -> dict[str, Any]:
    """Enregistre un nouveau run (schema-run, en général status = partial) et le retourne.

    `run` contient runId (généré par l'appelant avec ids.new_run_id()) ; cette
    fonction ajoute userId, type et itemKey. Échoue si le runId existe déjà.
    """
    run_id = run["runId"]
    fields = {k: v for k, v in run.items() if k not in ("sessionId", *_INTERNAL_FIELDS)}
    fields.setdefault("createdAt", _dynamo.now_iso())
    item = {
        **fields,
        "sessionId": session_id,
        "itemKey": run_item_key(run_id),
        "userId": user_id,
        "type": TYPE_RUN,
    }
    try:
        _table().put_item(
            Item=_dynamo.to_dynamo(item),
            ConditionExpression="attribute_not_exists(itemKey)",
        )
    except ClientError as exc:
        if _dynamo.is_conditional_failure(exc):
            raise ApiError("INTERNAL", "Identifiant de run déjà utilisé.") from exc
        raise
    return _public(item)


def update_run(session_id: str, user_id: str, run_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Met à jour partiellement un run (UpdateItem) et retourne le run complet.

    Usage typique : passage de partial à done (status, narrative, verifier,
    verdicts enrichis de citations, evidence complétée, completedAt).
    Lève ApiError("RUN_NOT_FOUND") si le run n'existe pas ou n'appartient pas à user_id.
    Lève ValueError si fields touche sessionId, itemKey, userId, type ou runId.
    """
    forbidden = _IMMUTABLE_RUN_FIELDS.intersection(fields)
    if forbidden:
        raise ValueError(f"Champs non modifiables : {sorted(forbidden)}")
    if not fields:
        run = get_run(session_id, user_id, run_id)
        if run is None:
            raise ApiError("RUN_NOT_FOUND", "Run inconnu.")
        return run

    names: dict[str, str] = {"#uid": "userId", "#ik": "itemKey"}
    values: dict[str, Any] = {":uid": user_id}
    assignments = []
    for i, (name, value) in enumerate(fields.items()):
        names[f"#f{i}"] = name
        values[f":v{i}"] = _dynamo.to_dynamo(value)
        assignments.append(f"#f{i} = :v{i}")
    try:
        response = _table().update_item(
            Key={"sessionId": session_id, "itemKey": run_item_key(run_id)},
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression="attribute_exists(#ik) AND #uid = :uid",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if _dynamo.is_conditional_failure(exc):
            raise ApiError("RUN_NOT_FOUND", "Run inconnu.") from exc
        raise
    return _public(response["Attributes"])


def get_run(session_id: str, user_id: str, run_id: str) -> dict[str, Any] | None:
    """Retourne le run (schema-run), ou None s'il est absent ou non possédé."""
    item = _owned(_get_item(session_id, run_item_key(run_id)), user_id)
    return _public(item) if item else None


def get_latest_run(session_id: str, user_id: str) -> dict[str, Any] | None:
    """Dernier run de la session appartenant à user_id (runId ULID : ordre chronologique), sinon None.

    Sert à read_evidence (« registre du dernier run de la session », WS5).
    """
    for item in _query_all(session_id, RUN_PREFIX, newest_first=True):
        if _owned(item, user_id):
            return _public(item)
    return None


def delete_analyses(session_id: str, user_id: str) -> None:
    """Supprime tous les mandats et runs de la session (appelé à la suppression d'une conversation).

    Ne supprime rien si les items n'appartiennent pas à user_id.
    """
    owned = [
        item
        for item in _query_all(session_id, None, newest_first=False)
        if item.get("userId") == user_id
    ]
    if not owned:
        return
    with _table().batch_writer() as batch:
        for item in owned:
            batch.delete_item(Key={"sessionId": item["sessionId"], "itemKey": item["itemKey"]})
