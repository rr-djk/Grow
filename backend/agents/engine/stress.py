"""Périodes de test de résistance dérivées des données (jamais choisies à la main).

- y2022 : année civile 2022 (premier et dernier jour de cotation de SPY ou XIU.TO) ;
- covid_2020 : du sommet au creux de SPY au premier semestre 2020 ;
- rate_hikes : du premier au dernier relèvement du dernier cycle de hausse
  du taux directeur (V39079, Banque du Canada ; DFF à défaut) ;
- crypto_crash : sommet → creux de la pire baisse de BTC-USD dans le jeu.
Une période non calculable (historique trop court) est renvoyée avec
available = False et une note : elle n'est jamais inventée.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.agents.data.store import DataStore
from backend.agents.engine.analytics import max_drawdown, native_series

PERIOD_IDS = ("y2022", "covid_2020", "rate_hikes", "crypto_crash")
MIN_HIKES = 2

LABELS = {
    "y2022": "Stress period: calendar year 2022",
    "covid_2020": "Stress period: COVID crash 2020",
    "rate_hikes": "Stress period: policy rate hiking cycle",
    "crypto_crash": "Stress period: crypto crash",
}


@dataclass
class StressPeriod:
    period_id: str
    available: bool
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None
    method: str = ""
    source: str = ""
    note: str | None = None


def _reference_ticker(store: DataStore, candidates: tuple[str, ...]) -> str | None:
    return next((t for t in candidates if store.has_ticker(t)), None)


def derive_period(store: DataStore, period_id: str) -> StressPeriod:
    if period_id == "y2022":
        ticker = _reference_ticker(store, ("SPY", "XIU.TO"))
        if ticker is None:
            return StressPeriod(period_id, False, note="No reference index (SPY or XIU.TO) in the dataset.")
        days = native_series(store, ticker)
        days = days[(days.index >= "2022-01-01") & (days.index <= "2022-12-31")]
        if days.empty:
            return StressPeriod(period_id, False, note="The dataset does not cover 2022.")
        return StressPeriod(
            period_id, True, days.index.min(), days.index.max(),
            method=f"First and last {ticker} trading days of calendar year 2022.",
            source=store.source_label(f"prices/{ticker}.parquet"),
        )

    if period_id == "covid_2020":
        if not store.has_ticker("SPY"):
            return StressPeriod(period_id, False, note="SPY is not in the dataset.")
        spy = native_series(store, "SPY")
        h1 = spy[(spy.index >= "2020-01-01") & (spy.index <= "2020-06-30")]
        if len(h1) < 20:
            return StressPeriod(period_id, False, note="The dataset does not cover the first half of 2020.")
        _, peak, trough = max_drawdown(h1)
        return StressPeriod(
            period_id, True, peak, trough,
            method="SPY adjusted close: peak to trough of the largest drawdown in H1 2020.",
            source=store.source_label("prices/SPY.parquet"),
        )

    if period_id == "rate_hikes":
        macro = store.macro()
        for series_id in ("V39079", "DFF"):
            series = macro[macro["series_id"] == series_id].set_index("date")["value"].astype(float)
            if series.empty:
                continue
            changes = series.diff().dropna()
            changes = changes[changes != 0]
            if changes.empty:
                continue
            runs: list[list[pd.Timestamp]] = []
            current: list[pd.Timestamp] = []
            for day, delta in changes.items():
                if delta > 0:
                    current.append(day)
                else:
                    if current:
                        runs.append(current)
                    current = []
            if current:
                runs.append(current)
            cycles = [r for r in runs if len(r) >= MIN_HIKES]
            if not cycles:
                continue
            run_start, run_end = cycles[-1][0], cycles[-1][-1]
            return StressPeriod(
                period_id, True, run_start, run_end,
                method=f"First to last increase of the latest hiking cycle (at least {MIN_HIKES} consecutive increases) in {series_id}.",
                source=store.source_label("macro/macro.parquet"),
            )
        return StressPeriod(period_id, False, note="No policy rate hiking cycle found (V39079 or DFF).")

    if period_id == "crypto_crash":
        if not store.has_ticker("BTC-USD"):
            return StressPeriod(period_id, False, note="BTC-USD is not in the dataset.")
        _, peak, trough = max_drawdown(native_series(store, "BTC-USD"))
        if peak is None or trough is None or peak == trough:
            return StressPeriod(period_id, False, note="No BTC-USD drawdown found.")
        return StressPeriod(
            period_id, True, peak, trough,
            method="BTC-USD adjusted close: peak to trough of its largest drawdown in the dataset.",
            source=store.source_label("prices/BTC-USD.parquet"),
        )

    raise ValueError(f"Unknown period_id: {period_id}")
