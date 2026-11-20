"""Constructeur de portefeuille moyenne-variance (module-engine) : U(w) = w'mu - (A/2) w'Sigma w.

Transcription du script de l'équipe :
- rendements quotidiens (adjclose, devise de cotation) sur `windowYears` ans, titres cotés à au moins
  `minCoverage` de la fenêtre, jours communs seulement (aucun cours reporté);
- beta = cov(titre, marché) / var(marché) contre ^GSPC; mu = rf + beta (rendement du marché - rf);
- Sigma = covariance Ledoit-Wolf (écrite en numpy, formule de scikit-learn) x 252;
- contraintes : somme des poids = 1, poids dans [0, maxWeight], plafond par industrie, plancher des
  industries préférées (facultatif), industries exclues à 0;
- les industries préférées reçoivent `preferredBonus` de rendement « perçu » dans l'optimisation
  seulement; les résultats sont recalculés avec le vrai mu.
Le problème est un programme quadratique : il est résolu exactement par quadprog (numpy seul,
compatible avec la Lambda), au lieu de SLSQP.

L'aversion au risque A, les industries préférées et exclues ne sont jamais codées en dur : A vient
du profil de risque du mandat, les industries de la conversation (vides par défaut).
Les rendements espérés sont un modèle (CAPM sur l'historique), pas une prévision.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.agents.data.store import DataStore
from backend.agents.engine.analytics import MARKET_INDEX, native_series

TRADING_DAYS = 252
_CONFIG_FILE = Path(__file__).with_name("optimizer_config.json")


class OptimizerError(ValueError):
    """Demande impossible ou données insuffisantes : le message (anglais) est montré à l'utilisateur."""


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with _CONFIG_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def risk_aversion(risk_profile: int, config: dict[str, Any] | None = None) -> float:
    """Aversion au risque A pour un profil 1-5 (table en configuration)."""
    table = (config or load_config())["aversionByProfile"]
    key = str(int(risk_profile))
    if key not in table:
        raise OptimizerError(f"Risk profile must be between 1 and 5 (got {risk_profile}).")
    return float(table[key])


def ledoit_wolf_covariance(returns: np.ndarray) -> np.ndarray:
    """Covariance Ledoit-Wolf (identique à sklearn.covariance.LedoitWolf().fit(returns).covariance_)."""
    x = np.asarray(returns, dtype=float)
    n, p = x.shape
    x = x - x.mean(axis=0)
    emp_cov = x.T @ x / n
    x2 = x**2
    emp_cov_trace = x2.sum(axis=0) / n
    mu = emp_cov_trace.sum() / p
    delta_ = (emp_cov**2).sum()
    beta_ = (x2.T @ x2).sum() / n - delta_
    beta_ = beta_ / (p * n)
    delta = (delta_ - 2.0 * mu * emp_cov_trace.sum() + p * mu**2) / p
    beta = min(beta_, delta)
    shrinkage = 0.0 if beta == 0 else beta / delta
    shrunk = (1.0 - shrinkage) * emp_cov
    shrunk[np.diag_indices(p)] += shrinkage * mu
    return shrunk


def solve_mean_variance(sigma: np.ndarray, mu: np.ndarray, aversion: float, upper: np.ndarray,
                        groups: list[tuple[np.ndarray, float | None, float | None]]) -> np.ndarray:
    """max w'mu - (A/2) w'Sigma w, sum w = 1, 0 <= w <= upper, et pour chaque groupe (masque, plafond, plancher)
    plancher <= sum(w[masque]) <= plafond. Retourne les poids; ValueError si le problème est infaisable."""
    from quadprog import solve_qp

    p = len(mu)
    columns = [np.ones(p)]
    bounds = [1.0]
    columns += list(np.eye(p))
    bounds += [0.0] * p
    columns += list(-np.eye(p))
    bounds += list(-upper)
    for mask, cap, floor in groups:
        indicator = mask.astype(float)
        if cap is not None:
            columns.append(-indicator)
            bounds.append(-cap)
        if floor:
            columns.append(indicator)
            bounds.append(floor)
    constraints = np.column_stack(columns)
    hessian = aversion * sigma
    hessian = (hessian + hessian.T) / 2.0 + 1e-10 * np.eye(p)
    solution = solve_qp(hessian, mu, constraints, np.array(bounds), meq=1)[0]
    return np.asarray(solution)


