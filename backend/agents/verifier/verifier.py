"""module-verifier : contrôle non bloquant de chaque phrase du texte affiché.

Contrôles (contrat module-verifier, SOLUTION.md 7.5) :
1. chaque {EV-nn}/{KB-nn} existe dans le registre du run ;
2. aucun nombre écrit à la main (%, $, points de base, ratio, décimal, entier
   significatif) hors constantes du mandat, années, numéros de règle et de document ;
3. aucune formule de recommandation, de promesse ou de jugement de conformité/convenance (motifs EN et FR) ;
4. mêmes emplacements dans textEn et text (la traduction n'en perd ni n'en ajoute).
Une phrase fautive est retirée et listée dans hiddenSentences ; jamais de
nouvelle tentative. Les motifs sont des expressions fixes écrites ici, jamais
construites depuis une sortie de modèle (pas de ReDoS).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

PLACEHOLDER_RE = re.compile(r"\{((?:EV|KB)-\d{2,})\}")
SECTION_KEYS = ("data_used", "why", "limits", "what_would_change")

DOCUMENT_REF_RE = re.compile(
    r"\b(?:NI|CSA|CIRO|IIROC|Notice|Avis|Regulation|Règlement|Policy|Instruction|GN|Rule|Règle|R)?[\s-]?"
    r"(?:\d{2}-\d{3}(?:CP)?|GN-\d{4}-\d{2}-\d{3}|\d{4}-\d{3}|R(?:10|[1-9]))\b"
)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ{«\"(])")

NUMBER_RE = re.compile(
    r"(?P<num>[-+−]?\d[\d\s  ]*(?:[.,]\d+)?)"
    r"\s?(?P<unit>%|\$|\$\s?US|bps?|pb|points? de base|basis points?|x\b|×|fois)?",
    re.IGNORECASE,
)

METHOD_RESAMPLING_LEVEL = 90.0

FORBIDDEN_PATTERNS = [
    r"\byou should (?:buy|sell|invest|hold|add)\b", r"\bwe recommend\b", r"\bi recommend\b", r"\brecommended\b",
    r"\bguarantee(?:d|s)?\b", r"\brisk[- ]free\b(?!\s+(?:rate|asset|benchmark))", r"\bsure (?:bet|thing|win)\b", r"\bwill (?:certainly|definitely) (?:rise|grow|gain)\b",
    r"\bbuy now\b", r"\bmust (?:buy|sell)\b", r"\bbest investment\b",
    r"\bvous devriez (?:acheter|vendre|investir|conserver|ajouter)\b", r"\bje (?:vous )?recommande\b",
    r"\bnous (?:vous )?recommandons\b", r"\brecommand[ée]e?s?\b", r"\bgaranti(?:e|es|s)?\b", r"(?<!taux )\bsans risque\b",
    r"\bachetez\b", r"\bvendez\b", r"\bmeilleur placement\b", r"\bva (?:certainement|forcément) (?:monter|augmenter)\b",
    r"\bconseiller financier\b", r"\bplanificateur financier\b", r"\bfinancial (?:advisor|adviser|planner)\b",
]

JUDGEMENT_PATTERNS = [
    r"\bnon-?compliant\b", r"\bcompliant\b", r"\bcomplies with\b", r"\bcomply with\b",
    r"\b(?:is|are|was|were) (?:not |un)?suitable\b", r"\bunsuitable\b", r"\bsuits? you\b",
    r"compatible with (?:your|the retained) (?:risk )?profile",
    r"\b(?:passes|passed)\b",
    r"\bfits? (?:the |your |this )?(?:retained |risk |stated )*(?:profile|mandate)\b",
    r"\b(?:consistent|in line) with (?:the |your )?(?:retained |risk )*profile\b",
    r"\b(?:in line|consistent) with \{(?:KB|EV)-\d{2,}\}",
    r"\bconformes?\b", r"\bvous convient\b", r"\bconvien(?:t|nent) (?:à|a) (?:ce|cette|votre|ton|ta)\b",
    r"adapté(?:e|s|es)? à votre profil", r"compatible avec votre profil",
    r"\bcorrespond(?:ent)? au profil\b", r"\b(?:cohérent|cohérente|cohérents)s? avec le profil\b",
    r"\bconformément à \{(?:KB|EV)-\d{2,}\}", r"\ben phase avec \{(?:KB|EV)-\d{2,}\}",
]

DISCLAIMER_PATTERN = (
    r"\b(?:does|do|will) not (?:assess|judge|evaluate|determine|say|decide|take a position)\b|\btakes? no position\b"
    r"|\bne (?:se )?prononce(?:nt)? pas\b|\bn'(?:évalue|apprécie|juge|établit) pas\b|\bne (?:juge|détermine|évalue) pas\b"
)

_FORBIDDEN = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]
_JUDGEMENT = [re.compile(p, re.IGNORECASE) for p in JUDGEMENT_PATTERNS]
_DISCLAIMER = re.compile(DISCLAIMER_PATTERN, re.IGNORECASE)


NON_SYMBOLS = frozenset({"ON", "QC", "BC", "AB", "SK", "MB", "NB", "NS", "PE", "NL", "YT", "NT", "NU"})
RULE_ID_RE = re.compile(r"R\d+")


def symbol_pattern(universe: set[str]) -> re.Pattern[str] | None:
    symbols = sorted((t for t in universe if len(t) >= 2 and t not in NON_SYMBOLS and not RULE_ID_RE.fullmatch(t)), key=len, reverse=True)
    if not symbols:
        return None
    return re.compile(r"(?<![A-Za-z0-9.\-])(?:" + "|".join(re.escape(t) for t in symbols) + r")(?![A-Za-z0-9\-])")


def unlisted_symbols(sentence: str, pattern: re.Pattern[str] | None, allowed: set[str]) -> list[str]:
    if pattern is None:
        return []
    return sorted({m.group(0) for m in pattern.finditer(PLACEHOLDER_RE.sub(" ", sentence))} - allowed)


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER_RE.findall(text or "")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_RE.split((text or "").strip())]
    return [p for p in parts if p]


def _normalize_number(raw: str) -> float | None:
    cleaned = raw.replace(" ", "").replace(" ", "").replace(" ", "").replace("−", "-")
    if re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+", cleaned):
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def mandate_constants(mandate: dict[str, Any]) -> set[float]:
    """Constantes saisies par l'utilisateur et répétables sans emplacement (« 3 ans », « 15 000 $ »)."""
    values: set[float] = set()
    for key in ("horizonYears", "maxAcceptableLossPct", "riskTolerance", "riskCapacity"):
        if isinstance(mandate.get(key), (int, float)):
            values.add(float(mandate[key]))
    for op in mandate.get("operations") or []:
        for key in ("amount", "weight"):
            if isinstance(op.get(key), (int, float)):
                values.add(float(op[key]))
    for item in (mandate.get("preferences") or {}).get("preferredIndustries") or []:
        if isinstance(item.get("minWeight"), (int, float)):
            values.add(float(item["minWeight"]))
    values.add(METHOD_RESAMPLING_LEVEL)
    return values


