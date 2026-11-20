"""Registre de preuves d'un run (schema-evidence) : seule source des chiffres affichés.

Identifiants : EV-nn pour un calcul ou une hypothèse, KB-nn pour une citation
réglementaire, uniques dans un run (conventions.identifiers.evidenceId).
Les champs label, method et caveats sont en anglais (language_policy) ; seul
`formatted` suit userLanguage, car c'est la valeur que le front affiche.
"""

from __future__ import annotations

import math
from typing import Any


def format_number(value: float | None, unit: str, language: str) -> str | None:
    """Formate une valeur pour l'affichage : 15.2 % → « 15,2 % » (fr) ou « 15.2% » (en)."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    decimals = 0 if unit in ("CAD", "USD") else 1
    text = f"{value:,.{decimals}f}"
    if language == "fr":
        text = text.replace(",", " ").replace(".", ",")
        if unit == "%":
            return f"{text} %"
        if unit in ("CAD", "USD"):
            return f"{text} $" if unit == "CAD" else f"{text} $ US"
        return f"{text} {unit}".strip()
    if unit == "%":
        return f"{text}%"
    if unit in ("CAD", "USD"):
        return f"{unit} {text}"
    return f"{text} {unit}".strip()


class EvidenceRegistry:
    """Accumule les éléments EV-nn et KB-nn d'un run, dans l'ordre de création."""

    def __init__(self, language: str = "en", items: list[dict[str, Any]] | None = None):
        self.language = language
        self.items: list[dict[str, Any]] = list(items or [])
        self._counters = {"EV": 0, "KB": 0}
        for item in self.items:
            prefix, _, number = item["id"].partition("-")
            if prefix in self._counters and number.isdigit():
                self._counters[prefix] = max(self._counters[prefix], int(number))

    def _next(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}-{self._counters[prefix]:02d}"

    def add(
        self,
        *,
        kind: str,
        label: str,
        source: str,
        value: float | None = None,
        unit: str = "%",
        scenario: int | None = None,
        method: str | None = None,
        window: str | None = None,
        currency: str | None = None,
        as_of: str | None = None,
        caveats: list[str] | None = None,
        formatted: str | None = None,
        key: str | None = None,
    ) -> str:
        """Inscrit un calcul, une hypothèse ou un fait d'émetteur ; renvoie son EV-nn."""
        if kind not in ("metric", "etf_fact", "assumption"):
            raise ValueError(f"kind invalide pour EV : {kind}")
        evidence: dict[str, Any] = {"id": self._next("EV"), "kind": kind, "label": label, "source": source}
        if value is not None:
            evidence["value"] = round(float(value), 4)
        shown = formatted if formatted is not None else format_number(value, unit, self.language)
        if shown is not None:
            evidence["formatted"] = shown
        optional = {
            "scenario": scenario, "method": method, "window": window, "currency": currency,
            "asOf": as_of, "caveats": caveats or None,
        }
        evidence.update({k: v for k, v in optional.items() if v is not None})
        if key:
            evidence["key"] = key
        self.items.append(evidence)
        return evidence["id"]

    def add_regulation(
        self,
        *,
        document: str,
        excerpt: str,
        jurisdiction: str,
        source: str,
        section: str | None = None,
        url: str | None = None,
        as_of: str | None = None,
        label: str | None = None,
        document_type: str | None = None,
        regulator: str | None = None,
        status: str | None = None,
        section_title: str | None = None,
        language: str | None = None,
    ) -> str:
        """Inscrit un passage réglementaire tiré de la KB ; renvoie son KB-nn."""
        evidence: dict[str, Any] = {
            "id": self._next("KB"), "kind": "regulation", "label": label or document,
            "document": document, "excerpt": excerpt, "jurisdiction": jurisdiction, "source": source,
        }
        optional = {"section": section, "url": url, "asOf": as_of, "documentType": document_type, "regulator": regulator,
                    "status": status, "sectionTitle": section_title, "language": language}
        for k, v in optional.items():
            if v:
                evidence[k] = v
        self.items.append(evidence)
        return evidence["id"]

    def get(self, evidence_id: str) -> dict[str, Any] | None:
        return next((item for item in self.items if item["id"] == evidence_id), None)

    def ids(self) -> set[str]:
        return {item["id"] for item in self.items}

    def public_items(self) -> list[dict[str, Any]]:
        """Éléments conformes à schema-evidence (la clé interne `key` est retirée)."""
        return [{k: v for k, v in item.items() if k != "key"} for item in self.items]