@dataclass
class Holding:
    symbol: str
    name: str
    industry: str
    weight: float
    beta: float
    expected_return: float


@dataclass
class OptimizationResult:
    holdings: list[Holding]
    expected_return: float
    volatility: float
    utility: float
    beta: float
    preferred_share: float
    by_industry: dict[str, float]
    aversion: float
    risk_profile: int
    window: tuple[pd.Timestamp, pd.Timestamp]
    observations: int
    universe_size: int
    excluded_industries: list[str]
    preferred_industries: list[dict[str, Any]]
    config: dict[str, Any]
    notes: list[str] = field(default_factory=list)


def _clean_preferences(excluded: list[str] | None, preferred: list[dict[str, Any]] | None,
                       known: set[str], config: dict[str, Any]) -> tuple[list[str], dict[str, float]]:
    excluded_set = list(dict.fromkeys(excluded or []))
    minimums: dict[str, float] = {}
    for item in preferred or []:
        industry = item["industry"]
        minimum = item.get("minWeight") or 0.0
        if industry in minimums:
            raise OptimizerError(f"Industry '{industry}' is listed twice in the preferred industries.")
        if minimum < 0 or minimum > 1:
            raise OptimizerError(f"Minimum weight for '{industry}' must be between 0 and 100 %.")
        minimums[industry] = float(minimum)
    for industry in list(excluded_set) + list(minimums):
        if industry not in known:
            raise OptimizerError(f"Unknown industry '{industry}': it is not in the dataset.")
    both = sorted(set(excluded_set) & set(minimums))
    if both:
        raise OptimizerError(f"Industry '{both[0]}' cannot be both preferred and excluded.")
    if sum(minimums.values()) > 1.0 + 1e-9:
        raise OptimizerError("The minimum weights of the preferred industries add up to more than 100 %.")
    return excluded_set, minimums


