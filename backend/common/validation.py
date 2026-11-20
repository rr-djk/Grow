"""Validation des entrées HTTP (payload v2), partagée par les deux Lambdas.

Seuls les types, champs requis, enums et bornes explicitement écrits dans le
contrat sont vérifiés. Aucune règle supplémentaire n'est inventée : les
contraintes non prévues (longueur d'un titre, unicité des tickers, signe du
prix de revient) ne sont pas appliquées.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import uuid
from typing import Any

from backend.common.categories import category_ids
from backend.common.http import ApiError

MAX_LIMIT = 100


PROVINCES = (
    "QC",
    "ON",
    "BC",
    "AB",
    "SK",
    "MB",
    "NB",
    "NS",
    "PE",
    "NL",
    "YT",
    "NT",
    "NU",
)

MANDATE_MODES = ("add_asset", "rebalance", "diagnose", "build")
MAX_BUILD_AMOUNT = 100_000_000
MANDATE_OBJECTIVES = ("growth", "income", "preservation", "project", "retirement")
OPERATION_ACTIONS = ("add", "remove", "set_weight")
CURRENCIES = ("CAD", "USD")
FIELD_SOURCES = ("persona", "user_answer", "team_assumption", "slider")

MANDATE_FIELDS = (
    "portfolioId",
    "mode",
    "objective",
    "objectiveDetail",
    "horizonYears",
    "riskTolerance",
    "riskCapacity",
    "maxAcceptableLossPct",
    "constraints",
    "preferences",
    "province",
    "userLanguage",
    "operations",
    "subjectTicker",
    "compareCategory",
    "buildAmount",
    "fieldSources",
)


def _validation_error(message: str) -> ApiError:
    return ApiError("VALIDATION_ERROR", message)


def _reject_constant(value: str) -> None:
    """Refuse NaN et Infinity, que json.loads accepte par défaut."""
    raise ValueError(f"valeur JSON non finie : {value}")


def parse_json_body(
    event: dict[str, Any], *, required: bool = True, allow_empty: bool = False
) -> dict[str, Any]:
    """Retourne le corps JSON sous forme d'objet.

    `allow_empty=True` autorise une requête sans corps (POST /conversations,
    dont le seul champ est facultatif). Un corps requis absent est une erreur.
    """
    body = event.get("body")
    if body is None or (isinstance(body, str) and body == ""):
        if required and not allow_empty:
            raise _validation_error("Corps JSON requis.")
        return {}
    if not isinstance(body, str):
        raise _validation_error("Corps JSON invalide.")

    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeError) as exc:
            raise _validation_error("Corps JSON invalide.") from exc
        if body == "":
            if required and not allow_empty:
                raise _validation_error("Corps JSON requis.")
            return {}

    try:
        parsed = json.loads(body, parse_constant=_reject_constant)
    except (ValueError, TypeError) as exc:
        raise _validation_error("Corps JSON invalide.") from exc
    if not isinstance(parsed, dict):
        raise _validation_error("Le corps JSON doit être un objet.")
    return parsed


def _reject_unknown_fields(body: dict[str, Any], allowed: tuple[str, ...]) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        labels = ", ".join(unknown)
        raise _validation_error(f"Champ(s) non prévu(s) : {labels}.")


def _string(body: dict[str, Any], key: str, *, required: bool = True) -> str | None:
    if key not in body:
        if required:
            raise _validation_error(f"Champ requis : {key}.")
        return None
    value = body[key]
    if not isinstance(value, str):
        raise _validation_error(f"{key} doit être une chaîne.")
    return value


def _integer(body: dict[str, Any], key: str, *, required: bool = True) -> int | None:
    if key not in body:
        if required:
            raise _validation_error(f"Champ requis : {key}.")
        return None
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _validation_error(f"{key} doit être un entier.")
    return value


def _number(
    body: dict[str, Any], key: str, *, required: bool = True
) -> int | float | None:
    if key not in body:
        if required:
            raise _validation_error(f"Champ requis : {key}.")
        return None
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _validation_error(f"{key} doit être un nombre.")
    if not math.isfinite(float(value)):
        raise _validation_error(f"{key} doit être un nombre fini.")
    return value


def _array_of_strings(body: dict[str, Any], key: str) -> list[str] | None:
    if key not in body:
        return None
    value = body[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _validation_error(f"{key} doit être un tableau de chaînes.")
    return value


def _validate_risk_score(value: int, key: str) -> int:
    if value < 1 or value > 5:
        raise _validation_error(f"{key} doit être compris entre 1 et 5.")
    return value


def _validate_province(value: str) -> str:
    if value not in PROVINCES:
        values = ", ".join(PROVINCES)
        raise _validation_error(
            f"province doit être une province ou un territoire canadien ({values})."
        )
    return value


def _validate_iso_639_1(value: str) -> str:
    if not (
        len(value) == 2
        and value.isascii()
        and value.isalpha()
        and value.islower()
    ):
        raise _validation_error(
            "userLanguage doit être un code ISO 639-1 à 2 lettres minuscules (ex. fr, en)."
        )
    return value


def validate_investor_profile(body: dict[str, Any]) -> dict[str, Any]:
    """Valide schema-investor-profile et retourne les champs autorisés."""
    _reject_unknown_fields(
        body,
        (
            "riskLevel",
            "riskTolerance",
            "riskCapacity",
            "province",
            "horizonMinYears",
            "horizonMaxYears",
            "objective",
            "constraints",
            "preferences",
            "excludedAssetClasses",
        ),
    )
    _string(body, "riskLevel", required=False)
    risk_tolerance = _integer(body, "riskTolerance")
    assert risk_tolerance is not None
    _validate_risk_score(risk_tolerance, "riskTolerance")
    risk_capacity = _integer(body, "riskCapacity")
    assert risk_capacity is not None
    _validate_risk_score(risk_capacity, "riskCapacity")
    province = _string(body, "province", required=False)
    if province is not None:
        _validate_province(province)
    horizon_min = _integer(body, "horizonMinYears")
    horizon_max = _integer(body, "horizonMaxYears", required=False)
    objective = _string(body, "objective")
    profile: dict[str, Any] = {
        "riskTolerance": risk_tolerance,
        "riskCapacity": risk_capacity,
        "horizonMinYears": horizon_min,
        "objective": objective,
    }
    if province is not None:
        profile["province"] = province
    if horizon_max is not None:
        profile["horizonMaxYears"] = horizon_max
    for key in ("constraints", "preferences", "excludedAssetClasses"):
        value = _array_of_strings(body, key)
        if value is not None:
            profile[key] = value
    return profile


def _validate_mandate_preferences(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _validation_error("preferences doit être un objet.")
    _reject_unknown_fields(
        raw, ("esg", "excludedSectors", "excludedAssetClasses", "excludedIndustries", "preferredIndustries")
    )
    preferences: dict[str, Any] = {}
    if "esg" in raw:
        esg = raw["esg"]
        if not isinstance(esg, bool):
            raise _validation_error("preferences.esg doit être un booléen.")
        preferences["esg"] = esg
    for key in ("excludedSectors", "excludedAssetClasses", "excludedIndustries"):
        values = _array_of_strings(raw, key)
        if values is not None:
            preferences[key] = values
    if "preferredIndustries" in raw:
        preferences["preferredIndustries"] = _validate_preferred_industries(raw["preferredIndustries"])
    return preferences


def _validate_preferred_industries(raw: Any) -> list[dict[str, Any]]:
    """Industries préférées du mode build : [{ industry, minWeight }], minWeight en % (facultatif, null = bonus seulement)."""
    if not isinstance(raw, list):
        raise _validation_error("preferences.preferredIndustries doit être un tableau.")
    items: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise _validation_error("Chaque industrie préférée doit être un objet { industry, minWeight }.")
        _reject_unknown_fields(entry, ("industry", "minWeight"))
        industry = _string(entry, "industry")
        if not industry:
            raise _validation_error("preferredIndustries.industry ne peut pas être vide.")
        item: dict[str, Any] = {"industry": industry}
        minimum = entry.get("minWeight")
        if minimum is not None:
            if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not 0 <= minimum <= 100:
                raise _validation_error("preferredIndustries.minWeight doit être un nombre entre 0 et 100 (en %) ou null.")
            item["minWeight"] = minimum
        items.append(item)
    return items


def _validate_operation(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _validation_error("Chaque opération doit être un objet.")
    _reject_unknown_fields(
        raw, ("action", "ticker", "amount", "weight", "currency")
    )
    action = _string(raw, "action")
    if action not in OPERATION_ACTIONS:
        values = ", ".join(OPERATION_ACTIONS)
        raise _validation_error(f"action doit être l'un de : {values}.")
    ticker = _string(raw, "ticker")
    if not ticker:
        raise _validation_error("ticker ne peut pas être vide.")
    operation: dict[str, Any] = {"action": action, "ticker": ticker}
    amount = _number(raw, "amount", required=False)
    if amount is not None:
        if amount <= 0:
            raise _validation_error("amount doit être supérieur à 0.")
        operation["amount"] = amount
    weight = _number(raw, "weight", required=False)
    if weight is not None:
        if weight < 0 or weight > 100:
            raise _validation_error("weight doit être compris entre 0 et 100.")
        operation["weight"] = weight
    currency = _string(raw, "currency", required=False)
    if currency is not None:
        if currency not in CURRENCIES:
            values = ", ".join(CURRENCIES)
            raise _validation_error(f"currency doit être l'un de : {values}.")
        operation["currency"] = currency
    if action == "add" and "amount" not in operation:
        raise _validation_error("add exige un amount (montant dans currency) ; weight n'est valide que pour set_weight.")
    if action == "set_weight" and "weight" not in operation:
        raise _validation_error("set_weight exige un weight (poids cible en %).")
    if action in ("add", "remove") and "weight" in operation:
        raise _validation_error(f"{action} n'accepte pas weight : utiliser amount (ou set_weight pour un poids cible).")
    if action == "set_weight" and "amount" in operation:
        raise _validation_error("set_weight n'accepte pas amount : utiliser weight (poids cible en %).")
    return operation


def _validate_field_sources(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise _validation_error("fieldSources doit être un objet.")
    sources: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise _validation_error("Chaque clé de fieldSources doit être une chaîne.")
        if not isinstance(value, str) or value not in FIELD_SOURCES:
            values = ", ".join(FIELD_SOURCES)
            raise _validation_error(
                f"fieldSources[{key}] doit être l'un de : {values}."
            )
        sources[key] = value
    return sources


def validate_mandate_create(body: dict[str, Any]) -> dict[str, Any]:
    """Valide schema-mandate-create-request et retourne le mandat normalisé."""
    _reject_unknown_fields(body, MANDATE_FIELDS)

    portfolio_id = _string(body, "portfolioId")
    if not portfolio_id:
        raise _validation_error("portfolioId ne peut pas être vide.")

    mode = _string(body, "mode")
    if mode not in MANDATE_MODES:
        values = ", ".join(MANDATE_MODES)
        raise _validation_error(f"mode doit être l'un de : {values}.")

    objective = _string(body, "objective")
    if objective not in MANDATE_OBJECTIVES:
        values = ", ".join(MANDATE_OBJECTIVES)
        raise _validation_error(f"objective doit être l'un de : {values}.")

    horizon_years = _number(body, "horizonYears")
    assert horizon_years is not None
    if horizon_years <= 0:
        raise _validation_error("horizonYears doit être supérieur à 0.")

    risk_tolerance = _integer(body, "riskTolerance")
    assert risk_tolerance is not None
    _validate_risk_score(risk_tolerance, "riskTolerance")

    risk_capacity = _integer(body, "riskCapacity")
    assert risk_capacity is not None
    _validate_risk_score(risk_capacity, "riskCapacity")

    province = _string(body, "province")
    assert province is not None
    _validate_province(province)

    user_language = _string(body, "userLanguage")
    assert user_language is not None
    _validate_iso_639_1(user_language)

    mandate: dict[str, Any] = {
        "portfolioId": portfolio_id,
        "mode": mode,
        "objective": objective,
        "horizonYears": horizon_years,
        "riskTolerance": risk_tolerance,
        "riskCapacity": risk_capacity,
        "province": province,
        "userLanguage": user_language,
    }

    objective_detail = _string(body, "objectiveDetail", required=False)
    if objective_detail is not None:
        mandate["objectiveDetail"] = objective_detail

    max_loss = _number(body, "maxAcceptableLossPct", required=False)
    if max_loss is not None:
        if max_loss <= 0 or max_loss > 100:
            raise _validation_error(
                "maxAcceptableLossPct doit être compris entre 0 (exclu) et 100."
            )
        mandate["maxAcceptableLossPct"] = max_loss

    constraints = _array_of_strings(body, "constraints")
    if constraints is not None:
        mandate["constraints"] = constraints

    if "preferences" in body:
        mandate["preferences"] = _validate_mandate_preferences(body["preferences"])

    if "operations" in body:
        raw_ops = body["operations"]
        if not isinstance(raw_ops, list):
            raise _validation_error("operations doit être un tableau.")
        mandate["operations"] = [_validate_operation(op) for op in raw_ops]

    subject_ticker = _string(body, "subjectTicker", required=False)
    if subject_ticker is not None:
        if not subject_ticker:
            raise _validation_error("subjectTicker ne peut pas être vide.")
        mandate["subjectTicker"] = subject_ticker

    compare_category = _string(body, "compareCategory", required=False)
    if compare_category is not None:
        if compare_category not in category_ids():
            values = ", ".join(category_ids())
            raise _validation_error(f"compareCategory doit être l'un de : {values}.")
        mandate["compareCategory"] = compare_category

    build_amount = _number(body, "buildAmount", required=False)
    if build_amount is not None:
        if mode != "build":
            raise _validation_error("buildAmount n'est permis qu'en mode build.")
        if build_amount <= 0 or build_amount > MAX_BUILD_AMOUNT:
            raise _validation_error(f"buildAmount doit être supérieur à 0 et au plus {MAX_BUILD_AMOUNT:,.0f}.")
        mandate["buildAmount"] = build_amount

    if "fieldSources" in body:
        mandate["fieldSources"] = _validate_field_sources(body["fieldSources"])

    return mandate


def validate_conversation_create(body: dict[str, Any]) -> str | None:
    """Valide schema-conversation-create-request (title facultatif)."""
    _reject_unknown_fields(body, ("title",))
    return _string(body, "title", required=False)


def validate_conversation_update(body: dict[str, Any]) -> str:
    """Valide schema-conversation-update-request (title requis)."""
    _reject_unknown_fields(body, ("title",))
    return _string(body, "title")  # type: ignore[return-value]


def validate_holdings(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Valide schema-holdings-put-request : une liste complète de positions."""
    _reject_unknown_fields(body, ("holdings",))
    holdings = body.get("holdings")
    if not isinstance(holdings, list):
        raise _validation_error("holdings doit être un tableau.")
    validated: list[dict[str, Any]] = []
    for holding in holdings:
        if not isinstance(holding, dict):
            raise _validation_error("Chaque position doit être un objet.")
        _reject_unknown_fields(holding, ("ticker", "quantity", "avgCost"))
        ticker = _string(holding, "ticker")
        quantity = _number(holding, "quantity")
        assert quantity is not None
        if quantity <= 0:
            raise _validation_error("quantity doit être supérieur à 0.")
        avg_cost = _number(holding, "avgCost")
        validated.append(
            {"ticker": ticker, "quantity": quantity, "avgCost": avg_cost}
        )
    return validated


