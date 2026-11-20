"""Traduction des textes d'un run : chaque texte part dès qu'il existe, en parallèle, sans attendre les autres.

- Sections du rédacteur : `follow` se branche sur le futur de la section et traduit dès qu'elle est écrite.
- Motifs reformulés par l'auditeur : `submit_text` dès la fin de l'auditeur, pendant les sections tardives.
- Motifs par défaut et mentions de province : table fixe française (rules/fr.py), aucun appel.
- `finalize` attend tout, puis envoie en UN appel LLM (sans outil) les seuls textes signalés par les contrôles.
  Un texte qui échoue encore, ou une erreur de Translate, donne le texte anglais : un run n'échoue jamais ici.
Seul `userLanguage = fr` est traduit ; `en` ne fait aucun appel ; toute autre langue affiche l'anglais.
"""

from __future__ import annotations

import contextvars
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from backend.agents import telemetry
from backend.agents.llm.orchestrator import agent as orchestrator
from backend.agents.observability import log_event
from backend.agents.rules import fr as fixed_fr
from backend.agents.tools.context import RequestContext
from backend.agents.translate import service
from backend.common import config

WORKERS = 8

_PROBLEM_HINTS = {
    "empty": "The translation is empty: translate the source.",
    "placeholders": "The placeholders differ from the source (lost, added or changed): restore them exactly.",
    "forbidden_phrase": "The translation contains wording of advice, recommendation, guarantee or compliance/suitability judgement that the source does not have: rephrase neutrally.",
    "added_number": "The translation contains a number that the source does not have: remove it or restore the source's.",
}


@dataclass
class Item:
    """Un texte traduit. `status` : table (phrase fixe), ok, fixed (corrigé par le LLM), fallback (anglais affiché),
    flagged (en attente de correction, état transitoire)."""

    english: str
    text: str
    status: str
    reason: str | None = None
    candidate: str | None = None
    detail: str | None = None

    @property
    def translated(self) -> bool:
        return self.status in ("table", "ok", "fixed")


