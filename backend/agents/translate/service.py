"""Appel à Amazon Translate et contrôles du texte traduit.

- Le texte est envoyé en HTML à TranslateDocument (TranslateText n'a pas de ContentType) : chaque emplacement
  {EV-nn}/{KB-nn} et chaque passage entre guillemets est enveloppé dans <span translate="no">. Au retour, les balises
  sont retirées et les entités HTML décodées.
- Les contrôles (emplacements, formulations interdites, chiffres ajoutés) sont ceux du vérificateur, appliqués
  juste après la traduction : un texte qui en échoue est signalé (correction LLM, sinon repli sur l'anglais).
- Aucune exception de ce module ne doit faire échouer un run : l'appelant replie sur l'anglais.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from typing import Any

from backend.agents.verifier.verifier import forbidden_phrases, handwritten_numbers, placeholders

SOURCE_LANGUAGE = "en"
TARGET_LANGUAGE = "fr-CA"
REGION = "us-east-1"

_PROTECTED = re.compile(r"\{(?:EV|KB)-\d{2,}\}|\"[^\"]*\"|“[^”]*”|«[^»]*»")
_TAG = re.compile(r"<[^>]*>")
_GLUED_BEFORE = re.compile(r"(?<=[A-Za-zÀ-ÿ0-9,;:])(\{(?:EV|KB)-\d{2,}\})")
_GLUED_AFTER = re.compile(r"(\{(?:EV|KB)-\d{2,}\})(?=[A-Za-zÀ-ÿ])")

_CLIENT = None


def _client():
    """Client boto3 `translate` (us-east-1), délais courts : le repli sur l'anglais coûte moins qu'une attente."""
    global _CLIENT
    if _CLIENT is None:
        import boto3
        from botocore.config import Config

        _CLIENT = boto3.client(
            "translate", region_name=REGION,
            config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 2, "mode": "standard"}),
        )
    return _CLIENT


def protect(text: str) -> str:
    """Texte en HTML : caractères spéciaux échappés, emplacements et citations en translate="no"."""
    escaped = html.escape(text, quote=False)
    return "<p>" + _PROTECTED.sub(lambda m: f'<span translate="no">{m.group(0)}</span>', escaped) + "</p>"


def unprotect(translated_html: str) -> str:
    """Retire les balises (les nôtres et celles que Translate a pu ajouter) puis décode les entités HTML."""
    text = html.unescape(_TAG.sub("", translated_html))
    return _GLUED_AFTER.sub(r"\1 ", _GLUED_BEFORE.sub(r" \1", text)).strip()


def _content(blob: Any) -> str:
    if hasattr(blob, "read"):
        blob = blob.read()
    return blob.decode("utf-8") if isinstance(blob, (bytes, bytearray)) else str(blob)


def error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return str((response.get("Error") or {}).get("Code") or type(exc).__name__)
    return type(exc).__name__


def translate(client: Any, text: str, terminology: str | None) -> tuple[str, bool]:
    """Traduit `text` en fr-CA ; renvoie (texte, terminologie appliquée). Lève l'erreur du client si elle persiste.

    Terminologie absente du compte (ResourceNotFoundException) : un deuxième essai sans elle."""
    def call(names: list[str]) -> str:
        params: dict[str, Any] = {
            "Document": {"Content": protect(text).encode("utf-8"), "ContentType": "text/html"},
            "SourceLanguageCode": SOURCE_LANGUAGE, "TargetLanguageCode": TARGET_LANGUAGE,
        }
        if names:
            params["TerminologyNames"] = names
        return unprotect(_content(client.translate_document(**params)["TranslatedDocument"]["Content"]))

    if terminology:
        try:
            return call([terminology]), True
        except Exception as exc:  # noqa: BLE001 - seul ResourceNotFoundException se rattrape
            if error_code(exc) != "ResourceNotFoundException":
                raise
    return call([]), False



def _digits(text: str) -> Counter[str]:
    """Les nombres « écrits à la main » d'un texte, réduits à leurs chiffres (15,000 $ et 15 000 $ s'égalent)."""
    return Counter(re.sub(r"\D", "", n) for n in handwritten_numbers(text, set()))


def problem(english: str, french: str) -> tuple[str, str] | None:
    """Premier défaut du texte traduit : (code, détail) ou None. Contrôles du vérificateur appliqués à la traduction."""
    if not french.strip():
        return "empty", "The translation is empty."
    if Counter(placeholders(english)) != Counter(placeholders(french)):
        return "placeholders", f"Expected placeholders {sorted(placeholders(english))}, found {sorted(placeholders(french))}."
    new_phrases = forbidden_phrases(french) if not forbidden_phrases(english) else []
    if new_phrases:
        return "forbidden_phrase", f"Forbidden wording: {new_phrases}."
    added = _digits(french) - _digits(english)
    if added:
        return "added_number", f"Numbers not in the source: {sorted(added)}."
    return None
