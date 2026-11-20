"""Calculs purs sur séries de prix (module-engine), sans E/S ni modèle.

Conventions (contrat module-engine.rules, SOLUTION.md section 10) :
- rendements à partir de adjclose ; les splits ne sont jamais réappliqués ;
- conversion en CAD avec le dernier taux USD/CAD connu (report), devise native conservée ;
- annualisation √252 (actions, FNB) et √365 (crypto), chacun sur son calendrier natif ;
- portefeuilles sur l'intersection des jours de cotation de leurs actifs hors crypto
  (jours ouvrés nord-américains communs), crypto échantillonnée sur ces jours ;
- portefeuille à poids constants (rééquilibré chaque jour) : méthode écrite dans les preuves.
Les pourcentages sont des nombres : -18.4 veut dire -18,4 %.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.agents.data.store import DataStore


def is_crypto(ticker: str, asset_class: str | None = None) -> bool:
    return (asset_class or "").lower() == "crypto" or ticker.endswith("-USD")


def periods_per_year(ticker: str, asset_class: str | None = None) -> int:
    return 365 if is_crypto(ticker, asset_class) else 252


def native_series(store: DataStore, ticker: str) -> pd.Series:
    """adjclose dans la devise de cotation, calendrier natif."""
    return store.prices(ticker)["adjclose"].astype(float)


def listing_currency(store: DataStore, ticker: str) -> str:
    currency = store.asset(ticker).get("currency")
    if currency:
        return str(currency)
    return "CAD" if ticker.endswith(".TO") else "USD"


def to_cad(store: DataStore, ticker: str, series: pd.Series) -> pd.Series:
    """Convertit une série en CAD avec le dernier taux USD/CAD connu à chaque date."""
    if listing_currency(store, ticker) == "CAD":
        return series
    fx = store.fx_usdcad()
    rate = fx.reindex(fx.index.union(series.index)).ffill().reindex(series.index)
    return (series * rate).dropna()


def fx_rate_on(store: DataStore, day: pd.Timestamp) -> float:
    fx = store.fx_usdcad()
    known = fx[fx.index <= day]
    return float(known.iloc[-1] if len(known) else fx.iloc[0])


def max_drawdown(index: pd.Series) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    """Pire baisse (en %, négative), date du sommet, date du creux."""
    if index.empty:
        return 0.0, None, None
    running_max = index.cummax()
    drawdown = index / running_max - 1.0
    trough = drawdown.idxmin()
    peak = index.loc[:trough].idxmax()
    return float(drawdown.min() * 100.0), peak, trough


def annualized_volatility(returns: pd.Series, periods: int) -> float:
    if len(returns) < 2:
        return float("nan")
    return float(returns.std(ddof=1) * math.sqrt(periods) * 100.0)


def total_return(index: pd.Series) -> float:
    if len(index) < 2:
        return float("nan")
    return float((index.iloc[-1] / index.iloc[0] - 1.0) * 100.0)


@dataclass
class AlignedPrices:
    """Prix en CAD alignés sur un calendrier commun, avec la méthode d'alignement."""

    frame: pd.DataFrame
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    shortened_by: list[str]
    missing: list[str]


def aligned_cad_prices(
    store: DataStore,
    tickers: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    require_full_window: bool = False,
) -> AlignedPrices:
    """Prix CAD sur l'intersection des dates de cotation hors crypto, dans [start, end].

    require_full_window=True : un actif qui commence après `start` (+5 jours) est
    déclaré manquant au lieu de raccourcir la fenêtre (tests de résistance).
    """
    columns: dict[str, pd.Series] = {}
    shortened: list[str] = []
    missing: list[str] = []
    for ticker in tickers:
        series = to_cad(store, ticker, native_series(store, ticker))
        series = series[(series.index >= start) & (series.index <= end)]
        if series.empty:
            missing.append(ticker)
            continue
        if series.index.min() > start + pd.Timedelta(5, "D"):
            if require_full_window:
                missing.append(ticker)
                continue
            shortened.append(ticker)
        columns[ticker] = series
    if not columns:
        return AlignedPrices(pd.DataFrame(), None, None, shortened, missing)
    non_crypto = [t for t in columns if not is_crypto(t, store.asset(t).get("asset_class"))]
    calendar_source = non_crypto or list(columns)
    calendar = None
    for ticker in calendar_source:
        idx = columns[ticker].index
        calendar = idx if calendar is None else calendar.intersection(idx)
    frame = pd.DataFrame(index=calendar)
    for ticker, series in columns.items():
        frame[ticker] = series.reindex(calendar)
    frame = frame.dropna(how="any")
    if frame.empty:
        return AlignedPrices(frame, None, None, shortened, missing)
    return AlignedPrices(frame, frame.index.min(), frame.index.max(), shortened, missing)


