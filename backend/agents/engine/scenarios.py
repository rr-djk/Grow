"""Scénarios 0/1/2 d'un mandat confirmé et leurs mesures (module-engine).

0 : portefeuille actuel ; 1 : idée appliquée telle quelle ; 2 : comparaison par
catégorie d'actifs, seulement si l'utilisateur la demande en choisissant une
catégorie (mandat.compareCategory, lot B). Elle garde le montant de l'idée et
remplace chaque titre ajouté par la catégorie choisie, sans juger le titre.
Le FNB qui la représente n'est qu'une approximation de calcul : aucun texte
visible sans clic (libellé, description, proxyNote, libellés de preuve, notes)
ne le nomme ; son symbole n'apparaît que dans method et source de la preuve (R5).

Chaque mesure devient un élément du registre (EV-nn) ; scenario.metrics ne
contient que des identifiants EV.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.agents.data.store import DataStore
from backend.agents.engine import analytics as an
from backend.agents.engine import optimizer
from backend.agents.engine.concentration import by_asset_class, concentration, top_sector
from backend.agents.engine.registry import EvidenceRegistry
from backend.agents.engine.stress import LABELS as STRESS_LABELS
from backend.agents.engine.stress import PERIOD_IDS, StressPeriod, derive_period
from backend.agents.rules.settings import risk_band, settings
from backend.common.categories import get_category

PORTFOLIO_METHOD = (
    "Constant-weight portfolio (daily rebalanced) on adjusted close (adjclose) converted to CAD "
    "with the last known USD/CAD rate; common North American trading days of the holdings."
)
VOL_METHOD = "Standard deviation of daily returns x sqrt(252) (equities, ETFs) or sqrt(365) (crypto)."
DD_METHOD = "Largest peak-to-trough decline of the value index over the window."
HOLDING_LABEL_PREFIX = "Holding "
BUILD_METHOD = (
    "Mean-variance model U = w'mu - (A/2) w'Sigma w: mu from the CAPM (beta against the S&P 500 index, risk-free rate), "
    "Sigma from the Ledoit-Wolf covariance of daily returns, constraints on single-stock and industry weights. "
    "Expected returns are a model of the past window, not a forecast."
)
PAST_CAVEATS = ["Past performance describes the past; it does not predict future returns."]
SURVIVOR_CAVEAT = "Survivorship bias: the asset universe was selected in 2026."

STRESS_METRIC_KEYS = {
    "y2022": "stress2022",
    "covid_2020": "stressCovid2020",
    "rate_hikes": "stressRates",
    "crypto_crash": "stressCrypto",
}


@dataclass
class ScenarioAnalysis:
    """Résultats chiffrés d'un scénario, lus par module-rules (jamais envoyés bruts au modèle)."""

    index: int
    label: str
    positions_cad: dict[str, float]
    weights: dict[str, float]
    metrics: dict[str, float] = field(default_factory=dict)
    stress: dict[str, float] = field(default_factory=dict)
    concentration: dict[str, Any] = field(default_factory=dict)
    idea_assets: list[dict[str, Any]] = field(default_factory=list)
    portfolio_band: int | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    description: str | None = None
    proxy_note: str | None = None
    notes: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    holdings: list[dict[str, Any]] = field(default_factory=list)
    parameters: list[dict[str, Any]] = field(default_factory=list)

    def shown(self, tickers: list[str]) -> list[str]:
        """Noms à afficher : la catégorie à la place du symbole d'approximation."""
        return [self.names.get(t, t) for t in tickers]

    def hide_symbols(self, text: str) -> str:
        for symbol, label in self.names.items():
            text = text.replace(symbol, label)
        return text


@dataclass
class EngineResult:
    as_of: pd.Timestamp
    window: tuple[pd.Timestamp, pd.Timestamp]
    scenarios: list[ScenarioAnalysis]
    stress_periods: dict[str, StressPeriod]
    registry: EvidenceRegistry
    sources: list[dict[str, Any]]
    macro_usage: list[dict[str, Any]]
    warnings: list[str]
    compare_requested: bool = False