def handwritten_numbers(sentence: str, constants: set[float]) -> list[str]:
    """Nombres non autorisés d'une phrase (après retrait des emplacements et références)."""
    text = PLACEHOLDER_RE.sub(" ", sentence)
    text = DOCUMENT_REF_RE.sub(" ", text)
    text = YEAR_RE.sub(" ", text)
    found = []
    for match in NUMBER_RE.finditer(text):
        raw = match.group("num").strip()
        if not any(ch.isdigit() for ch in raw):
            continue
        value = _normalize_number(raw)
        unit = match.group("unit")
        if value is None:
            found.append(match.group(0).strip())
            continue
        if value in constants or abs(value) in constants:
            continue
        is_decimal = bool(re.search(r"\d[.,]\d", raw))
        if unit or is_decimal or abs(value) > 10:
            found.append(match.group(0).strip())
    return found


def forbidden_phrases(sentence: str) -> list[str]:
    found = [m.group(0) for pattern in _FORBIDDEN for m in [pattern.search(sentence)] if m]
    if not _DISCLAIMER.search(sentence):
        found += [m.group(0) for pattern in _JUDGEMENT for m in [pattern.search(sentence)] if m]
    return found


def verify_narrative(
    sections: list[dict[str, Any]], evidence_ids: set[str], mandate: dict[str, Any],
    universe: set[str] | None = None, held: set[str] | None = None, built: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    """Contrôle les sections { key, textEn, text } ; renvoie (sections nettoyées, phrases masquées, rapport).

    `universe` : symboles du jeu de données ; avec lui, toute phrase qui nomme un symbole que l'utilisateur n'a ni écrit
    (opérations, subjectTicker) ni détenu (`held`) est masquée (le FNB d'approximation de la comparaison, notamment). `built` : symboles du portefeuille construit (mode build)."""
    constants = mandate_constants(mandate)
    pattern = symbol_pattern(universe or set())
    allowed = set(held or set()) | {op["ticker"] for op in mandate.get("operations") or []}
    allowed |= set(built or set())
    allowed |= {mandate["subjectTicker"]} if mandate.get("subjectTicker") else set()
    hidden: list[dict[str, str]] = []
    cleaned: list[dict[str, Any]] = []
    total = resolved = numbers = forbidden = 0
    placeholders_match = True

    for section in sections:
        text_en = section.get("textEn") or ""
        text = section.get("text") if section.get("text") is not None else text_en
        if Counter(placeholders(text_en)) != Counter(placeholders(text)):
            placeholders_match = False
        kept: list[str] = []
        for sentence in split_sentences(text):
            ids = placeholders(sentence)
            total += len(ids)
            unknown = [i for i in ids if i not in evidence_ids]
            resolved += len(ids) - len(unknown)
            bad_numbers = handwritten_numbers(sentence, constants)
            bad_phrases = forbidden_phrases(sentence) + unlisted_symbols(sentence, pattern, allowed)
            numbers += len(bad_numbers)
            forbidden += len(bad_phrases)
            if unknown:
                hidden.append({"section": section["key"], "reason": "unknown_placeholder"})
            elif bad_numbers:
                hidden.append({"section": section["key"], "reason": "handwritten_number"})
            elif bad_phrases:
                hidden.append({"section": section["key"], "reason": "forbidden_phrase"})
            else:
                kept.append(sentence)
        cleaned.append({**section, "text": " ".join(kept)})

    report = {
        "placeholdersResolved": resolved,
        "placeholdersTotal": total,
        "handwrittenNumbers": numbers,
        "forbiddenPhrases": forbidden,
        "placeholdersMatch": placeholders_match,
    }
    return cleaned, hidden, report