class RunTranslator:
    def __init__(self, ctx: RequestContext, language: str):
        self.ctx = ctx
        self.language = language
        self.active = language == "fr"
        if language not in ("en", "fr"):
            log_event("translate.unsupported_language", language=language, sessionId=ctx.session_id)
        self._pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="translate") if self.active else None
        self._items: dict[str, Future] = {}
        self._resolved: dict[str, Item] = {}
        self._terminology = config.translate_terminology()

    def __enter__(self) -> "RunTranslator":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)

    def follow(self, label: str, source: Future) -> None:
        """Traduit `source.result()` (le texte anglais d'une section) dès que ce futur se termine."""
        if not self.active:
            return
        key, out, context = f"section:{label}", Future(), contextvars.copy_context()
        self._items[key] = out

        def on_done(done: Future) -> None:
            if done.cancelled() or done.exception() is not None:
                out.set_exception(done.exception() or RuntimeError("cancelled"))
                return
            try:
                self._pool.submit(context.run, self._resolve, key, done.result(), out)
            except Exception as exc:  # noqa: BLE001 - jamais d'exception perdue dans un callback
                out.set_exception(exc)

        source.add_done_callback(on_done)

    def follow_sections(self, calls: Any) -> None:
        """`calls` : un `writer.SectionCalls` (futures par clé de section)."""
        for key, future in calls.futures.items():
            self.follow(key, future)

    def submit_text(self, english: str, kind: str, label: str) -> None:
        """Lance la traduction d'un motif (kind = message) ou d'une mention (kind = notice), sauf s'il est dans la table fixe."""
        if not self.active:
            return
        key = f"text:{english}"
        if key in self._items:
            return
        out: Future = Future()
        self._items[key] = out
        fixed = (fixed_fr.fixed_message if kind == "message" else fixed_fr.fixed_notice)(english)
        if fixed is not None:
            out.set_result(Item(english, fixed, "table"))
            return
        self._pool.submit(contextvars.copy_context().run, self._resolve, label, english, out)

    def _resolve(self, label: str, english: str, out: Future) -> None:
        try:
            out.set_result(self._translate_one(label, english))
        except BaseException as exc:  # noqa: BLE001 - un futur jamais résolu bloquerait finalize
            out.set_exception(exc)

    def _translate_one(self, label: str, english: str) -> Item:
        started = time.perf_counter()
        with telemetry.trace_span(
            "translate.text", observation_type="tool", session_id=self.ctx.session_id, user_id=self.ctx.user_id,
            input_data={"key": label, "chars": len(english)},
        ) as span:
            item: Item
            terminology_used = False
            try:
                client = self.ctx.clients.get("translate") or service._client()
                french, terminology_used = service.translate(client, english, self._terminology)
                found = service.problem(english, french)
                if found is None:
                    item = Item(english, french, "ok")
                else:
                    item = Item(english, english, "flagged", reason=found[0], candidate=french, detail=found[1])
            except Exception as exc:  # noqa: BLE001 - fail-open : l'anglais s'affiche, le run continue
                code = service.error_code(exc)
                log_event("translate.error", key=label, error=code, sessionId=self.ctx.session_id)
                item = Item(english, english, "fallback", reason=f"error:{code}")
            telemetry.set_span_output(span, {
                "key": label, "chars": len(english),
                "result": item.status if item.status != "flagged" else f"flagged:{item.reason}",
                "durationMs": round((time.perf_counter() - started) * 1000), "terminology": terminology_used,
            })
            return item

    def finalize(self) -> None:
        """Attend toutes les traductions, puis corrige en un seul appel LLM les textes signalés."""
        resolved: dict[str, Item] = {}
        for key, future in self._items.items():
            try:
                resolved[key] = future.result()
            except Exception:  # noqa: BLE001 - texte absent : l'anglais s'affichera
                continue
        self._resolved = resolved
        flagged = [item for item in resolved.values() if item.status == "flagged"]
        if flagged:
            self._fix(flagged)

    def _fix(self, flagged: list[Item]) -> None:
        payload = [
            {"item": i, "source": it.english, "translation": it.candidate,
             "problem": f"{_PROBLEM_HINTS[it.reason or 'empty']} {it.detail}"}
            for i, it in enumerate(flagged)
        ]
        started = time.perf_counter()
        fixed_count = 0
        with telemetry.trace_span(
            "translate.fix", observation_type="tool", session_id=self.ctx.session_id, user_id=self.ctx.user_id,
            input_data={"flagged": len(flagged), "reasons": [it.reason for it in flagged]},
        ) as span:
            try:
                fixes = orchestrator.fix_translations(self.ctx, payload)
            except Exception as exc:  # noqa: BLE001 - AgentFailure ou erreur Bedrock : l'anglais remplace les textes signalés
                log_event("translate.fix_failed", reason=getattr(exc, "reason", type(exc).__name__), sessionId=self.ctx.session_id)
                fixes = []
            for fix in fixes:
                index = fix.get("item")
                if not isinstance(index, int) or not 0 <= index < len(flagged) or not fix.get("find"):
                    continue
                item = flagged[index]
                if fix["find"] in (item.candidate or ""):
                    item.candidate = (item.candidate or "").replace(fix["find"], fix.get("replace", ""), 1)
            for item in flagged:
                still = service.problem(item.english, item.candidate or "")
                if still is None:
                    item.text, item.status, item.reason = item.candidate or item.english, "fixed", None
                    fixed_count += 1
                else:
                    item.text, item.status, item.reason = item.english, "fallback", still[0]
            telemetry.set_span_output(span, {
                "flagged": len(flagged), "fixed": fixed_count, "fallback": len(flagged) - fixed_count,
                "durationMs": round((time.perf_counter() - started) * 1000),
            })

    def section(self, label: str, english: str) -> Item:
        return self._get(f"section:{label}", english)

    def text(self, english: str) -> Item:
        return self._get(f"text:{english}", english)

    def _get(self, key: str, english: str) -> Item:
        if not self.active:
            return Item(english, english, "ok")
        item = self._resolved.get(key)
        return item if item is not None else Item(english, english, "fallback", reason="missing")