def holding_values_cad(store: DataStore, holdings: list[dict[str, Any]], as_of: pd.Timestamp) -> tuple[dict[str, float], list[str]]:
    """Valeur CAD de chaque position au dernier cours (close) connu à as_of."""
    values: dict[str, float] = {}
    warnings: list[str] = []
    rate = an.fx_rate_on(store, as_of)
    for holding in holdings:
        ticker = holding["ticker"]
        if not store.has_ticker(ticker):
            warnings.append(f"{ticker} is not in the dataset universe: position ignored.")
            continue
        prices = store.prices(ticker)
        known = prices[prices.index <= as_of]
        if known.empty:
            warnings.append(f"No price for {ticker} on or before {as_of.date()}: position ignored.")
            continue
        last_day = known.index[-1]
        if (as_of - last_day).days > 5:
            warnings.append(f"Last price for {ticker} dated {last_day.date()} (stale).")
        price = float(known["close"].iloc[-1])
        value = price * float(holding["quantity"])
        if an.listing_currency(store, ticker) == "USD":
            value *= rate
        values[ticker] = values.get(ticker, 0.0) + value
    return values, warnings


def quantity_for_value_cad(store: DataStore, symbol: str, value_cad: float, as_of: pd.Timestamp) -> tuple[float, float, str] | None:
    """Inverse de holding_values_cad : (quantité, dernier cours, devise de cotation) pour une valeur en CAD, ou None sans cours."""
    if not store.has_ticker(symbol):
        return None
    prices = store.prices(symbol)
    known = prices[prices.index <= as_of]
    if known.empty:
        return None
    price = float(known["close"].iloc[-1])
    if price <= 0:
        return None
    currency = an.listing_currency(store, symbol)
    unit_cad = price * an.fx_rate_on(store, as_of) if currency == "USD" else price
    return value_cad / unit_cad, price, currency


def _amount_cad(store: DataStore, amount: float, currency: str | None, as_of: pd.Timestamp) -> float:
    return amount * an.fx_rate_on(store, as_of) if currency == "USD" else amount


def apply_operations(
    store: DataStore, positions: dict[str, float], operations: list[dict[str, Any]], as_of: pd.Timestamp, default_currency: str
) -> dict[str, float]:
    result = dict(positions)
    for op in operations:
        ticker = op["ticker"]
        action = op["action"]
        if action == "add":
            result[ticker] = result.get(ticker, 0.0) + _amount_cad(store, float(op.get("amount", 0.0)), op.get("currency") or default_currency, as_of)
        elif action == "remove":
            amount = op.get("amount")
            current = result.get(ticker, 0.0)
            removed = current if amount is None else min(current, _amount_cad(store, float(amount), op.get("currency") or default_currency, as_of))
            result[ticker] = current - removed
        elif action == "set_weight":
            target = float(op.get("weight", 0.0)) / 100.0
            total = sum(result.values())
            others = {t: v for t, v in result.items() if t != ticker}
            other_total = sum(others.values())
            if total <= 0:
                continue
            result = {t: v / other_total * total * (1 - target) for t, v in others.items()} if other_total else {}
            result[ticker] = total * target
    return {t: v for t, v in result.items() if v > 1e-9}


def _weights(positions: dict[str, float]) -> dict[str, float]:
    total = sum(positions.values())
    return {t: v / total * 100.0 for t, v in positions.items()} if total else {}



def _crypto_refused(mandate: dict[str, Any]) -> bool:
    preferences = mandate.get("preferences") or {}
    excluded = [c.lower() for c in preferences.get("excludedAssetClasses") or []]
    constraints = " ".join(mandate.get("constraints") or []).lower()
    return "crypto" in excluded or "no crypto" in constraints


