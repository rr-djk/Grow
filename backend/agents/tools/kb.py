"""Recherche dans la Knowledge Base réglementaire (Bedrock KB Retrieve), filtrée par juridiction.

Le filtre de métadonnées vient du contexte : juridiction ∈ {CA, province du
mandat}, et éventuellement sujets. Les passages renvoyés sont des données non
fiables : le texte est tronqué et neutralisé (aucune balise d'encadrement ne
peut s'y glisser) avant d'être montré à un modèle.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from backend.agents import telemetry
from backend.common import config

KNOWN_SUBJECTS = (
    "kyc", "profil_risque", "convenance", "instruction", "reglement", "crypto", "esg", "fonds", "oeo",
    "aide_decision", "recommandation", "titres_proteges", "relation_client", "cadrage", "questions_investisseur",
)

DOCUMENT_TITLES = {
    "CA_21-329": "CSA/IIROC Staff Notice 21-329 (crypto-asset trading platforms)",
    "CA_21-332": "CSA Staff Notice 21-332 (crypto-asset trading platforms, pre-registration undertakings)",
    "CA_31-103CP": "Companion Policy 31-103CP (registration requirements)",
    "CA_31-103": "National Instrument 31-103 (registration requirements, exemptions and ongoing obligations)",
    "CA_31-368": "Joint CSA/CIRO Staff Notice 31-368 (client focused reforms)",
    "CA_81-334": "CSA Staff Notice 81-334 (ESG-related investment fund disclosure)",
    "CA_CIRO_GN-3200-26-001": "CIRO Guidance GN-3200-26-001 (order-execution-only services)",
    "CA_CIRO_bulletin-26-0059": "CIRO Bulletin 26-0059 (order-execution-only guidance)",
    "ON_FSRA_rule-2020-001": "FSRA Rule 2020-001 (financial professionals title protection)",
    "QC_AMF_financial-planner-title": "AMF: the financial planner title in Québec",
    "QC_NBDB_relationship-disclosure-information": "National Bank Direct Brokerage: relationship disclosure information",
    "QC_NBDB_tips-better-investment-decisions": "National Bank Direct Brokerage: questions before investing",
    "SK_FCAA_FPFA-proposed-regulations-notice": "FCAA: proposed Financial Planners and Financial Advisors regulations",
}

MAX_PASSAGES = 5
MAX_EXCERPT_CHARS = 2400

CITABLE_REGULATORS = ("CSA", "CSA-IIROC", "CSA-CIRO", "CSA-AMF", "CIRO", "FSRA", "AMF", "FCAA")


_ABBREVIATIONS = {
    "s", "ss", "sec", "secs", "art", "arts", "no", "nos", "para", "paras", "subs", "ch", "cl", "pt", "pp", "p",
    "c", "cf", "vs", "v", "inc", "ltd", "corp", "co", "dr", "mr", "mrs", "ms", "st", "fig", "ex", "eg", "ie", "etc",
    "al", "approx", "ref", "reg", "regs", "sch", "div", "vol", "ed", "eds", "rev", "max", "min",
}
_SENTENCE_END = re.compile(r"""([.!?])(["')\]”’]*)(?=\s+["'(\[“‘]*[A-Z0-9]|\s*$)""")


def _is_sentence_end(head: str, match: re.Match[str]) -> bool:
    """Vrai si le point à cette position termine une phrase (et non « s. », « art. », « No. »…)."""
    if match.group(1) != ".":
        return True
    word = re.search(r"([A-Za-z]+)$", head[: match.start()])
    if word is None:
        return True
    if word.group(1).lower() in _ABBREVIATIONS:
        return False
    if len(word.group(1)) == 1 and word.group(1).isupper():
        return False
    return True


def excerpt_of(text: str, limit: int = MAX_EXCERPT_CHARS) -> str:
    """Texte brut de la base, coupé à la dernière vraie fin de phrase avant la limite (jamais résumé ni traduit).

    Les « ; » et « : » ne terminent pas une phrase, et un point après « s. », « art. » ou « No. » non plus :
    couper là donnerait un extrait qui s'arrête au milieu d'un article.
    """
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    head = flat[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(head) if _is_sentence_end(head, m)]
    if ends and ends[-1] >= limit * 0.4:
        return head[: ends[-1]].rstrip()
    return head.rsplit(" ", 1)[0].rstrip() + " …"


def document_title(uri: str | None) -> str:
    name = PurePosixPath(uri or "").name
    for prefix in sorted(DOCUMENT_TITLES, key=len, reverse=True):
        if name.startswith(prefix):
            return DOCUMENT_TITLES[prefix]
    return name or "Unknown document"


def neutralize(text: str) -> str:
    """Retire les balises qui pourraient fermer l'encadrement des données."""
    return (
        text.replace("<", "‹").replace(">", "›").replace("\u0000", "").strip()
    )


def build_filter(jurisdictions: list[str], subjects: list[str] | None, strict_citable: bool | None = None) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = [{"in": {"key": "juridiction", "value": jurisdictions}}]
    if strict_citable is None:
        strict_citable = bool(config.kb_corpus_version())
    if strict_citable:
        clauses.append({"equals": {"key": "citable", "value": True}})
    valid = [s for s in subjects or [] if s in KNOWN_SUBJECTS]
    if len(valid) == 1:
        clauses.append({"listContains": {"key": "sujets", "value": valid[0]}})
    elif len(valid) > 1:
        clauses.append({"orAll": [{"listContains": {"key": "sujets", "value": s}} for s in valid]})
    return clauses[0] if len(clauses) == 1 else {"andAll": clauses}


_CLIENT = None


def _client():
    global _CLIENT
    if _CLIENT is None:
        import boto3

        _CLIENT = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
    return _CLIENT


def is_citable(metadata: dict[str, Any]) -> bool:
    """Revérifie `citable` dans le code, comme la juridiction (défense en profondeur).

    Corpus par section : `citable` doit valoir vrai. Ancien corpus (clé absente, KB_CORPUS_VERSION non posée) :
    seuls les régulateurs de la liste sont citables. Dès que le nouveau corpus est ingéré, une clé absente = non citable."""
    value = metadata.get("citable")
    if isinstance(value, str):
        value = value.strip().lower() == "true" if value.strip().lower() in ("true", "false") else None
    if value is True:
        return True
    if value is False:
        return False
    if config.kb_corpus_version():
        return False
    return metadata.get("regulateur") in CITABLE_REGULATORS


def section_label(metadata: dict[str, Any], page: Any = None, document: str | None = None) -> str | None:
    """« s. 2.1.1 Decision-making supports » si la section existe, sinon « page N » (plage de pages, ou page Bedrock)."""
    section = metadata.get("section")
    if section:
        title = metadata.get("section_titre")
        return f"s. {section} {title}".strip() if title else f"s. {section}"
    pages = metadata.get("pages")
    title = metadata.get("section_titre")
    if title and title != document:
        return f"{title} (page {pages})" if pages else title
    if pages:
        return f"page {pages}"
    return f"page {int(page)}" if isinstance(page, (int, float)) else None


def retrieve(query: str, jurisdictions: list[str], subjects: list[str] | None = None, client=None) -> list[dict[str, Any]]:
    """Appelle Retrieve et renvoie au plus MAX_PASSAGES passages normalisés."""
    kb = config.kb_id()
    if not kb:
        raise RuntimeError("KB_ID is not configured")
    with telemetry.trace_span(
        "kb.retrieve",
        observation_type="retriever",
        input_data={"query": query, "jurisdictions": jurisdictions, "subjects": subjects},
    ) as span:
        response = (client or _client()).retrieve(
            knowledgeBaseId=kb,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": MAX_PASSAGES,
                    "filter": build_filter(jurisdictions, subjects),
                }
            },
        )
        passages = []
        for result in response.get("retrievalResults", []):
            metadata = result.get("metadata") or {}
            if metadata.get("juridiction") not in jurisdictions:
                continue
            if not is_citable(metadata):
                continue
            if len(passages) >= MAX_PASSAGES:
                break
            uri = (result.get("location") or {}).get("s3Location", {}).get("uri") or metadata.get("x-amz-bedrock-kb-source-uri")
            page = metadata.get("x-amz-bedrock-kb-document-page-number")
            excerpt = excerpt_of((result.get("content") or {}).get("text", ""))
            passages.append({
                "document": document_title(uri),
                "section": section_label(metadata, page, document_title(uri)),
                "sectionTitle": metadata.get("section_titre"),
                "documentType": metadata.get("type_document"),
                "regulator": metadata.get("regulateur"),
                "status": metadata.get("statut"),
                "language": metadata.get("langue"),
                "excerpt": excerpt,
                "jurisdiction": metadata.get("juridiction"),
                "version": metadata.get("date_version"),
                "url": metadata.get("source_url"),
                "file": PurePosixPath(uri or "").name or None,
                "score": round(float(result.get("score", 0.0)), 3),
            })
        telemetry.set_span_output(
            span,
            [
                {
                    "document": p["document"],
                    "section": p["section"],
                    "jurisdiction": p["jurisdiction"],
                    "score": p["score"],
                }
                for p in passages
            ],
        )
        return passages
