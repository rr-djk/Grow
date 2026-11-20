"""Concentration d'un scénario : titre unique, secteur, pays, devise, avec composition des FNB.

Composition : etf_enriched.json (fiches émetteurs datées, WS3). Un FNB sans fiche
est lu par sa catégorie (secteur de l'univers) et signalé « composition not
available ». Un FNB n'est pas un titre unique pour R6 : seules ses principales
positions (topHoldings) s'ajoutent aux positions directes (lecture par transparence).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.agents.data.store import DataStore
from backend.agents.engine.analytics import is_crypto, listing_currency

TECH_SECTOR = "Information Technology"

GICS_SECTORS = {
    "Information Technology", "Health Care", "Financials", "Consumer Discretionary", "Communication Services",
    "Industrials", "Consumer Staples", "Energy", "Utilities", "Real Estate", "Materials",
}


def top_sector(concentration: dict[str, Any] | None) -> tuple[str | None, float]:
    """Plus gros secteur GICS (par transparence des FNB documentés) et son poids en % du portefeuille."""
    best: tuple[str | None, float] = (None, 0.0)
    for item in (concentration or {}).get("bySector") or []:
        if item.get("label") in GICS_SECTORS and float(item.get("weight") or 0.0) > best[1]:
            best = (item["label"], float(item["weight"]))
    return best


def is_fund(asset_class: str | None) -> bool:
    return (asset_class or "").lower().startswith("etf")


_COUNTRY_CODES = {"canada": "CA", "united states": "US"}


def _country_of(ticker: str, asset_class: str | None, country: str | None = None) -> str:
    """Pays de cotation : colonne `country` du jeu (Yahoo) si présente, sinon règle du suffixe."""
    if is_crypto(ticker, asset_class):
        return "Crypto"
    if country:
        return _COUNTRY_CODES.get(country.strip().lower(), country.strip())
    return "CA" if ticker.endswith(".TO") else "US"


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    return {k: v / total * 100.0 for k, v in weights.items()} if total else {}


def _has_composition(sheet: dict[str, Any] | None) -> bool:
    """Une fiche sans secteurs, sans pays ni positions (gabarit non rempli) ne décrit aucune composition."""
    return bool(sheet) and bool(sheet.get("sectorWeights") or sheet.get("countryWeights") or sheet.get("topHoldings"))


def concentration(store: DataStore, weights: dict[str, float]) -> dict[str, Any]:
    """Poids (en %) d'un scénario. `weights` : poids par ticker (somme quelconque, normalisée)."""
    weights = _normalize({t: w for t, w in weights.items() if w > 0})
    enriched = store.etf_enriched()
    single: dict[str, float] = defaultdict(float)
    sector: dict[str, float] = defaultdict(float)
    country: dict[str, float] = defaultdict(float)
    currency: dict[str, float] = defaultdict(float)
    tech = 0.0
    caveats: list[str] = []
    sources: list[str] = []
    no_composition: list[str] = []

    for ticker, weight in weights.items():
        asset = store.asset(ticker)
        asset_class = asset.get("asset_class")
        currency[listing_currency(store, ticker)] += weight
        if not is_fund(asset_class):
            single[ticker] += weight
            label = asset.get("sector") or "Unknown"
            sector[label] += weight
            country[_country_of(ticker, asset_class, asset.get("country"))] += weight
            if label == TECH_SECTOR:
                tech += weight
            continue
        sheet = enriched.get(ticker)
        if not _has_composition(sheet):
            no_composition.append(ticker)
            sector[asset.get("sector") or "Fund (composition not available)"] += weight
            country[_country_of(ticker, asset_class, asset.get("country"))] += weight
            continue
        sources.append(f"{ticker}: {sheet.get('sourceUrl', 'issuer sheet')} (as of {sheet.get('asOfDate', 'n/a')})")
        sector_weights = sheet.get("sectorWeights") or {}
        if sector_weights:
            total = sum(float(v) for v in sector_weights.values()) or 100.0
            for label, share in sector_weights.items():
                sector[label] += weight * float(share) / total
                if label == TECH_SECTOR:
                    tech += weight * float(share) / total
        else:
            sector[asset.get("sector") or "Fund"] += weight
        country_weights = sheet.get("countryWeights") or {}
        if country_weights:
            total = sum(float(v) for v in country_weights.values()) or 100.0
            for label, share in country_weights.items():
                country[label] += weight * float(share) / total
        else:
            country[_country_of(ticker, asset_class, asset.get("country"))] += weight
        for holding in sheet.get("topHoldings") or []:
            held = holding.get("ticker")
            share = holding.get("weight")
            if held and share is not None:
                single[held] += weight * float(share) / 100.0

    if no_composition:
        caveats.append(
            "Fund composition not available for " + ", ".join(sorted(no_composition))
            + ": exposure read by fund category, look-through incomplete."
        )
    if any(_has_composition(enriched.get(t)) for t in weights):
        caveats.append("Look-through uses only the top holdings published by each issuer.")

    top_ticker, top_weight = (None, 0.0)
    if single:
        top_ticker, top_weight = max(single.items(), key=lambda kv: kv[1])

    def as_list(mapping: dict[str, float]) -> list[dict[str, Any]]:
        return [
            {"label": label, "weight": round(value, 2)}
            for label, value in sorted(mapping.items(), key=lambda kv: -kv[1])
        ]

    crypto_weight = sum(
        w for t, w in weights.items() if is_crypto(t, store.asset(t).get("asset_class"))
    )
    return {
        "topSingle": {"ticker": top_ticker, "weight": round(top_weight, 2)},
        "singleWeights": {k: round(v, 2) for k, v in single.items()},
        "bySector": as_list(sector),
        "byCountry": as_list(country),
        "byCurrency": as_list(currency),
        "techLookThrough": round(tech, 2),
        "cryptoWeight": round(crypto_weight, 2),
        "lookThroughComplete": not no_composition,
        "caveats": caveats,
        "sources": sources,
    }


def by_asset_class(store: DataStore, weights: dict[str, float]) -> list[dict[str, Any]]:
    weights = _normalize({t: w for t, w in weights.items() if w > 0})
    grouped: dict[str, float] = defaultdict(float)
    for ticker, weight in weights.items():
        grouped[store.asset(ticker).get("asset_class") or "unknown"] += weight
    return [{"label": k, "weight": round(v, 2)} for k, v in sorted(grouped.items(), key=lambda kv: -kv[1])]