def parse_pagination(
    event: dict[str, Any], default_limit: int
) -> tuple[int, str | None]:
    """Valide `limit` (1..100) et `cursor` (chaîne non vide si présent)."""
    query = event.get("queryStringParameters") or {}
    if not isinstance(query, dict):
        raise _validation_error("Paramètres de requête invalides.")
    limit = default_limit
    if "limit" in query:
        try:
            limit = int(query["limit"])
        except (TypeError, ValueError) as exc:
            raise _validation_error("limit doit être un entier.") from exc
        if limit < 1 or limit > MAX_LIMIT:
            raise _validation_error(f"limit doit être compris entre 1 et {MAX_LIMIT}.")
    cursor = None
    if "cursor" in query:
        cursor = query["cursor"]
        if not isinstance(cursor, str) or cursor == "":
            raise _validation_error("cursor doit être une chaîne non vide.")
    return limit, cursor


def path_parameter(event: dict[str, Any], name: str) -> str:
    """Retourne un paramètre de chemin non vide."""
    parameters = event.get("pathParameters") or {}
    value = parameters.get(name)
    if not isinstance(value, str) or value == "":
        raise _validation_error(f"Paramètre de chemin requis : {name}.")
    return value


def session_id(event: dict[str, Any]) -> str:
    """Valide le sessionId du contrat (UUID v4 généré par le serveur)."""
    value = path_parameter(event, "sessionId")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise _validation_error("sessionId doit être un UUID v4.") from exc
    if parsed.version != 4 or parsed.variant != uuid.RFC_4122:
        raise _validation_error("sessionId doit être un UUID v4.")
    return str(parsed)


SPEECH_LANGS = ("fr", "en")


def validate_speech_session(body: dict[str, Any]) -> str:
    """Corps facultatif de POST /v1/speech/session : `lang` ("fr" par défaut)."""
    _reject_unknown_fields(body, ("lang",))
    lang = body.get("lang", "fr")
    if lang not in SPEECH_LANGS:
        raise _validation_error("lang doit valoir 'fr' ou 'en'.")
    return lang
