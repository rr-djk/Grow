"""Les 15 outils du contrat (section tools), en fonctions pures du contexte.

Chaque outil valide ses paramètres et construit lui-même sa lecture
(rule-tool-validation). Une erreur attendue est renvoyée comme
{ "error": "<quoi corriger>" }, jamais levée vers le modèle. Aucune réponse ne
dépasse les plafonds du contrat (20 actifs, 260 points, 5 passages KB) ni ne
contient de lignes brutes (rule-no-raw-rows).
"""

from __future__ import annotations

import difflib
import json
import re
import threading
import unicodedata
from datetime import date
from typing import Any

import pandas as pd

from backend.agents.data.store import NON_INVESTABLE_CLASSES
from backend.agents.engine import analytics as an
from backend.agents.engine import optimizer
from backend.agents.engine.concentration import concentration as concentration_of
from backend.agents.engine.scenarios import holding_values_cad, run_engine
from backend.agents.engine.stress import PERIOD_IDS, derive_period
from backend.agents.rules.rules import check_rules as run_rules
from backend.agents.tools import kb
from backend.agents.tools.context import RequestContext
from backend.common.http import ApiError
from backend.common.mandates import evaluate_mandate
from backend.common.repositories import analyses as analyses_repo
from backend.common.repositories import portfolios as portfolios_repo
from backend.common.repositories import users as users_repo
from backend.common.validation import validate_mandate_create

MAX_ASSETS = 20
MAX_SEARCH_TERMS = 8
MIN_FUZZY_CHARS = 4
NAME_ALIASES = {
    "banque royale": "royal bank", "banque td": "toronto dominion", "banque de montreal": "bank of montreal",
    "banque scotia": "nova scotia", "banque de la nouvelle ecosse": "nova scotia",
    "banque nationale": "national bank", "banque canadienne imperiale de commerce": "imperial commerce",
}
MAX_POINTS = 260
MAX_METRIC_TICKERS = 20
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
METRIC_NAMES = ("total_return", "volatility", "max_drawdown", "correlation")


def _error(message: str) -> dict[str, Any]:
    return {"error": message}


def _parse_date(value: Any, name: str) -> pd.Timestamp | str:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return f"{name} must be a date in YYYY-MM-DD format."
    try:
        return pd.Timestamp(date.fromisoformat(value))
    except ValueError:
        return f"{name} is not a valid calendar date."


def _unknown_ticker(ctx: RequestContext, ticker: str) -> dict[str, Any]:
    universe = list(ctx.store.universe().index)
    close = difflib.get_close_matches(str(ticker).upper(), universe, n=3, cutoff=0.5)
    hint = f" Closest symbols: {', '.join(close)}." if close else " Use search_assets to find the exact symbol."
    return _error(f"Unknown ticker '{ticker}': it must be an exact symbol of the dataset universe.{hint}")



def _norm(text: Any) -> str:
    """Minuscules, sans accents, ponctuation remplacée par des espaces (« Coca-Cola » = « coca cola »)."""
    plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain.lower()).split())


def _split_terms(query: str) -> list[str]:
    terms = [t.strip() for t in re.split(r"[,;\n]+", query) if t.strip()]
    return terms[:MAX_SEARCH_TERMS]


def _matches(term: str, ticker_n: str, name_n: str) -> int | None:
    """Rang de la correspondance (0 symbole exact, 1 début de symbole, 2 tous les mots, 3 sous-chaîne), sinon None."""
    needle = NAME_ALIASES.get(term, term)
    hay_tokens = (ticker_n + " " + name_n).split()
    if term == ticker_n:
        return 0
    if ticker_n.startswith(term):
        return 1
    tokens = needle.split()
    if tokens and all((t in hay_tokens) if len(t) == 1 else any(h.startswith(t) for h in hay_tokens) for t in tokens):
        return 2
    if len(needle) >= MIN_FUZZY_CHARS and needle in (ticker_n + " " + name_n):
        return 3
    return None