def candidate_universe(universe: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Actions avec industrie, cotées dans la devise de la configuration (une seule devise : USD par défaut, rendements sans conversion)."""
    if "industry" not in universe.columns:
        return universe.iloc[0:0]
    return universe[
        (universe["asset_class"].astype(str).str.lower() == "equity")
        & universe["industry"].notna()
        & universe["currency"].isin(config["universeCurrencies"])
    ]


def _check_reachable(industries: np.ndarray, excluded: list[str], minimums: dict[str, float], config: dict[str, Any]) -> None:
    is_excluded = np.isin(industries, excluded)
    for industry, minimum in minimums.items():
        available = int(((industries == industry) & ~is_excluded).sum())
        limit = min(config["preferredIndustryCap"], available * config["maxWeight"])
        if minimum > limit + 1e-9:
            raise OptimizerError(
                f"Industry '{industry}': a minimum of {minimum:.0%} is not reachable "
                f"({available} eligible stocks, at most {config['maxWeight']:.0%} each, cap {config['preferredIndustryCap']:.0%})."
            )
    if int((~is_excluded).sum()) * config["maxWeight"] < 1.0 - 1e-9:
        raise OptimizerError("Too few eligible stocks once the excluded industries are removed.")


def check_preferences(universe: pd.DataFrame, excluded: list[str] | None, preferred: list[dict[str, Any]] | None,
                      config: dict[str, Any] | None = None) -> None:
    """Contrôles de faisabilité sans calcul (avant la confirmation du mandat); OptimizerError sinon.
    `preferred` : [{industry, minWeight en fraction | None}]."""
    cfg = {**load_config(), **(config or {})}
    candidates = candidate_universe(universe, cfg)
    if candidates.empty:
        raise OptimizerError("No candidate with an industry in this dataset version.")
    excluded_list, minimums = _clean_preferences(excluded, preferred, set(candidates["industry"]), cfg)
    _check_reachable(candidates["industry"].to_numpy(), excluded_list, minimums, cfg)


def optimize_portfolio(store: DataStore, risk_profile: int, excluded_industries: list[str] | None = None,
                       preferred_industries: list[dict[str, Any]] | None = None,
                       config: dict[str, Any] | None = None) -> OptimizationResult:
    """Construit le portefeuille moyenne-variance. `preferred_industries` : [{industry, minWeight|None}]."""
    cfg = {**load_config(), **(config or {})}
    aversion = risk_aversion(risk_profile, cfg)
    universe = store.universe()
    if MARKET_INDEX not in universe.index:
        raise OptimizerError(f"Market index {MARKET_INDEX} is missing from this dataset version.")
    candidates = candidate_universe(universe, cfg)
    if candidates.empty:
        raise OptimizerError("No candidate with an industry in this dataset version.")
    excluded, minimums = _clean_preferences(
        excluded_industries, preferred_industries, set(candidates["industry"]), cfg
    )

    symbols = [*candidates.index, MARKET_INDEX]
    store.prices_many(symbols)
    series = {symbol: native_series(store, symbol) for symbol in symbols}
    prices = pd.DataFrame(series).sort_index()
    end = store.last_date()
    window = prices.loc[end - pd.DateOffset(years=int(cfg["windowYears"])):end]
    window = window.loc[:, window.notna().mean() >= cfg["minCoverage"]]
    if MARKET_INDEX not in window.columns:
        raise OptimizerError(f"{MARKET_INDEX} has too little history in the estimation window.")
    returns = window.pct_change(fill_method=None).iloc[1:].dropna()
    if len(returns) < 120:
        raise OptimizerError("Not enough common trading days to estimate the portfolio.")
    market = returns.pop(MARKET_INDEX)
    market_return = float(market.mean() * TRADING_DAYS)
    symbols = list(returns.columns)

    beta = returns.apply(lambda column: column.cov(market)) / market.var()
    mu = cfg["riskFreeRate"] + beta * (market_return - cfg["riskFreeRate"])
    sigma = ledoit_wolf_covariance(returns.values) * TRADING_DAYS

    meta = candidates.loc[symbols]
    industries = meta["industry"].to_numpy()
    is_excluded = np.isin(industries, excluded)
    is_preferred = np.isin(industries, list(minimums))
    max_weight = cfg["maxWeight"]
    _check_reachable(industries, excluded, minimums, cfg)
    keep = ~is_excluded

    mu_values = mu.to_numpy()
    mu_perceived = mu_values + cfg["preferredBonus"] * is_preferred

    def solve(active: np.ndarray) -> np.ndarray:
        """Poids sur les titres `active` (les autres à 0), contraintes d'industrie incluses."""
        groups: list[tuple[np.ndarray, float | None, float | None]] = []
        for industry in pd.unique(industries[active]):
            mask = (industries == industry)[active]
            cap = cfg["preferredIndustryCap"] if industry in minimums else cfg["industryCap"]
            groups.append((mask, cap, minimums.get(industry) or None))
        solved = solve_mean_variance(
            sigma[np.ix_(active, active)], mu_perceived[active], aversion, np.full(int(active.sum()), max_weight), groups
        )
        full = np.zeros(len(symbols))
        full[active] = np.round(solved, 6)
        return full

    try:
        weights = solve(keep)
    except ValueError as error:
        raise OptimizerError(
            "No portfolio satisfies all the constraints (weight and industry limits, minimums, exclusions)."
        ) from error
    small = (weights < cfg["minPositionWeight"]) & keep
    if small.any():
        try:
            weights = solve(keep & ~small)
        except ValueError:
            weights = np.where(small, 0.0, weights)
    weights = weights / weights.sum()

    expected = float(weights @ mu_values)
    variance = float(weights @ sigma @ weights)
    industry_weights = pd.Series(weights, index=industries).groupby(level=0).sum()
    by_industry = {k: float(v) for k, v in industry_weights[industry_weights > 0].sort_values(ascending=False).items()}
    holdings = [
        Holding(symbol=symbols[i], name=str(meta["name"].iloc[i] or symbols[i]), industry=str(industries[i]),
                weight=float(weights[i]), beta=float(beta.iloc[i]), expected_return=float(mu_values[i]))
        for i in np.argsort(-weights) if weights[i] > 0
    ]
    return OptimizationResult(
        holdings=holdings, expected_return=expected, volatility=math.sqrt(variance),
        utility=expected - aversion / 2.0 * variance, beta=float(weights @ beta.to_numpy()),
        preferred_share=float(weights[is_preferred].sum()), by_industry=by_industry, aversion=aversion,
        risk_profile=int(risk_profile), window=(returns.index.min(), returns.index.max()),
        observations=int(len(returns)), universe_size=len(symbols), excluded_industries=excluded,
        preferred_industries=[{"industry": k, "minWeight": v or None} for k, v in minimums.items()], config=cfg,
    )
