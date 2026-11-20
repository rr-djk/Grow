"""Citations que le code attache lui-même à R5 et R9 (lot E2), sans passer par Retrieve.

R5 (un outil d'aide à la décision ne recommande pas) et R9 (titres protégés de la province) portent sur l'outil, pas sur
le scénario : leur texte source (GN-3200-26-001 s. 2.1.1 et 3.3 ; AMF, FSRA, FCAA) ne dépend pas de l'idée testée et ne
se trouve pas par une recherche sémantique (la section 2.1.1 sortait 9e). Le code les lit dans `fixed_citations.json`,
produit par build_kb_corpus.py à partir du corpus ingéré, et les affiche à côté des mentions, jamais sous une règle
« non déclenchée ».

Invariant : une citation vient de Retrieve, ou d'une section fixée par le code dans le corpus de même `corpus_version` que
celui ingéré (KB_CORPUS_VERSION). Versions différentes ou variable absente : aucune citation fixée.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.agents.engine.registry import EvidenceRegistry
from backend.common import config

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "fixed_citations.json"


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pinned_for(rule: str, province: str | None) -> list[dict[str, Any]]:
    data = _data()
    version = config.kb_corpus_version()
    if not data or not version or data.get("corpus_version") != version:
        return []
    items = data.get("R5", []) if rule == "R5" else (data.get("R9", {}).get(province or "", []) if rule == "R9" else [])
    return [c for c in items if c.get("jurisdiction") in ("CA", province)]


def register(registry: EvidenceRegistry, province: str | None) -> dict[str, list[str]]:
    """Inscrit les citations fixées au registre du run ; renvoie { règle: [KB-nn] }."""
    version = config.kb_corpus_version()
    registered: dict[str, list[str]] = {}
    for rule in ("R5", "R9"):
        ids = [
            registry.add_regulation(
                document=c["document"], section=c.get("section"), excerpt=c["excerpt"], jurisdiction=c["jurisdiction"],
                url=c.get("url"), as_of=c.get("version"), source=f"Knowledge Base corpus {version}: {c.get('file')} (section fixée par le code)",
                document_type=c.get("documentType"), regulator=c.get("regulator"), status=c.get("status"),
                section_title=c.get("sectionTitle"), language=c.get("language"),
            )
            for c in pinned_for(rule, province)
        ]
        if ids:
            registered[rule] = ids
    return registered