def search_assets(ctx: RequestContext, query: str, asset_class: str | None = None) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        return _error("query must be a non-empty string (name or symbol).")
    terms = _split_terms(query[:400])
    if not terms:
        return _error("query must be a non-empty string (name or symbol).")
    universe = ctx.store.universe()
    rows = [
        (ticker, row, _norm(ticker), _norm(row["name"]))
        for ticker, row in universe.iterrows()
        if (not asset_class or str(row["asset_class"]).lower() == asset_class.lower())
        and str(row["asset_class"]).lower() not in NON_INVESTABLE_CLASSES
    ]
    multi = len(terms) > 1
    per_term = max(MAX_ASSETS // len(terms), 3) if multi else MAX_ASSETS
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    not_found: list[dict[str, Any]] = []
    for term in terms:
        term_n = _norm(term)
        found = []
        for ticker, row, ticker_n, name_n in rows:
            rank = _matches(term_n, ticker_n, name_n)
            if rank is not None:
                found.append((rank, ticker, row))
        found.sort(key=lambda x: (x[0], x[1]))
        if not found:
            scored = sorted(
                ((difflib.SequenceMatcher(None, term_n, _norm(t.split(".")[0])).ratio(), t) for t, _, _, _ in rows),
                key=lambda x: (-x[0], x[1]),
            )
            not_found.append({"query": term, "closest": [t for r, t in scored if r >= 0.8][:3]})
            continue
        for _, ticker, row in found[:per_term]:
            if ticker in seen:
                continue
            seen.add(ticker)
            item = {
                "ticker": ticker, "name": str(row["name"] or ""), "assetClass": row["asset_class"],
                "sector": row["sector"], "currency": row["currency"],
            }
            if multi:
                item["query"] = term
            items.append(item)
    result: dict[str, Any] = {"items": items[:MAX_ASSETS]}
    if not_found:
        result["notFound"] = not_found
    return result


def _holding(ctx: RequestContext, h: dict[str, Any]) -> dict[str, Any]:
    """Position + nom, classe, secteur et devise lus dans l'univers : l'orchestrateur ne décrit pas le contenu de mémoire."""
    universe = ctx.store.universe()
    row = universe.loc[h["ticker"]] if h["ticker"] in universe.index else None
    return {
        "ticker": h["ticker"], "quantity": h["quantity"], "avgCost": h["avgCost"],
        "name": None if row is None else str(row["name"] or ""),
        "assetClass": None if row is None else row["asset_class"],
        "sector": None if row is None else row["sector"],
        "currency": None if row is None else row["currency"],
    }


def get_portfolio(ctx: RequestContext) -> dict[str, Any]:
    portfolio = portfolios_repo.get_portfolio(ctx.user_id, ctx.portfolio_id)
    if portfolio is None:
        return _error(f"No portfolio '{ctx.portfolio_id}' for the current user.")
    return {
        "portfolioId": portfolio["portfolioId"],
        "baseCurrency": portfolio["baseCurrency"],
        "holdings": [_holding(ctx, h) for h in portfolio.get("holdings", [])],
    }


def get_profile(ctx: RequestContext) -> dict[str, Any]:
    user = users_repo.get_user(ctx.user_id)
    profile = (user or {}).get("investorProfile")
    return {"investorProfile": {k: v for k, v in profile.items() if k != "riskLevel"} if profile else profile}


def _industry_key(name: str) -> str:
    """Clé de comparaison : casse, espaces, ponctuation et « & »/« and » n'ont pas d'effet (« Health Care Plans » = « Healthcare Plans »)."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower().replace("&", "and"))


def _fix_industry_name(name: str, known: list[str]) -> str | None:
    """Nom exact du jeu si une seule industrie correspond (après normalisation, ou à 0,85 de ressemblance), sinon None.

    Une ressemblance partagée entre plusieurs noms, ou trop faible, n'est jamais devinée : mieux vaut l'erreur que
    remplacer une industrie par une autre de sens différent."""
    key = _industry_key(name)
    same = [k for k in known if _industry_key(k) == key]
    if len(same) == 1:
        return same[0]
    if same:
        return None
    close = difflib.get_close_matches(name, known, n=2, cutoff=0.85)
    return close[0] if len(close) == 1 else None


def _check_build_preferences(ctx: RequestContext, mandate: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Industries exclues ou préférées du mode build : noms exacts du jeu, minimums atteignables.

    Renvoie (erreurs, corrections). Un nom presque exact est corrigé dans le mandat, et la correction est signalée à l'agent
    (champ `corrections` du retour de propose_mandate, hors schema-mandate-warning).
    Toutes les industries inconnues sont signalées d'un coup : l'agent corrige en un seul aller-retour (délai de 30 s)."""
    preferences = mandate.get("preferences") or {}
    universe = ctx.store.universe()
    known = sorted(set(universe["industry"].dropna())) if "industry" in universe.columns else []
    warnings: list[str] = []
    fixed: dict[str, str] = {}

    def resolve(name: str) -> str:
        if name in known:
            return name
        if name not in fixed:
            correct = _fix_industry_name(name, known)
            if correct is None:
                return name
            fixed[name] = correct
            warnings.append(f"Industry '{name}' was corrected to the dataset name '{correct}'.")
        return fixed[name]

    if preferences.get("excludedIndustries"):
        preferences["excludedIndustries"] = list(dict.fromkeys(resolve(n) for n in preferences["excludedIndustries"]))
    if preferences.get("preferredIndustries"):
        preferences["preferredIndustries"] = [{**p, "industry": resolve(p["industry"])} for p in preferences["preferredIndustries"]]
    excluded = list(preferences.get("excludedIndustries") or [])
    preferred = [{"industry": p["industry"], "minWeight": (p["minWeight"] / 100.0 if p.get("minWeight") is not None else None)}
                 for p in preferences.get("preferredIndustries") or []]
    problems: list[str] = []
    for name in dict.fromkeys(excluded + [p["industry"] for p in preferred]):
        if name not in known:
            close = difflib.get_close_matches(name, known, n=5, cutoff=0.4)
            problems.append(f"Unknown industry '{name}'. Use the dataset's English industry names" + (f", for example: {', '.join(close)}." if close else "."))
    if problems:
        return problems, warnings
    try:
        optimizer.check_preferences(universe, excluded, preferred)
    except optimizer.OptimizerError as error:
        return [str(error)], warnings
    return [], warnings


def propose_mandate(ctx: RequestContext, draft: dict[str, Any]) -> dict[str, Any]:
    """Valide un brouillon (schema-mandate-create-request) ; ne confirme rien."""
    if isinstance(draft, str):
        try:
            draft = json.loads(draft)
        except ValueError:
            return {"valid": False, "errors": ["draft must be a JSON object."]}
    if not isinstance(draft, dict):
        return {"valid": False, "errors": ["draft must be a JSON object."]}
    draft = {**draft, "portfolioId": ctx.portfolio_id, "userLanguage": ctx.user_language}
    draft.pop("compareCategory", None)
    if ctx.province and "province" not in draft:
        draft["province"] = ctx.province
    try:
        mandate = validate_mandate_create(draft)
    except ApiError as error:
        return {"valid": False, "errors": [error.message]}
    unknown = [op["ticker"] for op in mandate.get("operations", []) if not ctx.store.is_investable(op["ticker"])]
    if mandate.get("subjectTicker") and not ctx.store.is_investable(mandate["subjectTicker"]):
        unknown.append(mandate["subjectTicker"])
    if unknown:
        return {"valid": False, "errors": [f"Unknown ticker(s): {', '.join(unknown)}. Use search_assets."]}
    corrections: list[str] = []
    if mandate["mode"] == "build":
        if mandate.get("operations") or mandate.get("subjectTicker"):
            return {"valid": False, "errors": ["build describes a portfolio to construct: no operations and no subjectTicker."]}
        problems, corrections = _check_build_preferences(ctx, mandate)
        if problems:
            return {"valid": False, "errors": problems}
    if mandate["mode"] in ("add_asset", "rebalance") and not mandate.get("operations"):
        return {"valid": False, "errors": ["operations must describe the tested idea for add_asset and rebalance."]}
    if mandate["mode"] == "diagnose" and not mandate.get("subjectTicker"):
        return {"valid": False, "errors": ["subjectTicker is required for diagnose."]}
    if (mandate.get("fieldSources") or {}).get("riskCapacity") == "team_assumption":
        return {"valid": False, "errors": [
            "riskCapacity cannot be a team assumption: use the profile value, or ask the user for it with quick replies."]}
    derived = evaluate_mandate(mandate)
    ctx.captured["mandateDraft"] = mandate
    return {"valid": True, "errors": [], **derived, **({"corrections": corrections} if corrections else {})}


def read_evidence(ctx: RequestContext, evidence_id: str | None = None) -> dict[str, Any]:
    """Registre du run (complet résumé, ou un élément)."""
    if not ctx.evidence:
        return _error("No analysis run in this session yet: the registry is empty.")
    if evidence_id:
        if not re.fullmatch(r"(EV|KB)-\d{2,}", str(evidence_id)):
            return _error("evidence_id must look like EV-07 or KB-03.")
        item = next((e for e in ctx.evidence if e["id"] == evidence_id), None)
        return item if item else _error(f"{evidence_id} is not in the registry of the latest run.")
    summary = []
    for item in ctx.evidence:
        entry = {k: item[k] for k in ("id", "kind", "label", "scenario", "formatted", "document") if k in item}
        summary.append(entry)
    verdicts = [
        {
            "rule": v["rule"], "scenario": v.get("scenario"), "status": v["status"], "reasonCode": v["reasonCode"],
            "messageEn": v["messageEn"], "thresholdNature": (v.get("threshold") or {}).get("nature"),
            "evidence": v.get("evidence", []), "citations": v.get("citations", []),
        }
        for v in ctx.verdicts
    ]
    return {"items": summary, "verdicts": verdicts}



def _resample(series: pd.Series, frequency: str) -> tuple[pd.Series, str]:
    if frequency == "weekly":
        series = series.resample("W-FRI").last().dropna()
    elif frequency == "monthly":
        series = series.resample("ME").last().dropna()
    if len(series) > MAX_POINTS and frequency == "daily":
        return _resample(series, "weekly")
    if len(series) > MAX_POINTS and frequency == "weekly":
        return _resample(series, "monthly")
    return series.tail(MAX_POINTS), frequency


def get_prices(ctx: RequestContext, ticker: str, start: str, end: str, frequency: str = "daily") -> dict[str, Any]:
    if not ctx.store.has_ticker(ticker):
        return _unknown_ticker(ctx, ticker)
    start_ts, end_ts = _parse_date(start, "start"), _parse_date(end, "end")
    for value in (start_ts, end_ts):
        if isinstance(value, str):
            return _error(value)
    if end_ts < start_ts:
        return _error("end must be on or after start.")
    if end_ts > start_ts + pd.DateOffset(years=5):
        return _error("end must be at most 5 years after start.")
    if frequency not in ("daily", "weekly", "monthly"):
        return _error("frequency must be daily, weekly or monthly.")
    series = an.native_series(ctx.store, ticker)
    series = series[(series.index >= start_ts) & (series.index <= end_ts)]
    notes = ["Days without a quote (holidays, weekends) are not filled; each point is a real quote."]
    if series.empty:
        return {"ticker": ticker, "points": [], "notes": ["No quote in this period."]}
    sampled, used = _resample(series, frequency)
    if used != frequency:
        notes.append(f"Switched to {used} frequency to stay under {MAX_POINTS} points.")
    return {
        "ticker": ticker, "currency": an.listing_currency(ctx.store, ticker), "frequency": used, "adjusted": True,
        "points": [[d.date().isoformat(), round(float(v), 4)] for d, v in sampled.items()],
        "source": ctx.store.source_label(f"prices/{ticker}.parquet"), "notes": notes,
    }


def get_macro(ctx: RequestContext, series_id: str, start: str, end: str) -> dict[str, Any]:
    start_ts, end_ts = _parse_date(start, "start"), _parse_date(end, "end")
    for value in (start_ts, end_ts):
        if isinstance(value, str):
            return _error(value)
    if series_id == "USDCAD":
        series = ctx.store.fx_usdcad()
        unit, frequency, source = "CAD per USD", "business daily", ctx.store.source_label("fx/usdcad.parquet")
        notes = []
    else:
        macro = ctx.store.macro()
        rows = macro[macro["series_id"] == series_id]
        if rows.empty:
            known = sorted(macro["series_id"].unique())
            return _error(f"Unknown series_id '{series_id}'. Known: {', '.join(known)}, USDCAD.")
        series = rows.set_index("date")["value"].astype(float)
        unit, frequency = str(rows["unit"].iloc[0]), str(rows["frequency"].iloc[0])
        source = ctx.store.source_label("macro/macro.parquet")
        notes = []
        if "month" in frequency:
            notes.append("Monthly values are dated by reference month, not by publication date.")
    series = series[(series.index >= start_ts) & (series.index <= end_ts)]
    sampled, _ = _resample(series, "daily")
    return {
        "series_id": series_id, "unit": unit, "frequency": frequency,
        "points": [[d.date().isoformat(), round(float(v), 4)] for d, v in sampled.items()],
        "source": source, "notes": notes,
    }


def compute_metrics(ctx: RequestContext, tickers: list[str], start: str, end: str, metrics: list[str]) -> dict[str, Any]:
    if not isinstance(tickers, list) or not tickers or len(tickers) > MAX_METRIC_TICKERS:
        return _error(f"tickers must be a list of 1 to {MAX_METRIC_TICKERS} symbols.")
    for ticker in tickers:
        if not ctx.store.has_ticker(ticker):
            return _unknown_ticker(ctx, ticker)
    if not isinstance(metrics, list) or not metrics or any(m not in METRIC_NAMES for m in metrics):
        return _error(f"metrics must be a non-empty list among: {', '.join(METRIC_NAMES)}.")
    start_ts, end_ts = _parse_date(start, "start"), _parse_date(end, "end")
    for value in (start_ts, end_ts):
        if isinstance(value, str):
            return _error(value)
    out: dict[str, Any] = {}
    for ticker in tickers:
        values = an.asset_metrics(ctx.store, ticker, start_ts, end_ts)
        out[ticker] = {
            "total_return": round(values["totalReturn"], 2) if values and "total_return" in metrics else None,
            "volatility": round(values["volatility"], 2) if values and "volatility" in metrics else None,
            "max_drawdown": round(values["maxDrawdown"], 2) if values and "max_drawdown" in metrics else None,
        }
    result: dict[str, Any] = {
        "metrics": out, "period": f"{start}/{end}",
        "assumptions": [
            "adjclose; percentages in the listing currency; volatility annualized with sqrt(252) or sqrt(365) for crypto.",
        ],
        "source": ctx.store.source_label("prices"),
    }
    if "correlation" in metrics and len(tickers) > 1:
        aligned = an.aligned_cad_prices(ctx.store, tickers, start_ts, end_ts)
        result["correlation"] = an.correlation_matrix(aligned.frame)
        result["assumptions"].append("Correlation of daily CAD returns on common trading days.")
    return result


def market_stats(ctx: RequestContext, tickers: list[str], start: str, end: str) -> dict[str, Any]:
    if not isinstance(tickers, list) or not tickers or len(tickers) > MAX_METRIC_TICKERS:
        return _error(f"tickers must be a list of 1 to {MAX_METRIC_TICKERS} symbols.")
    for ticker in tickers:
        if not ctx.store.has_ticker(ticker):
            return _unknown_ticker(ctx, ticker)
    if not ctx.store.has_ticker(an.MARKET_INDEX):
        return _error(f"Market index {an.MARKET_INDEX} is missing from this dataset version.")
    start_ts, end_ts = _parse_date(start, "start"), _parse_date(end, "end")
    for value in (start_ts, end_ts):
        if isinstance(value, str):
            return _error(value)
    stats = an.market_stats(ctx.store, tickers, start_ts, end_ts)
    rounded = {
        ticker: {k: (None if v is None else round(v, 2 if k in ("annual_return", "std_dev") else 4))
                 if k != "observations" else v for k, v in values.items()}
        for ticker, values in stats.items()
    }
    return {
        "stats": rounded, "benchmark": an.MARKET_INDEX, "period": f"{start}/{end}",
        "assumptions": [
            "Daily returns on adjclose in the listing currency, no currency conversion (a CAD listing is compared with the USD index) and no price carried forward.",
            "annual_return = mean x periods, in %; std_dev = std x sqrt(periods), in %; variance = var x periods, as a decimal; periods = 252, or 365 for crypto.",
            "beta = cov(asset, market) / var(market) and market_correlation use only the days both quote (observations); fewer than "
            f"{an.MIN_MARKET_OBSERVATIONS} common days gives null.",
        ],
        "source": ctx.store.source_label("prices"),
    }


def optimize_portfolio(ctx: RequestContext, risk_profile: int, excluded_industries: list[str] | None = None,
                       preferred_industries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Construit un portefeuille moyenne-variance (aperçu, rien n'est enregistré). minWeight en % (ou null)."""
    if isinstance(risk_profile, bool) or not isinstance(risk_profile, int) or not 1 <= risk_profile <= 5:
        return _error("risk_profile must be an integer from 1 to 5.")
    preferred = []
    for item in preferred_industries or []:
        if not isinstance(item, dict) or not isinstance(item.get("industry"), str):
            return _error("preferred_industries must be a list of { industry, minWeight }.")
        minimum = item.get("minWeight")
        preferred.append({"industry": item["industry"], "minWeight": None if minimum is None else float(minimum) / 100.0})
    try:
        result = optimizer.optimize_portfolio(ctx.store, risk_profile, list(excluded_industries or []), preferred)
    except optimizer.OptimizerError as error:
        return _error(str(error))
    return {
        "holdings": [{"symbol": h.symbol, "name": h.name, "industry": h.industry, "weight": round(h.weight * 100, 2),
                      "beta": round(h.beta, 2), "expected_return": round(h.expected_return * 100, 2)} for h in result.holdings],
        "by_industry": {k: round(v * 100, 2) for k, v in result.by_industry.items()},
        "expected_return": round(result.expected_return * 100, 2), "volatility": round(result.volatility * 100, 2),
        "beta": round(result.beta, 2), "utility": round(result.utility, 4), "risk_aversion": result.aversion,
        "period": an.window_label(*result.window),
        "assumptions": [
            "Mean-variance model: mu from the CAPM against ^GSPC, Ledoit-Wolf covariance, daily adjclose returns in the listing currency.",
            "Expected returns are a model of the observed window, not a forecast.",
            f"Candidates: USD-listed equities with an industry in the dataset ({result.universe_size} stocks).",
        ],
        "source": ctx.store.source_label("prices"),
    }


def _current_weights(ctx: RequestContext) -> dict[str, float] | dict[str, Any]:
    portfolio = portfolios_repo.get_portfolio(ctx.user_id, ctx.portfolio_id)
    if portfolio is None:
        return {}
    values, _ = holding_values_cad(ctx.store, portfolio.get("holdings", []), ctx.store.last_date())
    return values


def portfolio_impact(ctx: RequestContext, mandate_version: int) -> dict[str, Any]:
    mandate_item = analyses_repo.get_mandate(ctx.session_id, ctx.user_id, int(mandate_version))
    if mandate_item is None:
        return _error(f"No confirmed mandate version {mandate_version} in this session.")
    ctx.portfolio_id = mandate_item["mandate"]["portfolioId"]
    portfolio = portfolios_repo.get_portfolio(ctx.user_id, ctx.portfolio_id)
    from backend.agents.engine.registry import EvidenceRegistry

    registry = EvidenceRegistry(ctx.user_language)
    result = run_engine(ctx.store, mandate_item, portfolio, registry)
    ctx.engine_result, ctx.mandate_item = result, mandate_item
    return {
        "scenarios": [{"index": s.index, "label": s.label, "metrics": dict(s.evidence)} for s in result.scenarios],
        "evidenceIds": [item["id"] for item in registry.items],
    }


def stress_test(ctx: RequestContext, period_id: str) -> dict[str, Any]:
    if period_id not in PERIOD_IDS:
        return _error(f"period_id must be one of: {', '.join(PERIOD_IDS)}.")
    period = derive_period(ctx.store, period_id)
    if not period.available:
        return {"period": period_id, "available": False, "notes": [period.note]}
    weights = _current_weights(ctx)
    aligned = an.aligned_cad_prices(ctx.store, list(weights), period.start, period.end, require_full_window=True)
    if not weights or aligned.missing:
        return {"period": period_id, "start": period.start.date().isoformat(), "end": period.end.date().isoformat(),
                "drawdown": None, "notes": ["Insufficient history for: " + ", ".join(aligned.missing or ["empty portfolio"])]}
    drawdown, _, _ = an.max_drawdown(an.portfolio_index(aligned.frame, weights))
    return {"period": period_id, "start": period.start.date().isoformat(), "end": period.end.date().isoformat(),
            "drawdown": round(drawdown, 2), "method": period.method, "evidenceIds": []}


def concentration(ctx: RequestContext) -> dict[str, Any]:
    weights = _current_weights(ctx)
    if not weights:
        return _error("The portfolio is empty.")
    result = concentration_of(ctx.store, weights)
    return {k: result[k] for k in ("topSingle", "bySector", "byCountry", "byCurrency", "techLookThrough", "caveats")} | {"evidenceIds": []}



def check_rules(ctx: RequestContext) -> dict[str, Any]:
    if ctx.engine_result is None or ctx.mandate_item is None:
        return _error("Run portfolio_impact first: no scenarios in this run.")
    return {"verdicts": run_rules(ctx.store, ctx.mandate_item, ctx.engine_result)}



_PASSAGES_LOCK = threading.Lock()


def search_regulation(ctx: RequestContext, query: str, subjects: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        return _error("query must be a non-empty English sentence.")
    if not subjects:
        return _error("subjects is required: pass the subjects of the rule being audited.")
    if not isinstance(subjects, list) or any(s not in kb.KNOWN_SUBJECTS for s in subjects):
        return _error(f"subjects must be a list among: {', '.join(kb.KNOWN_SUBJECTS)}.")
    passages = kb.retrieve(query.strip()[:500], ctx.jurisdictions, subjects, client=ctx.clients.get("kb"))
    shown = []
    with _PASSAGES_LOCK:
        for passage in passages:
            ref = f"P{len(ctx.passages) + 1}"
            ctx.passages[ref] = passage
            shown.append({
                "ref": ref, "document": passage["document"], "section": passage["section"],
                "jurisdiction": passage["jurisdiction"], "version": passage["version"], "score": passage["score"],
                "excerpt": kb.neutralize(passage["excerpt"]),
            })
    return {"passages": shown}


TOOL_FUNCTIONS = {
    "search_assets": search_assets,
    "get_prices": get_prices,
    "get_macro": get_macro,
    "compute_metrics": compute_metrics,
    "market_stats": market_stats,
    "optimize_portfolio": optimize_portfolio,
    "get_portfolio": get_portfolio,
    "get_profile": get_profile,
    "propose_mandate": propose_mandate,
    "read_evidence": read_evidence,
    "portfolio_impact": portfolio_impact,
    "stress_test": stress_test,
    "concentration": concentration,
    "check_rules": check_rules,
    "search_regulation": search_regulation,
}
