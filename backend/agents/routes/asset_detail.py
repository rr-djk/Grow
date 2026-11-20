"""Route GET /v1/market/assets/{ticker} : fiche d'un actif (profil, prix, série et repères), sans modèle.

Tout est calculé ici, dans la devise de cotation de l'actif : le front n'affiche que ce qui est renvoyé.
Les rendements s'appuient sur `adjclose` (dividendes réinvestis) ; le prix affiché est la dernière clôture.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from backend.agents.data.store import DataStore
from backend.agents.engine import analytics
from backend.common.http import ApiError, json_response

RANGES = {"1m": pd.DateOffset(months=1), "6m": pd.DateOffset(months=6), "1y": pd.DateOffset(years=1), "5y": pd.DateOffset(years=5)}
MAX_POINTS = 120
YEAR_DAYS = 365


def _num(value: float, digits: int = 2) -> float | None:
    return None if value is None or not math.isfinite(value) else round(float(value), digits)


def _thin(series: pd.Series) -> pd.Series:
    """Garde au plus MAX_POINTS points, dernier point inclus."""
    if len(series) <= MAX_POINTS:
        return series
    step = math.ceil(len(series) / MAX_POINTS)
    keep = series.iloc[::-1].iloc[::step].iloc[::-1]
    return keep


def build_asset_detail(store: DataStore, ticker: str, range_key: str) -> dict[str, Any]:
    info = store.asset(ticker)
    prices = store.prices(ticker)
    if prices.empty:
        raise ApiError("ASSET_NOT_FOUND", f"Aucun historique de prix pour {ticker}.")
    adj = prices["adjclose"].astype(float)
    close = prices["close"].astype(float).where(prices["close"] > 0, adj)
    as_of = adj.index.max()
    asset_class = info.get("asset_class")

    window = adj[adj.index >= as_of - RANGES[range_key]]
    year = adj[adj.index >= as_of - pd.DateOffset(days=YEAR_DAYS)]
    year_close = close[close.index >= as_of - pd.DateOffset(days=YEAR_DAYS)]
    day_change = float((adj.iloc[-1] / adj.iloc[-2] - 1.0) * 100.0) if len(adj) >= 2 else float("nan")
    drawdown, _, _ = analytics.max_drawdown(year)
    periods = analytics.periods_per_year(ticker, asset_class)

    shown = _thin(window)
    scale = float(close.iloc[-1] / adj.iloc[-1])
    points = [{"date": d.strftime("%Y-%m-%d"), "close": _num(v * scale, 4)} for d, v in shown.items()]

    detail: dict[str, Any] = {
        "ticker": ticker,
        "name": str(info.get("name") or ticker),
        "assetClass": asset_class,
        "market": info.get("market"),
        "currency": info.get("currency"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "asOf": as_of.strftime("%Y-%m-%d"),
        "price": _num(close.iloc[-1], 4),
        "dayChangePct": _num(day_change),
        "range": range_key,
        "rangeChangePct": _num(analytics.total_return(window)),
        "points": points,
        "stats": {
            "high52w": _num(year_close.max(), 4),
            "low52w": _num(year_close.min(), 4),
            "volatility": _num(analytics.annualized_volatility(year.pct_change().dropna(), periods)),
            "maxDrawdown": _num(drawdown),
            "historyStart": adj.index.min().strftime("%Y-%m-%d"),
        },
    }
    profile = store.profiles().get(ticker) or {}
    if profile.get("description"):
        detail["description"] = str(profile["description"])
    if profile.get("website"):
        detail["website"] = str(profile["website"])
    detail["source"] = store.source_label(f"prices/{ticker}.parquet")
    return detail


def asset_detail(event: dict[str, Any], user_id: str, store: DataStore) -> dict[str, Any]:
    ticker = ((event.get("pathParameters") or {}).get("ticker") or "").strip()
    if not ticker:
        raise ApiError("VALIDATION_ERROR", "Paramètre requis : ticker.")
    range_key = (event.get("queryStringParameters") or {}).get("range", "1y")
    if range_key not in RANGES:
        raise ApiError("VALIDATION_ERROR", "range doit être l'un de : 1m, 6m, 1y, 5y.")
    if not store.is_investable(ticker):
        raise ApiError("ASSET_NOT_FOUND", f"{ticker} n'existe pas dans l'univers d'actifs.")
    return json_response(200, build_asset_detail(store, ticker, range_key))
