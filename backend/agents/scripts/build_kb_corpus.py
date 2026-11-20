"""Construit le corpus de la base de connaissances par section (lot E1).

Lit `docs/for_KB/` (aucune lecture S3), nettoie la mise en page, découpe chaque document par section en suivant
sa propre numérotation, et écrit `kb/<version>/` en local : un fichier texte et un `.metadata.json` par section,
un `manifest.json` et un `report.md`. N'envoie rien sur S3, ne change aucun préfixe Terraform, ne lance aucune
ingestion (voir les commandes écrites dans le rapport).

    python -m backend.agents.scripts.build_kb_corpus --source docs/for_KB --out kb/2026-11-15 --version 2026-11-15

Principes (GN-3200-26-001, sections 2.1.1 et 3.3 ; plan du lot E) :
- Extraction : `pdftotext -layout` (garde « toler ance » intact, contrairement à pypdf) ; .txt lus tels quels.
- Nettoyage : en-têtes et pieds de page des PDF (lignes répétées d'une page à l'autre), numéros de page isolés,
  lignes de page web (Source, Breadcrumb, HOME, Type, fil d'Ariane), tables des matières (titre répété : on garde
  l'occurrence qui a du texte), listes « Previous Guidance Note(s) » et « Related Documents ».
- Découpage : par section numérotée du document ; sans numérotation fiable, par groupes de pages, SANS numéro
  inventé (`section` absent, `pages` renseigné).
- Chaque section est un fichier : les métadonnées s'appliquent par fichier, donc chaque passage porte sa section
  sans changer le découpage de la source (FIXED_SIZE 300 jetons, 20 %).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.agents.tools.kb import DOCUMENT_TITLES, KNOWN_SUBJECTS, excerpt_of, section_label

HERE = Path(__file__).parent / "kb_corpus"
CITABLE_REGULATORS = {"CSA", "CSA-IIROC", "CSA-CIRO", "CSA-AMF", "CIRO", "FSRA", "AMF", "FCAA"}
PAGE_GROUP = 3
TOC_LEADER = re.compile(r"\.{4,}")
BARE_PAGE_NUMBER = re.compile(r"^\s*(?:Page\s+)?\d{1,3}(?:\s*(?:of|/)\s*\d{1,3})?\s*$", re.IGNORECASE)
MAX_METADATA_BYTES = 1500
TITLE_MAX = 80
NOTES_SUBJECT = "notes"


@dataclass
class Line:
    text: str
    page: int | None


@dataclass
class Section:
    section: str | None
    title: str | None
    lines: list[Line] = field(default_factory=list)
    order: int = 0

    def body(self) -> str:
        return "\n".join(line.text for line in self.lines).strip()

    def pages(self) -> str | None:
        pages = [line.page for line in self.lines if line.page is not None and line.text]
        if not pages:
            return None
        low, high = min(pages), max(pages)
        return str(low) if low == high else f"{low}-{high}"


@dataclass
class Removed:
    counts: Counter = field(default_factory=Counter)

    def add(self, kind: str, n: int = 1) -> None:
        self.counts[kind] += n


def normalize(text: str) -> str:
    """Pour les contrôles seulement : apostrophes et espaces normalisés."""
    return re.sub(r"\s+", " ", text.replace("’", "'").replace("‘", "'").replace(" ", " "))



def extract_pages(path: Path) -> list[str]:
    if path.suffix.lower() == ".pdf":
        if shutil.which("pdftotext") is None:
            raise RuntimeError("pdftotext est requis (paquet poppler-utils)")
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True).stdout
        pages = out.split("\f")
        return pages[:-1] if pages and not pages[-1].strip() else pages
    return [path.read_text(encoding="utf-8")]



def repeated_page_lines(pages: list[str]) -> set[str]:
    """En-têtes et pieds de page : lignes (chiffres normalisés) qui reviennent en haut ou en bas de nombreuses pages."""
    if len(pages) < 4:
        return set()
    counts: Counter = Counter()
    for page in pages:
        edge = [ln.strip() for ln in page.splitlines() if ln.strip()]
        for text in set(edge[:3] + edge[-3:]):
            counts[re.sub(r"\d+", "#", text)] += 1
    threshold = max(3, int(0.3 * len(pages)))
    return {text for text, n in counts.items() if n >= threshold and len(text) < 160}


def clean_lines(pages: list[str], cfg: dict[str, Any], removed: Removed, is_pdf: bool = True) -> list[Line]:
    headers = repeated_page_lines(pages)
    drop = [re.compile(p) for p in cfg.get("drop_line_regex", [])]
    lines: list[Line] = []
    for number, page in enumerate(pages, start=1):
        for raw in page.splitlines():
            text = raw.strip()
            if not text:
                lines.append(Line("", number))
                continue
            if re.sub(r"\d+", "#", text) in headers:
                removed.add("en-tête ou pied de page")
            elif is_pdf and BARE_PAGE_NUMBER.match(text):
                removed.add("numéro de page isolé")
            elif TOC_LEADER.search(text):
                removed.add("ligne de table des matières")
            elif any(rx.search(text) for rx in drop):
                removed.add("ligne de mise en page")
            else:
                lines.append(Line(text, number))
    until = cfg.get("preamble_until")
    if until:
        rx = re.compile(until)
        for index, line in enumerate(lines):
            if rx.search(line.text):
                removed.add("ligne de préambule de page web", index)
                lines = lines[index:]
                break
    return lines


def split_footnotes(lines: list[Line], removed: Removed) -> tuple[list[Line], list[str]]:
    """Pages web .txt : une note de bas de page tient sur deux lignes (numéro seul, puis texte)."""
    kept: list[Line] = []
    notes: list[str] = []
    index = 0
    while index < len(lines):
        if re.fullmatch(r"\d{1,2}", lines[index].text) and index + 1 < len(lines) and len(lines[index + 1].text) > 30:
            notes.append(f"{lines[index].text} {lines[index + 1].text}")
            removed.add("note de bas de page (fichier notes)")
            index += 2
            continue
        kept.append(lines[index])
        index += 1
    return kept, notes



def split_numbered(lines: list[Line], cfg: dict[str, Any], removed: Removed) -> list[Section]:
    levels = [re.compile(p) for p in cfg["levels"]]
    boundaries = [re.compile(p) for p in cfg.get("boundary_regex", [])]
    sections: list[Section] = []
    stack: list[str] = []
    current = Section(None, cfg.get("preamble_title"), order=0)
    for line in lines:
        text = line.text
        matched = None
        for depth, rx in enumerate(levels):
            m = rx.match(text)
            if m:
                matched = (depth, m.group("num"), m.group("title").strip())
                break
        if matched:
            depth, num, title = matched
            if len(levels) > 1:
                stack = stack[:depth] + [num]
                num = ".".join(stack)
            sections.append(current)
            current = Section(num, title, order=len(sections))
            continue
        if any(rx.match(text) for rx in boundaries):
            sections.append(current)
            current = Section(None, None, order=len(sections))
            removed.add("titre de partie ou annexe")
            continue
        current.lines.append(line)
    sections.append(current)
    return [s for s in sections if s.body()]


def split_pages(lines: list[Line], doc_title: str) -> list[Section]:
    """Sans numérotation fiable : groupes de pages. `section` reste vide (aucun numéro inventé)."""
    pages = sorted({line.page for line in lines if line.page is not None})
    if len(pages) <= PAGE_GROUP:
        return [Section(None, doc_title, lines=list(lines), order=1)] if any(ln.text for ln in lines) else []
    groups = [pages[i:i + PAGE_GROUP] for i in range(0, len(pages), PAGE_GROUP)]
    sections = []
    for order, group in enumerate(groups, start=1):
        chunk = [ln for ln in lines if ln.page in group]
        if any(ln.text for ln in chunk):
            sections.append(Section(None, None, lines=chunk, order=order))
    return sections


def prune(sections: list[Section], cfg: dict[str, Any], removed: Removed) -> list[Section]:
    """Retire les listes de documents liés, puis les doublons de titre (table des matières) : on garde le plus long."""
    drop = [re.compile(p, re.IGNORECASE) for p in cfg.get("drop_section_title_regex", [])]
    kept = []
    for section in sections:
        if section.title and any(rx.search(section.title) for rx in drop):
            removed.add("section de documents liés")
            continue
        kept.append(section)
    best: dict[str, Section] = {}
    for section in kept:
        if section.section is None:
            continue
        if section.section not in best or len(section.body()) > len(best[section.section].body()):
            best[section.section] = section
    out = []
    for section in kept:
        if section.section is not None and best[section.section] is not section:
            removed.add("doublon de titre (table des matières)")
            continue
        out.append(section)
    return out



def short_title(title: str | None) -> str | None:
    if not title:
        return None
    title = re.split(r"\s\((?:Section|Subsection|Subparagraph|Paragraph)s?\b", title)[0].strip()
    return title if len(title) <= TITLE_MAX else title[: TITLE_MAX - 1].rsplit(" ", 1)[0] + "…"


def subjects_for(doc_key: str, section: str | None, doc_subjects: list[str], proposal: dict[str, Any]) -> tuple[list[str], bool]:
    """(sujets, hérités du document ?). Le préfixe de section le plus long gagne."""
    cfg = proposal.get("documents", {}).get(doc_key, {"default": "inherit"})
    best = None
    for prefix, subjects in (cfg.get("sections") or {}).items():
        if section and (section == prefix or section.startswith(prefix + ".")):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, subjects)
    if best:
        return list(best[1]), False
    default = cfg.get("default", "inherit")
    return (list(doc_subjects), True) if default == "inherit" else (list(default), False)


def doc_key_of(name: str) -> str | None:
    for prefix in sorted(DOCUMENT_TITLES, key=len, reverse=True):
        if name.startswith(prefix):
            return prefix
    return None


def build_metadata(base: dict[str, Any], doc_key: str, version: str, section: Section, subjects: list[str], citable: bool,
                   pages: str | None = None) -> dict[str, Any]:
    attributes = {k: v for k, v in base.items() if k != "sujets"}
    attributes.update({
        "sujets": subjects,
        "doc_id": doc_key,
        "citable": citable,
        "statut": "projet" if base.get("regulateur") == "FCAA" else "en_vigueur",
        "corpus_version": version,
        "ordre": section.order,
    })
    if section.section:
        attributes["section"] = section.section
    title = short_title(section.title)
    if title:
        attributes["section_titre"] = title
    if pages:
        attributes["pages"] = pages
    size = len(json.dumps({"metadataAttributes": attributes}, ensure_ascii=False).encode("utf-8"))
    if size > MAX_METADATA_BYTES:
        raise ValueError(f"{doc_key} {section.section}: métadonnées de {size} octets (> {MAX_METADATA_BYTES})")
    unknown = [s for s in subjects if s not in KNOWN_SUBJECTS and s != NOTES_SUBJECT]
    if unknown:
        raise ValueError(f"{doc_key}: sujets hors KNOWN_SUBJECTS: {unknown}")
    return {"metadataAttributes": attributes}


def file_stem(doc_key: str, section: Section) -> str:
    return f"{doc_key}__s{section.section}" if section.section else f"{doc_key}__o{section.order:02d}"



def build_document(path: Path, rules: dict[str, Any], proposal: dict[str, Any], version: str, out: Path) -> dict[str, Any]:
    doc_key = doc_key_of(path.name)
    if doc_key is None:
        raise ValueError(f"Document inconnu de kb.DOCUMENT_TITLES : {path.name}")
    base = json.loads(Path(str(path) + ".metadata.json").read_text(encoding="utf-8"))["metadataAttributes"]
    cfg = rules.get("documents", {}).get(doc_key, {})
    removed = Removed()
    lines = clean_lines(extract_pages(path), cfg, removed, is_pdf=path.suffix.lower() == ".pdf")
    notes: list[str] = []
    if cfg.get("footnotes") == "txt_numbered_lines":
        lines, notes = split_footnotes(lines, removed)
    sections = split_numbered(lines, cfg, removed) if cfg.get("levels") else split_pages(lines, DOCUMENT_TITLES[doc_key])
    sections = prune(sections, cfg, removed)
    citable = base.get("regulateur") in CITABLE_REGULATORS
    is_pdf = path.suffix.lower() == ".pdf"
    entries, inherited = [], []
    for section in sections:
        subjects, inherits = subjects_for(doc_key, section.section, base.get("sujets", []), proposal)
        if inherits:
            inherited.append(section.section or f"o{section.order:02d}")
        stem = file_stem(doc_key, section)
        body = section.body()
        (out / f"{stem}_en.txt").write_text(body + "\n", encoding="utf-8")
        pages = section.pages() if is_pdf else None
        metadata = build_metadata(base, doc_key, version, section, subjects, citable, pages)
        (out / f"{stem}_en.txt.metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        entries.append({
            "doc_id": doc_key, "section": section.section, "section_titre": short_title(section.title), "langue": base.get("langue", "en"),
            "file": f"{stem}_en.txt", "titre": DOCUMENT_TITLES[doc_key], "taille": len(body), "pages": pages,
            "citable": citable, "statut": metadata["metadataAttributes"]["statut"], "ordre": section.order,
        })
    if notes:
        stem = f"{doc_key}__notes"
        (out / f"{stem}_en.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
        note_section = Section(None, "Footnotes", order=999)
        metadata = build_metadata(base, doc_key, version, note_section, [NOTES_SUBJECT], False)
        (out / f"{stem}_en.txt.metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        entries.append({"doc_id": doc_key, "section": None, "section_titre": "Footnotes", "langue": "en", "file": f"{stem}_en.txt",
                        "titre": DOCUMENT_TITLES[doc_key], "taille": sum(len(n) for n in notes), "pages": None, "citable": False,
                        "statut": metadata["metadataAttributes"]["statut"], "ordre": 999})
    all_text = normalize(" ".join((out / e["file"]).read_text(encoding="utf-8") for e in entries if e["section_titre"] != "Footnotes"))
    checks = []
    for phrase in cfg.get("must_contain", []):
        checks.append({"kind": "présente", "phrase": phrase, "ok": normalize(phrase) in all_text})
    for phrase in cfg.get("must_not_contain", []):
        checks.append({"kind": "absente", "phrase": phrase, "ok": normalize(phrase) not in all_text})
    return {"doc_id": doc_key, "source": path.name, "sections": entries, "removed": dict(removed.counts),
            "inherited": inherited, "checks": checks, "numbered": bool(cfg.get("levels"))}


def _pinned(out: Path, entry: dict[str, Any]) -> dict[str, Any]:
    metadata = json.loads((out / f"{entry['file']}.metadata.json").read_text(encoding="utf-8"))["metadataAttributes"]
    return {
        "document": DOCUMENT_TITLES[entry["doc_id"]], "section": section_label(metadata, None, DOCUMENT_TITLES[entry["doc_id"]]), "sectionTitle": metadata.get("section_titre"),
        "excerpt": excerpt_of((out / entry["file"]).read_text(encoding="utf-8")), "jurisdiction": metadata["juridiction"],
        "regulator": metadata["regulateur"], "status": metadata["statut"], "documentType": metadata["type_document"],
        "language": metadata["langue"], "url": metadata.get("source_url"), "version": metadata.get("date_version"), "file": entry["file"],
    }


def build_fixed_citations(manifest_sections: list[dict[str, Any]], rules: dict[str, Any], version: str, out: Path) -> dict[str, Any]:
    """Citations que le code attache lui-même (R5, R9) : texte embarqué dans le zip, lié à `corpus_version`."""
    def find(target: dict[str, Any]) -> dict[str, Any]:
        for entry in manifest_sections:
            if entry["doc_id"] != target["doc_id"] or not entry["citable"]:
                continue
            if ("section" in target and entry["section"] == target["section"]) or ("order" in target and entry["ordre"] == target["order"]):
                return entry
        raise ValueError(f"Section fixée introuvable : {target}")

    spec = rules.get("fixed_citations", {})
    return {
        "corpus_version": version,
        "R5": [_pinned(out, find(t)) for t in spec.get("R5", [])],
        "R9": {province: [_pinned(out, find(t)) for t in targets] for province, targets in spec.get("R9", {}).items()},
    }


def render_report(results: list[dict[str, Any]], version: str, out: Path) -> str:
    lines = [f"# Rapport du corpus {version}", "", "Généré par `build_kb_corpus.py` (aucun envoi, aucune ingestion).", "",
             "| Document | Sections | Numérotées | Citable | Statut | Taille totale |", "|---|---|---|---|---|---|"]
    for r in results:
        first = r["sections"][0]
        lines.append(f"| {r['doc_id']} | {len(r['sections'])} | {'oui' if r['numbered'] else 'non (groupes de pages)'} | "
                     f"{first['citable']} | {first['statut']} | {sum(s['taille'] for s in r['sections'])} |")
    lines += ["", "## Blocs retirés", ""]
    for r in results:
        lines.append(f"- **{r['doc_id']}** : " + (", ".join(f"{k} ×{v}" for k, v in sorted(r["removed"].items())) or "rien"))
    lines += ["", "## Sections aux sujets hérités du document (à relire, V5)", ""]
    for r in results:
        if r["inherited"]:
            lines.append(f"- **{r['doc_id']}** : {', '.join(r['inherited'][:60])}" + (" …" if len(r["inherited"]) > 60 else ""))
    lines += ["", "## Contrôles de phrases", ""]
    for r in results:
        for c in r["checks"]:
            lines.append(f"- {'OK' if c['ok'] else 'ÉCHEC'} {r['doc_id']} : phrase {c['kind']} « {c['phrase']} »")
    lines += ["", "## Alignement anglais-français", "",
              "Aucune version française dans ce corpus (E3 reporté) : `langue` vaut `en` partout ; `doc_id` et `section` sont conservés "
              "pour qu'un alignement puisse s'ajouter plus tard sans nouvelle ingestion.", "",
              "## Commandes à lancer par l'équipe (non exécutées)", "", "```bash",
              "cp kb/" + version + "/fixed_citations.json backend/agents/data/fixed_citations.json   # puis reconstruire la Lambda agents",
              "source scripts/aws-env.sh",
              f"aws s3 sync {out}/ s3://alphaforge-dataset-058264316309/kb/{version}/ --delete",
              f"# infra/terraform : kb_corpus_version = \"{version}\", puis terraform plan et apply (accord requis)",
              "aws bedrock-agent start-ingestion-job --knowledge-base-id CHMZAJEICM --data-source-id LJLQ9CGHXK",
              f"# Lambda agents : variable d'environnement KB_CORPUS_VERSION = \"{version}\" (filtre citable strict + citations fixées R5/R9)",
              "# après l'ingestion : refaire la recherche R5 (CA + QC) et vérifier que la section 2.1.1 figure parmi les 5 passages gardés",
              "```", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source", default="docs/for_KB", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    rules = json.loads((HERE / "rules.json").read_text(encoding="utf-8"))
    proposal = json.loads((HERE / "subjects.json").read_text(encoding="utf-8"))
    if args.out.exists() and any(args.out.iterdir()):
        print(f"Le dossier {args.out} n'est pas vide : choisir une nouvelle version.", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    documents = sorted(p for p in args.source.iterdir() if p.suffix.lower() in (".pdf", ".txt") and not p.name.endswith(".metadata.json"))
    results = [build_document(p, rules, proposal, args.version, args.out) for p in documents]
    manifest = {"corpus_version": args.version, "documents": len(results),
                "sections": [s for r in results for s in r["sections"]]}
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    fixed = build_fixed_citations(manifest["sections"], rules, args.version, args.out)
    (args.out / "fixed_citations.json").write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render_report(results, args.version, args.out)
    (args.out / "report.md").write_text(report, encoding="utf-8")
    print(report)
    failed = [c for r in results for c in r["checks"] if not c["ok"]]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