def _asset_band(store: DataStore, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> tuple[int | None, float | None]:
    metrics = an.asset_metrics(store, ticker, start, end)
    vol = metrics.get("volatility")
    if vol is None or vol != vol:
        return None, None
    return risk_band(vol), vol


@dataclass
class Comparison:
    """Catégorie choisie par l'utilisateur et FNB qui la représente pour le calcul seulement."""

    category_id: str
    label: str
    proxy: str
    band: int


def resolve_comparison(store: DataStore, category_id: str | None, start: pd.Timestamp, end: pd.Timestamp) -> Comparison | None:
    """Catégorie demandée + premier FNB d'approximation avec des cours sur la fenêtre ; None si indisponible."""
    category = get_category(category_id)
    if category is None:
        return None
    for proxy in category["proxies"]:
        if not store.has_ticker(proxy):
            continue
        band, _ = _asset_band(store, proxy, start, end)
        if band is not None:
            return Comparison(category["id"], category["label"], proxy, band)
    return None


def comparison_operations(mandate: dict[str, Any], comparison: Comparison) -> list[dict[str, Any]] | None:
    """Opérations du scénario 2 : chaque titre ajouté (add, set_weight) est remplacé par la catégorie, au même montant.

    Le titre n'est pas jugé : la comparaison ne dépend ni de sa volatilité ni du profil. Deux opérations qui visent
    la même catégorie sont cumulées (deux set_weight ne s'écraseraient pas). None si l'idée n'ajoute aucun titre.
    """
    operations: list[dict[str, Any]] = []
    weight_index: int | None = None
    replaced = False
    for op in mandate.get("operations") or []:
        if op["action"] not in ("add", "set_weight"):
            operations.append(op)
            continue
        replaced = True
        if op["action"] == "set_weight":
            if weight_index is None:
                weight_index = len(operations)
                operations.append({**op, "ticker": comparison.proxy, "weight": float(op.get("weight", 0.0))})
            else:
                operations[weight_index]["weight"] += float(op.get("weight", 0.0))
        else:
            operations.append({**op, "ticker": comparison.proxy})
    return operations if replaced else None



def _analysis_window(store: DataStore) -> tuple[pd.Timestamp, pd.Timestamp]:
    end = store.last_date()
    start = end - pd.DateOffset(years=int(settings()["windowYears"]))
    return pd.Timestamp(start), pd.Timestamp(end)


def _record_scenario_metrics(
    store: DataStore, registry: EvidenceRegistry, scenario: ScenarioAnalysis, start: pd.Timestamp, end: pd.Timestamp,
    periods: dict[str, StressPeriod], dataset_source: str,
) -> None:
    tickers = list(scenario.weights)
    aligned = an.aligned_cad_prices(store, tickers, start, end)
    if aligned.missing:
        scenario.notes.append("No price data on the window for " + ", ".join(scenario.shown(aligned.missing)) + ".")
    caveats = list(PAST_CAVEATS) + [SURVIVOR_CAVEAT]
    if aligned.shortened_by:
        caveats.append(
            "Window shortened to the common history of the holdings because of " + ", ".join(scenario.shown(aligned.shortened_by)) + "."
        )
    metrics = an.portfolio_metrics(aligned.frame, scenario.weights)
    window = an.window_label(aligned.start, aligned.end)
    if metrics:
        scenario.metrics = {k: metrics[k] for k in ("volatility", "maxDrawdown", "totalReturn")}
        scenario.portfolio_band = risk_band(metrics["volatility"])
        scenario.evidence["volatility"] = registry.add(
            kind="metric", label=f"Annualized volatility, scenario {scenario.index}", value=metrics["volatility"],
            scenario=scenario.index, method=f"{VOL_METHOD} {PORTFOLIO_METHOD}", window=window, currency="CAD",
            source=dataset_source, as_of=end.date().isoformat(), caveats=caveats, key="volatility",
        )
        scenario.evidence["maxDrawdown"] = registry.add(
            kind="metric", label=f"Maximum drawdown, scenario {scenario.index}", value=metrics["maxDrawdown"],
            scenario=scenario.index, method=f"{DD_METHOD} {PORTFOLIO_METHOD}", window=window, currency="CAD",
            source=dataset_source, as_of=end.date().isoformat(), caveats=caveats, key="maxDrawdown",
        )
        scenario.evidence["totalReturn"] = registry.add(
            kind="metric", label=f"Total return over the window, scenario {scenario.index}", value=metrics["totalReturn"],
            scenario=scenario.index, method=f"Change of the value index over the window. {PORTFOLIO_METHOD}",
            window=window, currency="CAD", source=dataset_source, as_of=end.date().isoformat(), caveats=caveats,
            key="totalReturn",
        )

    ranges = an.bootstrap_ranges(an.portfolio_index(aligned.frame, scenario.weights)) if metrics else {}
    if ranges:
        range_method = (
            f"Moving-block bootstrap ({ranges['resamples']} resamples, {ranges['blockDays']}-day blocks, fixed seed) of the "
            f"portfolio's daily returns over the window; 5th to 95th percentile. It shows how much the figure depends on the "
            f"period observed, not what the future holds. {PORTFOLIO_METHOD}"
        )
        fmt = "{:.1f}".format
        vol_low, vol_high = fmt(ranges["volatilityLow"]), fmt(ranges["volatilityHigh"])
        dd_low, dd_high = fmt(ranges["maxDrawdownLow"]), fmt(ranges["maxDrawdownHigh"])
        if registry.language == "fr":
            vol_text = f"{vol_low} % à {vol_high} %".replace(".", ",")
            dd_text = f"{dd_low} % à {dd_high} %".replace(".", ",")
        else:
            vol_text, dd_text = f"{vol_low}% to {vol_high}%", f"{dd_low}% to {dd_high}%"
        scenario.evidence["volatilityRange"] = registry.add(
            kind="metric", label=f"Annualized volatility, 90% resampling range, scenario {scenario.index}",
            value=(ranges["volatilityLow"] + ranges["volatilityHigh"]) / 2, formatted=vol_text,
            scenario=scenario.index, method=range_method, window=window, currency="CAD", source=dataset_source,
            as_of=end.date().isoformat(), caveats=caveats, key="volatilityRange",
        )
        scenario.evidence["maxDrawdownRange"] = registry.add(
            kind="metric", label=f"Maximum drawdown, 90% resampling range, scenario {scenario.index}",
            value=(ranges["maxDrawdownLow"] + ranges["maxDrawdownHigh"]) / 2, formatted=dd_text,
            scenario=scenario.index, method=range_method, window=window, currency="CAD", source=dataset_source,
            as_of=end.date().isoformat(), caveats=caveats, key="maxDrawdownRange",
        )

    for period_id, period in periods.items():
        if not period.available:
            continue
        stressed = an.aligned_cad_prices(store, tickers, period.start, period.end, require_full_window=True)
        if stressed.missing or stressed.frame.empty:
            scenario.notes.append(
                f"{STRESS_LABELS[period_id]} not computed: insufficient history for "
                + ", ".join(scenario.shown(stressed.missing or tickers)) + "."
            )
            continue
        index = an.portfolio_index(stressed.frame, scenario.weights)
        if index.empty:
            continue
        drawdown, _, _ = an.max_drawdown(index)
        key = STRESS_METRIC_KEYS[period_id]
        scenario.stress[period_id] = drawdown
        scenario.evidence[key] = registry.add(
            kind="metric", label=f"Maximum drawdown during {STRESS_LABELS[period_id].split(': ', 1)[1]}, scenario {scenario.index}",
            value=drawdown, scenario=scenario.index, method=f"{DD_METHOD} {PORTFOLIO_METHOD} Period: {period.method}",
            window=an.window_label(period.start, period.end), currency="CAD", source=dataset_source,
            caveats=PAST_CAVEATS, key=key,
        )

    conc = concentration(store, scenario.weights)
    scenario.concentration = conc
    conc_caveats = [scenario.hide_symbols(c) for c in conc["caveats"]] or None
    conc_source = dataset_source + (
        "; " + "; ".join(conc["sources"]) if conc["sources"] else ""
    )
    if conc["topSingle"]["ticker"]:
        scenario.evidence["topSingleWeight"] = registry.add(
            kind="metric", label=f"Largest single-security weight (direct positions plus the fund holdings available in the dataset), scenario {scenario.index}",
            value=conc["topSingle"]["weight"], scenario=scenario.index,
            method="Direct positions plus each fund's published top holdings, as a share of the portfolio.",
            source=conc_source, caveats=conc_caveats, key="topSingleWeight",
        )
    sector_label, sector_weight = top_sector(conc)
    if sector_label:
        scenario.evidence["topSectorWeight"] = registry.add(
            kind="metric", label=f"Largest sector weight ({sector_label}; direct positions plus the fund exposure available in the dataset), scenario {scenario.index}",
            value=sector_weight, scenario=scenario.index,
            method="Direct equities by sector plus each fund's published sector weights, as a share of the portfolio. Funds without a published composition are not counted in a sector.",
            source=conc_source, caveats=conc_caveats, key="topSectorWeight",
        )
    scenario.evidence["techWeightLookThrough"] = registry.add(
        kind="metric", label=f"Information Technology weight (direct positions plus the fund exposure available in the dataset), scenario {scenario.index}",
        value=conc["techLookThrough"], scenario=scenario.index,
        method="Direct IT equities plus each fund's published IT sector weight, as a share of the portfolio.",
        source=conc_source, caveats=conc_caveats, key="techWeightLookThrough",
    )
    scenario.evidence["cryptoWeight"] = registry.add(
        kind="metric", label=f"Crypto-asset weight, scenario {scenario.index}", value=conc["cryptoWeight"],
        scenario=scenario.index, method="Crypto-asset positions as a share of the portfolio.", source=dataset_source,
        key="cryptoWeight",
    )


def _fmt2(value: float, language: str) -> str:
    text = f"{value:.2f}"
    return text.replace(".", ",") if language == "fr" else text


def _build_scenario(
    store: DataStore, mandate_item: dict[str, Any], positions0: dict[str, float], registry: EvidenceRegistry,
    start: pd.Timestamp, end: pd.Timestamp,
) -> tuple[ScenarioAnalysis | None, str | None]:
    """Mode build : scénario 1 = portefeuille moyenne-variance construit à partir des paramètres du mandat."""
    mandate = mandate_item["mandate"]
    preferences = mandate.get("preferences") or {}
    preferred = [
        {"industry": p["industry"], "minWeight": p["minWeight"] / 100.0 if p.get("minWeight") is not None else None}
        for p in preferences.get("preferredIndustries") or []
    ]
    try:
        result = optimizer.optimize_portfolio(
            store, int(mandate_item["riskProfile"]), preferences.get("excludedIndustries") or [], preferred
        )
    except optimizer.OptimizerError as error:
        return None, str(error)
    language = registry.language
    source = store.source_label("prices") + " (Yahoo Finance via yfinance)"
    window = an.window_label(result.window[0], result.window[1])
    as_of = end.date().isoformat()
    requested = mandate.get("buildAmount")
    if requested:
        total, amount_origin = float(requested), "user"
    elif sum(positions0.values()):
        total, amount_origin = sum(positions0.values()), "portfolio"
    else:
        total, amount_origin = 100_000.0, "default"
    positions = {h.symbol: h.weight * total for h in result.holdings}
    scenario = ScenarioAnalysis(1, "Constructed portfolio", positions, _weights(positions))
    scenario.description = (
        "Simulation built from your parameters with a mean-variance model; it is not a recommendation to buy or hold any security."
    )
    caveats = list(PAST_CAVEATS) + [SURVIVOR_CAVEAT, "Expected returns are a CAPM model of the observed window, not a forecast."]
    cfg = result.config
    common = dict(scenario=1, window=window, source=source, as_of=as_of)

    def pct(value: float) -> float:
        return value * 100.0

    scenario.evidence["expectedReturn"] = registry.add(
        kind="metric", label="Expected annual return of the constructed portfolio (CAPM, model)", value=pct(result.expected_return),
        method=f"Weighted CAPM expected return. {BUILD_METHOD}", currency="USD", caveats=caveats, key="buildExpectedReturn", **common,
    )
    scenario.evidence["beta"] = registry.add(
        kind="metric", label="Beta of the constructed portfolio against the broad market index", value=result.beta,
        formatted=_fmt2(result.beta, language), unit="",
        method="Weighted beta = covariance with the index daily returns / variance of the index, listing currency.",
        caveats=caveats, key="buildBeta", **common,
    )
    scenario.evidence["utility"] = registry.add(
        kind="metric", label="Mean-variance utility of the constructed portfolio", value=result.utility,
        formatted=_fmt2(result.utility, language), unit="", method=BUILD_METHOD, caveats=caveats, key="buildUtility", **common,
    )
    aversion_id = registry.add(
        kind="assumption", label=f"Risk aversion coefficient used by the model (from risk profile {result.risk_profile})",
        value=result.aversion, formatted=_fmt2(result.aversion, language), unit="",
        method="Table of team assumptions by risk profile (1 to 5): a lower profile means a higher aversion.",
        source=source, window=window, as_of=as_of, key="buildAversion",
    )
    registry.add(
        kind="assumption", label="Risk-free rate used by the model (team assumption)", value=pct(cfg["riskFreeRate"]),
        method="Fixed team assumption in optimizer_config.json.", source=source, window=window, as_of=as_of, key="buildRiskFree",
    )
    scenario.parameters = [
        {"key": "riskAversion", "value": result.aversion, "riskProfile": result.risk_profile, "evidence": aversion_id},
        {"key": "maxWeight", "value": pct(cfg["maxWeight"])},
        {"key": "industryCap", "value": pct(cfg["industryCap"])},
        {"key": "preferredIndustryCap", "value": pct(cfg["preferredIndustryCap"])},
        {"key": "windowYears", "value": cfg["windowYears"]},
    ]
    amount_param: dict[str, Any] = {"key": "amount", "value": round(total, 2), "currency": "CAD", "origin": amount_origin}
    if amount_origin == "default":
        amount_param["evidence"] = registry.add(
            kind="assumption", label="Notional amount used for an empty portfolio (team assumption), CAD", value=total, unit="", formatted=f"{total:,.0f} CAD".replace(",", " "),
            method="Fixed team assumption: the empty portfolio is built on a notional amount.",
            source=source, window=window, as_of=as_of, currency="CAD", key="buildAmount",
        )
    scenario.parameters.append(amount_param)
    if result.excluded_industries:
        scenario.parameters.append({"key": "excludedIndustries", "value": result.excluded_industries})
    if result.preferred_industries:
        scenario.parameters.append({"key": "preferredIndustries", "value": result.preferred_industries})
    for holding in result.holdings:
        label = f"{HOLDING_LABEL_PREFIX}{holding.symbol}"
        weight_id = registry.add(
            kind="metric", label=f"{label}: weight in the constructed portfolio", value=pct(holding.weight),
            method=f"Optimizer weight, rounded; positions under {pct(cfg['minPositionWeight']):.1f}% are dropped. {BUILD_METHOD}",
            caveats=caveats, key=f"holding:{holding.symbol}:weight", **common,
        )
        beta_id = registry.add(
            kind="metric", label=f"{label}: beta against the broad market index", value=holding.beta,
            formatted=_fmt2(holding.beta, language), unit="", method="Covariance with the index / variance of the index, daily returns.",
            caveats=caveats, key=f"holding:{holding.symbol}:beta", **common,
        )
        expected_id = registry.add(
            kind="metric", label=f"{label}: expected annual return (CAPM, model)", value=pct(holding.expected_return),
            method=f"risk-free rate + beta x (index return - risk-free rate). {BUILD_METHOD}", caveats=caveats,
            key=f"holding:{holding.symbol}:expected", **common,
        )
        entry = {
            "symbol": holding.symbol, "name": holding.name, "industry": holding.industry,
            "weight": round(pct(holding.weight), 2),
            "evidence": {"weight": weight_id, "beta": beta_id, "expectedReturn": expected_id},
        }
        sized = quantity_for_value_cad(store, holding.symbol, positions[holding.symbol], end)
        if sized:
            quantity, last_price, listing = sized
            entry.update({"quantity": round(quantity, 4), "price": round(last_price, 4), "currency": listing})
        scenario.holdings.append(entry)
    scenario.notes.append(
        f"The model was estimated on {result.observations} common trading days over {result.universe_size} stocks "
        f"({window}); candidates are USD-listed equities with an industry in the dataset."
    )
    return scenario, None


def run_engine(
    store: DataStore,
    mandate_item: dict[str, Any],
    portfolio: dict[str, Any] | None,
    registry: EvidenceRegistry,
) -> EngineResult:
    """Construit les scénarios et inscrit toutes les mesures au registre."""
    mandate = mandate_item["mandate"]
    compare_requested = bool(mandate.get("compareCategory"))
    start, end = _analysis_window(store)
    dataset_source = store.source_label("prices") + " (Yahoo Finance via yfinance); fx/usdcad.parquet (Bank of Canada Valet)"
    holdings = (portfolio or {}).get("holdings") or []
    base_currency = (portfolio or {}).get("baseCurrency") or "CAD"
    warnings: list[str] = []

    positions0, value_warnings = holding_values_cad(store, holdings, end)
    warnings.extend(value_warnings)
    periods = {pid: derive_period(store, pid) for pid in PERIOD_IDS}
    macro_usage: list[dict[str, Any]] = []
    if periods["rate_hikes"].available:
        series_id = "V39079" if "V39079" in periods["rate_hikes"].method else "DFF"
        used_up_to = periods["rate_hikes"].end
        macro = store.macro()
        rows = macro[(macro["series_id"] == series_id) & (macro["date"] <= used_up_to)]
        publication = None
        if "publication_date" in rows.columns and not rows.empty:
            publication = rows["publication_date"].max()
        macro_usage.append({"seriesId": series_id, "usedUpTo": used_up_to, "publication": publication, "asOf": end})

    for period_id, period in periods.items():
        if period.available:
            registry.add(
                kind="assumption", label=STRESS_LABELS[period_id], formatted=an.window_label(period.start, period.end),
                method=period.method, window=an.window_label(period.start, period.end), source=period.source,
                key=f"period:{period_id}",
            )
    registry.add(
        kind="assumption", label="Analysis window (team assumption)", value=float(settings()["windowYears"]),
        unit="years" if registry.language != "fr" else "ans", window=an.window_label(start, end),
        method="Trailing window ending at the last price date of the dataset.", source=dataset_source,
        as_of=end.date().isoformat(), key="window",
    )

    scenarios: list[ScenarioAnalysis] = []
    operations = mandate.get("operations") or []
    s0 = ScenarioAnalysis(0, "Current portfolio", positions0, _weights(positions0))
    scenarios.append(s0)
    if mandate.get("mode") == "build":
        built, build_error = _build_scenario(store, mandate_item, positions0, registry, start, end)
        if built is not None:
            scenarios.append(built)
        else:
            warnings.append(f"The portfolio could not be constructed: {build_error}")
    elif operations:
        positions1 = apply_operations(store, positions0, operations, end, base_currency)
        s1 = ScenarioAnalysis(1, "Idea as stated", positions1, _weights(positions1))
        s1.idea_assets = _idea_assets(store, operations, start, end)
        scenarios.append(s1)
        if compare_requested:
            comparison = resolve_comparison(store, mandate["compareCategory"], start, end)
            ops2 = comparison_operations(mandate, comparison) if comparison else None
            if comparison and ops2:
                positions2 = apply_operations(store, positions0, ops2, end, base_currency)
                s2 = ScenarioAnalysis(2, "Comparison by asset category", positions2, _weights(positions2))
                s2.names = {comparison.proxy: comparison.label}
                s2.description = (
                    f"Same amount allocated to {comparison.label}, a category this tool places at level {comparison.band}."
                )
                s2.proxy_note = f"{comparison.label} is approximated by a fund of the dataset for the calculation only."
                s2.idea_assets = _idea_assets(store, ops2, start, end)
                registry.add(
                    kind="assumption", label=f"Risk level of the category {comparison.label} (volatility band)",
                    value=float(comparison.band), formatted=str(comparison.band), scenario=2, window=an.window_label(start, end),
                    method="Level 1 to 5 read from the annualized volatility of the approximation fund (team assumption bands).",
                    source=dataset_source, key="comparisonLevel",
                )
                scenarios.append(s2)

    for scenario in scenarios:
        if not scenario.weights:
            scenario.notes.append("Empty portfolio: no metric computed.")
            continue
        _record_scenario_metrics(store, registry, scenario, start, end, periods, dataset_source)

    subject = mandate.get("subjectTicker")
    idea_tickers = {a["ticker"] for s in scenarios if s.index != 2 for a in s.idea_assets}
    asset_evidence: dict[str, dict[str, str]] = {}
    for ticker in sorted(idea_tickers | ({subject} if subject else set())):
        asset_evidence[ticker] = _record_asset_metrics(store, registry, ticker, start, end)
    for scenario in scenarios:
        if scenario.index == 2:
            category_evidence = _record_asset_metrics(store, registry, comparison.proxy, start, end, category=comparison)
            for asset in scenario.idea_assets:
                asset["evidence"] = category_evidence.get("volatility")
            continue
        for asset in scenario.idea_assets:
            asset["evidence"] = asset_evidence.get(asset["ticker"], {}).get("volatility")

    sources = [
        {"id": "prices_daily", "dataset": store.source_label("prices"), "asOf": end.date().isoformat(),
         "note": "adjclose for returns, close for valuation; listing currency converted to CAD"},
        {"id": "fx_usdcad", "dataset": store.source_label("fx/usdcad.parquet"), "note": "last known rate carried forward"},
    ]
    if macro_usage:
        sources.append({"id": "macro", "dataset": store.source_label("macro/macro.parquet"),
                        "note": "policy rate used to derive the hiking-cycle stress period"})
    if store.etf_enriched():
        sources.append({"id": "etf_enriched", "dataset": store.source_label("etf_enriched.json"),
                        "note": "issuer fund sheets (dated) for look-through"})
    return EngineResult(end, (start, end), scenarios, periods, registry, sources, macro_usage, warnings, compare_requested)


def _idea_assets(store: DataStore, operations: list[dict[str, Any]], start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, Any]]:
    assets = []
    for op in operations:
        if op["action"] not in ("add", "set_weight") or not store.has_ticker(op["ticker"]):
            continue
        band, vol = _asset_band(store, op["ticker"], start, end)
        asset_class = store.asset(op["ticker"]).get("asset_class")
        assets.append({"ticker": op["ticker"], "band": band, "volatility": vol,
                       "crypto": an.is_crypto(op["ticker"], asset_class)})
    return assets