def portfolio_index(prices: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Indice de valeur d'un portefeuille à poids constants (rééquilibré chaque jour), base 1."""
    tickers = [t for t in weights if t in prices.columns and weights[t] > 0]
    if not tickers or len(prices) < 2:
        return pd.Series(dtype=float)
    w = np.array([weights[t] for t in tickers], dtype=float)
    w = w / w.sum()
    returns = prices[tickers].pct_change().dropna(how="any")
    port = returns.to_numpy() @ w
    index = pd.Series(np.concatenate([[1.0], np.cumprod(1.0 + port)]), index=prices.index[: len(port) + 1])
    return index


def portfolio_metrics(prices: pd.DataFrame, weights: dict[str, float]) -> dict[str, float]:
    index = portfolio_index(prices, weights)
    if index.empty:
        return {}
    returns = index.pct_change().dropna()
    dd, peak, trough = max_drawdown(index)
    return {
        "volatility": annualized_volatility(returns, 252),
        "maxDrawdown": dd,
        "totalReturn": total_return(index),
        "peak": peak,
        "trough": trough,
    }


BOOTSTRAP_RESAMPLES = 500
BOOTSTRAP_BLOCK_DAYS = 21
BOOTSTRAP_SEED = 20261115


def bootstrap_ranges(index: pd.Series, *, resamples: int = BOOTSTRAP_RESAMPLES, block: int = BOOTSTRAP_BLOCK_DAYS,
                     seed: int = BOOTSTRAP_SEED) -> dict[str, float]:
    """Incertitude d'échantillonnage : fourchette 5e-95e percentile de la volatilité et de la pire baisse.

    Bootstrap par blocs mobiles (blocs de 21 jours, pour garder l'autocorrélation et les grappes de volatilité)
    sur les rendements quotidiens du portefeuille, graine fixe (résultat reproductible). Elle mesure à quel point
    la période observée aurait pu donner un autre chiffre ; elle ne prédit rien sur l'avenir.
    """
    returns = index.pct_change().dropna().to_numpy()
    n = len(returns)
    if n < 2 * block:
        return {}
    rng = np.random.default_rng(seed)
    blocks_needed = int(math.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(resamples, blocks_needed))
    offsets = np.arange(block)
    sample = returns[(starts[:, :, None] + offsets[None, None, :]).reshape(resamples, -1)[:, :n]]
    vols = sample.std(axis=1, ddof=1) * math.sqrt(252) * 100.0
    paths = np.cumprod(1.0 + sample, axis=1)
    paths = np.concatenate([np.ones((resamples, 1)), paths], axis=1)
    drawdowns = (paths / np.maximum.accumulate(paths, axis=1) - 1.0).min(axis=1) * 100.0
    return {
        "volatilityLow": float(np.percentile(vols, 5)), "volatilityHigh": float(np.percentile(vols, 95)),
        "maxDrawdownLow": float(np.percentile(drawdowns, 5)), "maxDrawdownHigh": float(np.percentile(drawdowns, 95)),
        "resamples": resamples, "blockDays": block,
    }


def asset_metrics(store: DataStore, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    """Mesures d'un actif sur son calendrier natif, dans sa devise de cotation."""
    series = native_series(store, ticker)
    series = series[(series.index >= start) & (series.index <= end)]
    if len(series) < 2:
        return {}
    periods = periods_per_year(ticker, store.asset(ticker).get("asset_class"))
    dd, _, _ = max_drawdown(series)
    return {
        "volatility": annualized_volatility(series.pct_change().dropna(), periods),
        "maxDrawdown": dd,
        "totalReturn": total_return(series),
        "start": series.index.min(),
        "end": series.index.max(),
        "periods": periods,
    }


MARKET_INDEX = "^GSPC"
MIN_MARKET_OBSERVATIONS = 30


def market_stats(store: DataStore, tickers: list[str], start: pd.Timestamp, end: pd.Timestamp,
                 index: str = MARKET_INDEX) -> dict[str, dict[str, float | int | None]]:
    """Modèle de marché à un facteur : rendement, variance, écart-type, bêta et corrélation vs l'indice.

    Formules du script de l'équipe, sur les rendements quotidiens de adjclose dans la devise
    de cotation (aucune conversion), sans report de cours (pct_change(fill_method=None)) :
    rendement = moyenne × p, variance = var × p, écart-type = std × √p,
    bêta = cov(titre, marché) / var(marché), corrélation = corr(titre, marché), avec p = 252
    (365 pour la crypto). cov, var(marché) et corr portent sur les jours communs au titre et à
    l'indice, donc sur le même échantillon. Rendement et écart-type en %, variance en décimal.
    Sous MIN_MARKET_OBSERVATIONS jours communs, bêta et corrélation valent None.
    """

    def daily_returns(ticker: str) -> pd.Series:
        series = native_series(store, ticker)
        series = series[(series.index >= start) & (series.index <= end)]
        return series.pct_change(fill_method=None).dropna()

    market = daily_returns(index)
    out: dict[str, dict[str, float | int | None]] = {}
    for ticker in tickers:
        r = daily_returns(ticker)
        if len(r) < 2:
            out[ticker] = {"annual_return": None, "variance": None, "std_dev": None, "beta": None,
                           "market_correlation": None, "observations": 0}
            continue
        periods = periods_per_year(ticker, store.asset(ticker).get("asset_class"))
        std = float(r.std(ddof=1) * math.sqrt(periods))
        common = pd.concat([r, market], axis=1, join="inner").dropna()
        beta = corr = None
        if len(common) >= MIN_MARKET_OBSERVATIONS:
            rt, rm = common.iloc[:, 0], common.iloc[:, 1]
            market_var = float(rm.var(ddof=1))
            if market_var > 0:
                beta = float(rt.cov(rm) / market_var)
                corr = float(rt.corr(rm))
        out[ticker] = {
            "annual_return": float(r.mean() * periods * 100.0),
            "variance": float(r.var(ddof=1) * periods),
            "std_dev": std * 100.0,
            "beta": beta,
            "market_correlation": corr,
            "observations": int(len(common)),
        }
    return out


def correlation_matrix(prices: pd.DataFrame) -> dict[str, dict[str, float]]:
    returns = prices.pct_change().dropna(how="any")
    if len(returns) < 3:
        return {}
    corr = returns.corr()
    return {a: {b: round(float(corr.loc[a, b]), 3) for b in corr.columns} for a in corr.index}


def window_label(start: pd.Timestamp | None, end: pd.Timestamp | None) -> str | None:
    if start is None or end is None:
        return None
    return f"{start.date().isoformat()}/{end.date().isoformat()}"
