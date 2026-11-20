"""Table des droits agent/module → outils (contrat : allowed_tools, uses_tools), vérifiée au chargement.

Garanties (retour d'expérience Strands §3.2) : un outil enregistré deux fois,
un droit sur un outil inconnu, ou un composant sans droits déclarés lèvent une
erreur au démarrage à froid, pas chez le premier utilisateur. Tout appel
d'outil passe par Toolbox.call : droit vérifié, durée mesurée, ligne tool.call
émise et ajoutée au journal de l'exécution (source de explanation).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from backend.agents.observability import log_tool_call
from backend.agents.tools.catalog import TOOL_FUNCTIONS
from backend.agents.tools.context import RequestContext

GRANTS: dict[str, list[str]] = {
    "agent-orchestrator": ["get_portfolio", "get_profile", "search_assets", "propose_mandate", "read_evidence"],
    "agent-auditor": ["search_regulation"],
    "agent-writer": ["read_evidence"],
    "module-engine": ["get_prices", "get_macro", "compute_metrics", "market_stats", "optimize_portfolio", "get_portfolio", "portfolio_impact", "stress_test", "concentration"],
    "module-rules": ["check_rules"],
    "module-verifier": [],
}

MAX_TOOL_CALLS = {"agent-auditor": 16, "agent-writer": 4, "agent-orchestrator": 8}

TOOL_SOURCES = {
    "search_assets": "storage-dataset: universe.parquet",
    "get_prices": "storage-dataset: prices",
    "get_macro": "storage-dataset: macro, fx",
    "compute_metrics": "storage-dataset: prices, fx",
    "market_stats": "storage-dataset: prices",
    "optimize_portfolio": "storage-dataset: prices, universe.parquet",
    "get_portfolio": "db-portfolios",
    "get_profile": "db-users",
    "propose_mandate": "storage-dataset: universe.parquet",
    "read_evidence": "db-analyses",
    "portfolio_impact": "db-portfolios, db-analyses, storage-dataset",
    "stress_test": "storage-dataset",
    "concentration": "storage-dataset: etf_enriched.json, universe.parquet",
    "check_rules": "db-analyses",
    "search_regulation": "srv-bedrock-kb",
}

_REDACTED_PARAMS = {"draft"}


class ToolboxError(RuntimeError):
    """Erreur de câblage : détectée au démarrage."""


class Toolbox:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., dict[str, Any]]] = {}
        self._grants: dict[str, list[str]] = {}

    def register(self, tools: dict[str, Callable[..., dict[str, Any]]]) -> "Toolbox":
        for name, fn in tools.items():
            if name in self._tools:
                raise ToolboxError(f"Tool registered twice: {name}")
            self._tools[name] = fn
        return self

    def grant(self, owner: str, names: list[str]) -> "Toolbox":
        unknown = [n for n in names if n not in self._tools]
        if unknown:
            raise ToolboxError(f"Unknown tool(s) granted to {owner}: {unknown}")
        self._grants[owner] = list(names)
        return self

    def granted(self, owner: str) -> list[str]:
        if owner not in self._grants:
            raise ToolboxError(f"No tool grant declared for {owner}")
        return list(self._grants[owner])

    def tool_names(self) -> list[str]:
        return list(self._tools)

    def call(self, owner: str, name: str, ctx: RequestContext, **params: Any) -> dict[str, Any]:
        if name not in self.granted(owner):
            raise ToolboxError(f"{owner} is not allowed to call {name}")
        started = time.perf_counter()
        status = "ok"
        try:
            result = self._tools[name](ctx, **params)
            if isinstance(result, dict) and "error" in result:
                status = "error"
            elif isinstance(result, dict) and (result.get("items") == [] or result.get("passages") == []):
                status = "empty"
            return result
        except Exception:
            status = "error"
            raise
        finally:
            duration = int((time.perf_counter() - started) * 1000)
            shown = {k: ("<redacted>" if k in _REDACTED_PARAMS else v) for k, v in params.items()}
            record = {
                "agentId": owner, "tool": name, "params": shown, "status": status,
                "durationMs": duration, "source": TOOL_SOURCES.get(name),
            }
            ctx.tool_calls.append(record)
            log_tool_call(record, session_id=ctx.session_id, message_id=ctx.message_id or ctx.run_id)


def build_toolbox() -> Toolbox:
    box = Toolbox().register(TOOL_FUNCTIONS)
    for owner, names in GRANTS.items():
        box.grant(owner, names)
    return box


TOOLBOX = build_toolbox()