def _record_asset_metrics(
    store: DataStore, registry: EvidenceRegistry, ticker: str, start: pd.Timestamp, end: pd.Timestamp,
    category: Comparison | None = None,
) -> dict[str, str]:
    """Inscrit la volatilité et la pire baisse d'un titre ; renvoie leurs identifiants EV-nn.

    Avec `category`, le titre est le FNB d'approximation : libellés au nom de la catégorie, symbole seulement dans
    method et source, avec la mention « calculation only, not a selection »."""
    metrics = an.asset_metrics(store, ticker, start, end)
    if not metrics:
        return {}
    currency = an.listing_currency(store, ticker)
    window = an.window_label(metrics["start"], metrics["end"])
    source = store.source_label(f"prices/{ticker}.parquet")
    root = "sqrt(365)" if metrics["periods"] == 365 else "sqrt(252)"
    if category is not None:
        subject = f"the category {category.label} (approximated)"
        note = f" Approximation of the category by fund {ticker}: calculation only, not a selection."
        key = f"category:{category.category_id}"
    else:
        subject, note, key = f"{ticker} (listing currency)", "", f"asset:{ticker}"
    volatility_id = registry.add(
        kind="metric", label=f"Annualized volatility of {subject}", value=metrics["volatility"],
        method=f"Standard deviation of daily returns x {root}, native calendar, adjclose.{note}", window=window,
        currency=currency, source=source, caveats=PAST_CAVEATS, key=f"{key}:volatility",
    )
    drawdown_id = registry.add(
        kind="metric", label=f"Maximum drawdown of {subject}", value=metrics["maxDrawdown"],
        method=f"Largest peak-to-trough decline of adjclose over the window, native calendar.{note}", window=window,
        currency=currency, source=source, caveats=PAST_CAVEATS, key=f"{key}:maxDrawdown",
    )
    return {"volatility": volatility_id, "maxDrawdown": drawdown_id}


def public_scenarios(result: EngineResult, verdicts_by_scenario: dict[int, str]) -> list[dict[str, Any]]:
    """Scénarios au format schema-scenario (scenario.metrics = identifiants EV-nn)."""
    store_free = []
    for scenario in result.scenarios:
        item: dict[str, Any] = {
            "index": scenario.index,
            "label": scenario.label,
            "metrics": dict(scenario.evidence),
            "verdict": verdicts_by_scenario.get(scenario.index, "pass"),
        }
        if scenario.description:
            item["description"] = scenario.description
        if scenario.proxy_note:
            item["proxyNote"] = scenario.proxy_note
        if scenario.holdings:
            item["holdings"] = scenario.holdings
        if scenario.parameters:
            item["parameters"] = scenario.parameters
        store_free.append(item)
    return store_free


def attach_allocations(store: DataStore, result: EngineResult, scenarios: list[dict[str, Any]]) -> None:
    by_index = {s.index: s for s in result.scenarios}
    for item in scenarios:
        item["allocation"] = by_asset_class(store, by_index[item["index"]].weights)
