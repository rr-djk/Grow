#!/usr/bin/env python3
"""Supprime les commentaires du code source, sans toucher au reste.

Le script repère les plages de commentaires avec le tokenizer du langage
(ou un scanner dédié pour HCL, le shell et le CSS), puis les efface
caractère par caractère. Aucun autre octet du fichier n'est modifié :
pas de reformatage, pas de réécriture de chaînes, pas de perte de position.

Ce qui n'est jamais supprimé :

  * les docstrings Python : Strands les envoie au LLM comme description
    d'outil (backend/agents/tools/agent_tools.py), donc elles sont du code ;
  * les directives fonctionnelles : `# noqa`, `# type: ignore`,
    `# pragma: no cover`, shebangs, cookies d'encodage, `// @vitest-environment`,
    `// @ts-ignore`, `eslint-disable`, `/* @__PURE__ */`, `# shellcheck`… ;
  * les fichiers de test, les skills vendored (.agents/), les données,
    la documentation et les fichiers générés.

Trois modes :

  (défaut)   dry-run : compte les commentaires, n'écrit rien ;
  --check    sortie 1 s'il reste un commentaire supprimable (usage CI) ;
  --write    écrit, fichier par fichier, après vérification que le code
             hors commentaires n'a pas changé.

Chaque fichier passe trois contrôles avant d'être écrit, et il est ignoré
sinon : le code restant se re-analyse, aucun commentaire supprimable ne
subsiste, et la signature des jetons (hors commentaires) est identique.

Exemples :

  python scripts/strip_comments.py                      # état des lieux
  python scripts/strip_comments.py --diff               # + le diff complet
  python scripts/strip_comments.py --lang python        # un seul langage
  python scripts/strip_comments.py --write              # applique
  python scripts/strip_comments.py --check ; echo $?    # 0 = rien à faire

Le TypeScript/JavaScript est analysé par @babel/parser, cherché dans
frontend/node_modules (installé par `cd frontend && npm ci`). S'il manque,
les fichiers TS/JS sont laissés intacts et le script sort en code 2.
"""

from __future__ import annotations

import argparse
import codecs
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent

# Répertoires scannés, relatifs à la racine du dépôt.
SCAN_DIRS = ("backend", "frontend", "infra", "scripts", "profiling")

# Répertoires ignorés partout (vendored, générés, données, caches).
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode",
    ".venv", "venv", "env", "node_modules", "__pycache__", "site-packages",
    ".agents", ".archify", ".opencode", "graphify-out", "data", "contract", "docs",
    "dist", "build", "coverage", ".terraform", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".cache",
}

# Un répertoire de tests n'est jamais nettoyé.
TEST_DIRS = {"tests", "test", "__tests__", "e2e", "fixtures"}

LANGUAGES = ("python", "typescript", "terraform", "shell", "css")

EXTENSIONS = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".mjs": "typescript",
    ".cjs": "typescript",
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".hcl": "terraform",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".css": "css",
}

TEST_FILE_RE = re.compile(
    r"^(?:test_.*\.py|.*_test\.py|conftest\.py|.*\.(?:test|spec)\.[cm]?[jt]sx?)$"
)
GENERATED_FILE_RE = re.compile(r"(?:\.min\.[cm]?[jt]s|\.min\.css|\.bundle\.js)$")


# ---------------------------------------------------------------------------
# Directives fonctionnelles : ces commentaires sont conservés.
# ---------------------------------------------------------------------------

PYTHON_KEEP_RE = re.compile(
    r"#!|-\*-|coding[:=]"
    # Pas de \b final : « type: » et « pragma: » finissent par un caractère
    # non-mot, et `\b` après « : » ne correspondrait donc jamais.
    r"|\b(?:noqa|type:|pragma:|fmt:|isort:|mypy:|ruff:|flake8:|pylint:"
    r"|nosec|codespell:|spellchecker:)",
    re.IGNORECASE,
)

TYPESCRIPT_KEEP_RE = re.compile(
    r"@vitest-environment|@jest-environment|@jest-environment-options"
    r"|@ts-(?:ignore|expect-error|nocheck|check)"
    r"|eslint-|prettier-ignore|biome-ignore|tslint:"
    r"|@__PURE__|@__NO_SIDE_EFFECTS__|#__PURE__"
    r"|sourceMappingURL|sourceURL"
    r"|istanbul ignore|vite-ignore|webpackChunkName|webpackIgnore"
    r"|@flow\b|@jsx\b|@jsxImportSource|@jsxFrag"
    # `/// <reference … />` : la valeur Babel conserve un `/` du préfixe `///`.
    r"|^\s*/?\s*<reference\b"
)

SHELL_KEEP_RE = re.compile(r"shellcheck", re.IGNORECASE)

# Aucune directive fonctionnelle connue pour HCL et CSS.
HCL_KEEP_RE = None
CSS_KEEP_RE = None


# ---------------------------------------------------------------------------
# Modèle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Comment:
    start: int
    end: int
    text: str


@dataclass
class Job:
    path: Path
    rel: str
    lang: str
    original: str
    dump: Callable[[str], bytes]
    comments: list[Comment] = field(default_factory=list)
    kept: list[Comment] = field(default_factory=list)
    dropped: list[Comment] = field(default_factory=list)
    stripped: str | None = None
    tokens_before: list[str] = field(default_factory=list)
    tokens_after: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def removed_lines(self) -> int:
        if self.stripped is None:
            return 0
        return len(self.original.splitlines()) - len(self.stripped.splitlines())


# ---------------------------------------------------------------------------
# Découverte des fichiers
# ---------------------------------------------------------------------------


def is_test_path(path: Path, rel: str) -> bool:
    parts = Path(rel).parts
    if any(part in TEST_DIRS for part in parts[:-1]):
        return True
    return bool(TEST_FILE_RE.match(path.name))


def discover(langs: set[str]) -> list[tuple[Path, str]]:
    # Ce script ne se nettoie pas lui-même : il ne doit pas réécrire sa propre
    # source pendant qu'il tourne, et ses commentaires expliquent les scanners.
    myself = Path(__file__).resolve()
    found: list[tuple[Path, str]] = []
    for base in SCAN_DIRS:
        directory = ROOT / base
        if not directory.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(directory):
            dirnames[:] = sorted(
                name for name in dirnames if name not in EXCLUDED_DIRS
            )
            for name in sorted(filenames):
                path = Path(dirpath) / name
                lang = EXTENSIONS.get(path.suffix.lower())
                if lang is None or lang not in langs:
                    continue
                if name.startswith(".") or GENERATED_FILE_RE.search(name):
                    continue
                if name.endswith(".lock.hcl"):
                    continue
                rel = path.relative_to(ROOT).as_posix()
                if is_test_path(path, rel):
                    continue
                if path.resolve() == myself:
                    continue
                found.append((path, lang))
    return found


def load(path: Path) -> tuple[str, Callable[[str], bytes]]:
    """Lit le fichier en normalisant BOM et CRLF, et renvoie de quoi l'écrire."""
    raw = path.read_bytes()
    bom = raw.startswith(codecs.BOM_UTF8)
    text = raw.decode("utf-8-sig")
    crlf = "\r\n" in text
    if crlf:
        text = text.replace("\r\n", "\n")

    def dump(value: str) -> bytes:
        data = value.encode("utf-8")
        if crlf:
            data = data.replace(b"\n", b"\r\n")
        if bom:
            data = codecs.BOM_UTF8 + data
        return data

    return text, dump


# ---------------------------------------------------------------------------
# Collecte des plages de commentaires par langage
# ---------------------------------------------------------------------------


def python_comments(text: str) -> list[Comment]:
    line_starts = [0]
    for line in text.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))

    def offset(row: int, column: int) -> int:
        return line_starts[row - 1] + column

    found: list[Comment] = []
    for token in tokenize.generate_tokens(StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            found.append(
                Comment(offset(*token.start), offset(*token.end), token.string)
            )
    return found


def csv_comments(text: str) -> list[Comment]:
    """Commentaires `/* … */` en respectant les chaînes."""
    found: list[Comment] = []
    index, size = 0, len(text)
    while index < size:
        char = text[index]
        if char in "\"'":
            quote = char
            index += 1
            while index < size:
                if text[index] == "\\":
                    index += 2
                elif text[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = size if end == -1 else end + 2
            found.append(Comment(index, end, text[index:end]))
            index = end
            continue
        index += 1
    return found


def hcl_comments(text: str) -> list[Comment]:
    """Commentaires HCL : `#`, `//` et `/* */`, hors chaînes, heredocs et `${…}`."""
    found: list[Comment] = []
    index, size = 0, len(text)
    while index < size:
        char = text[index]
        if char == '"':
            index = _skip_hcl_string(text, index)
            continue
        if text.startswith("<<", index):
            heredoc_end = _skip_heredoc(text, index)
            index = heredoc_end if heredoc_end is not None else index + 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = size if end == -1 else end + 2
            found.append(Comment(index, end, text[index:end]))
            index = end
            continue
        if char == "#" or text.startswith("//", index):
            end = text.find("\n", index)
            end = size if end == -1 else end
            found.append(Comment(index, end, text[index:end]))
            index = end
            continue
        index += 1
    return found


def _skip_hcl_string(text: str, index: int) -> int:
    """Renvoie l'index qui suit la chaîne commençant à `index` (guillemet ouvrant)."""
    index += 1
    size = len(text)
    while index < size:
        char = text[index]
        if char == "\\":
            index += 2
        elif char == '"':
            return index + 1
        elif text.startswith("${", index):
            index = _skip_hcl_interpolation(text, index + 2)
        else:
            index += 1
    return size


def _skip_hcl_interpolation(text: str, index: int) -> int:
    """Renvoie l'index qui suit le `}` fermant l'interpolation ouverte avant `index`."""
    depth, size = 1, len(text)
    while index < size:
        char = text[index]
        if char == '"':
            index = _skip_hcl_string(text, index)
        elif char == "{":
            depth += 1
            index += 1
        elif char == "}":
            depth -= 1
            index += 1
            if depth == 0:
                return index
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = size if end == -1 else end + 2
        elif char == "#" or text.startswith("//", index):
            end = text.find("\n", index)
            index = size if end == -1 else end
        else:
            index += 1
    return size


def _skip_heredoc(text: str, index: int) -> int | None:
    """Renvoie l'index de fin du heredoc ouvert à `index` (`<<MARQUEUR`), ou None."""
    cursor = index + 2
    if cursor < len(text) and text[cursor] == "-":
        cursor += 1
    if cursor < len(text) and text[cursor] in "\"'":
        quote = text[cursor]
        close = text.find(quote, cursor + 1)
        if close == -1:
            return None
        marker = text[cursor + 1 : close]
        cursor = close + 1
    else:
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text[cursor:])
        if not match:
            return None
        marker = match.group(0)
        cursor += len(marker)

    line_end = text.find("\n", cursor)
    if line_end == -1 or text[cursor:line_end].strip():
        return None

    position = line_end + 1
    while position < len(text):
        end_of_line = text.find("\n", position)
        if end_of_line == -1:
            end_of_line = len(text)
        if text[position:end_of_line].strip() == marker:
            return end_of_line
        position = end_of_line + 1
    return len(text)


SHELL_WORD_BREAK = set(" \t\n;|&(")


def shell_comments(text: str) -> list[Comment]:
    """Lignes de commentaire du shell, hors chaînes, `${#var}` et heredocs."""
    found: list[Comment] = []
    index, size = 0, len(text)
    quote: str | None = None
    while index < size:
        char = text[index]
        if quote is not None:
            if char == "\\" and quote == '"':
                index += 2
            elif char == quote:
                quote = None
                index += 1
            else:
                index += 1
            continue
        if char in "'\"":
            quote = char
            index += 1
            continue
        if char == "\\":
            index += 2
            continue
        if char == "#" and (index == 0 or text[index - 1] in SHELL_WORD_BREAK):
            end = text.find("\n", index)
            end = size if end == -1 else end
            if not (index == 0 and text.startswith("#!")):
                found.append(Comment(index, end, text[index:end]))
            index = end
            continue
        if text.startswith("<<", index):
            heredoc_end = _skip_heredoc(text, index)
            if heredoc_end is not None:
                index = heredoc_end
                continue
        index += 1
    return found


# ---------------------------------------------------------------------------
# TypeScript / JavaScript : une seule passe node pour tout le lot
# ---------------------------------------------------------------------------

BABEL_SCRIPT = r"""
const parser = require(process.argv[1]);
let payload = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { payload += chunk; });
process.stdin.on("end", () => {
  const files = JSON.parse(payload);
  const out = files.map((file) => {
    let plugins;
    if (/\.tsx$/.test(file.name)) plugins = ["typescript", "jsx"];
    else if (/\.ts$/.test(file.name)) plugins = [["typescript", { dts: /\.d\.ts$/.test(file.name) }]];
    else plugins = ["jsx"];
    try {
      const ast = parser.parse(file.code, {
        sourceType: "unambiguous",
        allowReturnOutsideFunction: true,
        allowAwaitOutsideFunction: true,
        allowSuperOutsideMethod: true,
        allowUndeclaredExports: true,
        attachComment: false,
        tokens: true,
        plugins,
      });
      const comments = (ast.comments || []).map((comment) => ({
        start: comment.start,
        end: comment.end,
        text: comment.value,
        block: comment.type === "CommentBlock",
      }));
      // Les jetons de commentaire ont un `type` qui est une chaîne
      // ("CommentLine" / "CommentBlock"), les vrais jetons un objet.
      const tokens = (ast.tokens || [])
        .filter((token) => typeof token.type !== "string")
        .map((token) => {
          const label = token.type && token.type.label !== undefined
            ? token.type.label
            : String(token.type);
          const value = token.value === undefined || token.value === null
            ? ""
            : String(token.value);
          return label + "\u0000" + value;
        });
      return { name: file.name, comments, tokens, error: null };
    } catch (error) {
      return {
        name: file.name,
        comments: [],
        tokens: [],
        error: error && error.message ? error.message : String(error),
      };
    }
  });
  process.stdout.write(JSON.stringify(out));
});
"""


class BabelError(RuntimeError):
    pass


BABEL_SKIPPED = "Babel indisponible"


def babel_parser_path() -> Path:
    return ROOT / "frontend" / "node_modules" / "@babel" / "parser"


def run_babel(texts: list[tuple[str, str]]) -> list[dict]:
    node = shutil.which("node")
    if node is None:
        raise BabelError("node est introuvable dans le PATH")
    package = babel_parser_path()
    if not package.is_dir():
        raise BabelError(
            f"{package} est absent (installer avec `cd frontend && npm ci`)"
        )
    payload = json.dumps(
        [{"name": name, "code": code} for name, code in texts], ensure_ascii=False
    )
    try:
        completed = subprocess.run(
            [node, "-e", BABEL_SCRIPT, str(package)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except OSError as error:
        raise BabelError(f"node n'a pas pu démarrer : {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        raise BabelError(
            "l'analyse Babel a échoué : " + (detail[-1] if detail else "sans détail")
        )
    return json.loads(completed.stdout)


# ---------------------------------------------------------------------------
# Filtre des directives et suppression
# ---------------------------------------------------------------------------

WORD_RE = re.compile(r"[A-Za-z0-9_$]")


def keep_comment(lang: str, comment: Comment, *, keep_doc: bool) -> bool:
    if lang == "python":
        return bool(PYTHON_KEEP_RE.search(comment.text))
    if lang == "typescript":
        # /** … */ : le texte renvoyé par Babel commence par `*`.
        if keep_doc and comment.text.startswith("*"):
            return True
        return bool(TYPESCRIPT_KEEP_RE.search(comment.text))
    if lang == "shell":
        return bool(SHELL_KEEP_RE.search(comment.text))
    return False


def strip_comments(text: str, comments: list[Comment]) -> str:
    """Supprime les commentaires et l'indentation qu'ils laissaient derrière eux."""
    spans: list[tuple[int, int]] = []
    for comment in sorted(comments, key=lambda item: item.start):
        start, end = comment.start, comment.end
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", end)
        if line_end == -1:
            line_end = len(text)
        before = text[line_start:start]
        after = text[end:line_end]
        alone_before = before.strip() == ""
        alone_after = after.strip() == ""

        if alone_before and alone_after:
            # Commentaire seul sur sa ou ses lignes : on retire la ligne entière.
            start = line_start
            end = line_end + 1 if line_end < len(text) else line_end
        elif alone_before:
            # Commentaire en tête de ligne, suivi de code sur la même ligne.
            start = line_start
            end = comment.end
            while end < len(text) and text[end] in " \t":
                end += 1
        elif alone_after:
            # Commentaire de fin de ligne : on retire aussi les espaces avant.
            start = line_start + len(before.rstrip())
            end = comment.end
        spans.append((start, end))

    # Fusionne les plages qui se touchent, et les blocs de commentaires séparés
    # par une seule ligne vide : sinon chaque suppression laisse un blanc.
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            continue
        if merged:
            previous_start, previous_end = merged[-1]
            gap = text[previous_end:start]
            if (
                text[previous_end - 1] == "\n"
                and gap.strip() == ""
                and gap.count("\n") <= 1
            ):
                merged[-1] = (previous_start, end)
                continue
        merged.append((start, end))

    pieces: list[str] = []
    cursor = 0
    for start, end in merged:
        # Une ligne de commentaire encadrée par deux lignes vides n'en laisse
        # qu'une : on avale aussi le saut de ligne qui suit.
        whole_line = (
            (start == 0 or text[start - 1] == "\n")
            and end > 0
            and text[end - 1] == "\n"
        )
        if (
            whole_line
            and text[end : end + 1] == "\n"
            and (start == 0 or (start >= 2 and text[start - 2 : start] == "\n\n"))
        ):
            end += 1

        pieces.append(text[cursor:start])
        previous = text[start - 1] if start else ""
        following = text[end] if end < len(text) else ""
        # `a/*c*/b` ne doit pas devenir `ab` : un espace tient lieu de séparateur.
        if previous and following and WORD_RE.match(previous) and WORD_RE.match(following):
            pieces.append(" ")
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


# ---------------------------------------------------------------------------
# Contrôles avant écriture
# ---------------------------------------------------------------------------


def python_signature(text: str) -> list[str]:
    ignored = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
    return [
        f"{token.type}:{token.string}"
        for token in tokenize.generate_tokens(StringIO(text).readline)
        if token.type not in ignored
    ]


def shell_syntax_ok(interpreter: str, text: str, tmpdir: Path) -> bool | None:
    binary = shutil.which(interpreter)
    if binary is None:
        return None
    probe = tmpdir / f"probe-{os.getpid()}.sh"
    probe.write_text(text, encoding="utf-8")
    try:
        return subprocess.run(
            [binary, "-n", str(probe)], capture_output=True
        ).returncode == 0
    finally:
        probe.unlink(missing_ok=True)


def check_job(job: Job, tmpdir: Path) -> str | None:
    """Renvoie un motif de refus, ou None si le fichier peut être écrit."""
    assert job.stripped is not None
    if job.stripped == job.original:
        return None

    if job.lang == "python":
        try:
            if python_signature(job.original) != python_signature(job.stripped):
                return "les jetons Python ont changé"
            compile(job.stripped, job.rel, "exec")
        except (SyntaxError, tokenize.TokenError) as error:
            return f"le Python nettoyé ne compile plus ({error})"
        return None

    if job.lang == "typescript":
        if job.tokens_before != job.tokens_after:
            return "les jetons TypeScript ont changé"
        return None

    if job.lang == "shell":
        for interpreter in ("bash", "zsh"):
            before = shell_syntax_ok(interpreter, job.original, tmpdir)
            if before is None:
                continue
            after = shell_syntax_ok(interpreter, job.stripped, tmpdir)
            if before and not after:
                return f"`{interpreter} -n` échoue après nettoyage"
            if before:
                return None
        return None

    return None


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Supprime les commentaires du code, sans rien reformater.",
        epilog="Sans --write, aucun fichier n'est modifié.",
    )
    parser.add_argument("--write", action="store_true", help="écrit les fichiers nettoyés")
    parser.add_argument(
        "--check",
        action="store_true",
        help="sortie 1 s'il reste des commentaires supprimables",
    )
    parser.add_argument("--diff", action="store_true", help="affiche le diff complet")
    parser.add_argument(
        "--lang",
        action="append",
        default=[],
        metavar="LANG",
        help="restreint à un langage : " + ", ".join(LANGUAGES) + " (répétable)",
    )
    parser.add_argument(
        "--keep-doc",
        action="store_true",
        help="conserve les blocs /** … */ (JSDoc) du TypeScript",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="écrit aussi les fichiers modifiés mais non commités",
    )
    parser.add_argument(
        "--fmt",
        action="store_true",
        help="passe `terraform fmt` sur les .tf nettoyés (alignement des attributs)",
    )
    parser.add_argument("--quiet", action="store_true", help="résumé seul")
    args = parser.parse_args(argv)
    if args.write and args.check:
        parser.error("--write et --check sont incompatibles")
    return args


def parse_langs(values: list[str]) -> set[str]:
    if not values:
        return set(LANGUAGES)
    wanted: set[str] = set()
    for value in values:
        for item in value.split(","):
            item = item.strip().lower()
            if not item:
                continue
            if item not in LANGUAGES:
                raise SystemExit(
                    f"langage inconnu : {item} (attendu : {', '.join(LANGUAGES)})"
                )
            wanted.add(item)
    return wanted


def dirty_paths() -> set[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return set()
    paths: set[str] = set()
    for line in completed.stdout.splitlines():
        name = line[3:].strip()
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        if name:
            paths.add(str((ROOT / name).resolve()))
    return paths


def print_diff(job: Job) -> None:
    assert job.stripped is not None
    diff = "".join(
        difflib.unified_diff(
            job.original.splitlines(keepends=True),
            job.stripped.splitlines(keepends=True),
            fromfile=job.rel,
            tofile=f"{job.rel} (nettoyé)",
            n=2,
        )
    )
    if diff:
        print(diff, end="" if diff.endswith("\n") else "\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    langs = parse_langs(args.lang)

    files = discover(langs)
    if not files:
        print("Aucun fichier correspondant.")
        return 0

    jobs: list[Job] = []
    for path, lang in files:
        rel = path.relative_to(ROOT).as_posix()
        try:
            original, dump = load(path)
        except (OSError, UnicodeDecodeError) as error:
            print(f"  ignoré  {rel} : {error}")
            continue
        jobs.append(Job(path=path, rel=rel, lang=lang, original=original, dump=dump))

    errors: list[str] = []
    babel_failure: str | None = None

    # --- collecte -----------------------------------------------------------
    typescript_jobs = [job for job in jobs if job.lang == "typescript"]
    if typescript_jobs:
        try:
            results = run_babel([(job.rel, job.original) for job in typescript_jobs])
        except BabelError as error:
            babel_failure = str(error)
            for job in typescript_jobs:
                job.error = BABEL_SKIPPED
        else:
            for job, result in zip(typescript_jobs, results):
                if result.get("error"):
                    job.error = f"analyse impossible : {result['error']}"
                    continue
                job.comments = [
                    Comment(item["start"], item["end"], item["text"])
                    for item in result["comments"]
                ]
                job.tokens_before = result["tokens"]

    for job in jobs:
        if job.lang == "typescript" or job.error is not None:
            continue
        try:
            job.comments = {
                "python": python_comments,
                "terraform": hcl_comments,
                "shell": shell_comments,
                "css": csv_comments,
            }[job.lang](job.original)
        except Exception as error:  # tokenizer cassé : on n'écrit pas ce fichier
            job.error = f"analyse impossible : {error}"

    # --- suppression --------------------------------------------------------
    for job in jobs:
        if job.error is not None:
            continue
        job.kept = [c for c in job.comments if keep_comment(job.lang, c, keep_doc=args.keep_doc)]
        job.dropped = [c for c in job.comments if c not in job.kept]
        job.stripped = strip_comments(job.original, job.dropped)

    # --- contrôle des jetons TypeScript ------------------------------------
    if typescript_jobs:
        touched = [
            job for job in typescript_jobs
            if job.error is None and job.stripped is not None and job.stripped != job.original
        ]
        if touched:
            try:
                results = run_babel([(job.rel, job.stripped or "") for job in touched])
            except BabelError as error:
                errors.append(f"contrôle TypeScript impossible : {error}")
            else:
                for job, result in zip(touched, results):
                    if result.get("error"):
                        job.error = f"relecture impossible : {result['error']}"
                        continue
                    job.tokens_after = result["tokens"]
                    leftovers = [
                        Comment(item["start"], item["end"], item["text"])
                        for item in result["comments"]
                    ]
                    if any(not keep_comment(job.lang, c, keep_doc=args.keep_doc) for c in leftovers):
                        job.error = "des commentaires subsistent après nettoyage"

    # --- contrôles et écriture ---------------------------------------------
    written: list[Job] = []
    dirty = dirty_paths() if args.write else set()
    with_tmpdir = Path(os.environ.get("TMPDIR", "/tmp")) / "opencode"
    with_tmpdir.mkdir(parents=True, exist_ok=True)

    for job in jobs:
        if job.error is None and job.stripped is not None and job.stripped != job.original:
            if job.lang != "typescript":
                leftovers = [
                    c for c in {
                        "python": python_comments,
                        "terraform": hcl_comments,
                        "shell": shell_comments,
                        "css": csv_comments,
                    }[job.lang](job.stripped)
                    if not keep_comment(job.lang, c, keep_doc=args.keep_doc)
                ]
                if leftovers:
                    job.error = "des commentaires subsistent après nettoyage"
            if job.error is None:
                job.error = check_job(job, with_tmpdir)

        if job.error is not None:
            if job.error != BABEL_SKIPPED:
                errors.append(f"{job.rel} : {job.error}")
            continue

        if job.stripped == job.original:
            continue

        if args.write:
            if str(job.path.resolve()) in dirty and not args.allow_dirty:
                errors.append(
                    f"{job.rel} : modifié localement, laissé intact (--allow-dirty pour passer outre)"
                )
                continue
            try:
                job.path.write_bytes(job.dump(job.stripped or ""))
            except OSError as error:
                errors.append(f"{job.rel} : écriture impossible ({error})")
                continue
            written.append(job)

    # --- rapport ------------------------------------------------------------
    if args.write and written:
        terraform_files = [str(job.path) for job in written if job.lang == "terraform"]
        if terraform_files:
            binary = shutil.which("terraform")
            if args.fmt and binary:
                subprocess.run([binary, "fmt", *terraform_files], check=False)
            elif args.fmt:
                errors.append("terraform est absent : `terraform fmt` n'a pas pu être lancé")
            else:
                print(
                    "Les .tf nettoyés ne sont plus alignés : "
                    "lancer `terraform fmt -recursive infra/terraform`."
                )

    if not args.quiet:
        for job in jobs:
            if job.error is not None or not job.dropped:
                continue
            print(
                f"  {job.rel:<58} {job.lang:<10} "
                f"{len(job.dropped):>4} commentaire(s), {job.removed_lines:>4} ligne(s)"
            )
            if job.kept:
                print(f"      conservés : {len(job.kept)} (directive ou docstring)")
        if args.diff:
            for job in jobs:
                if job.error is None and job.dropped and job.stripped != job.original:
                    print()
                    print_diff(job)

    total_comments = sum(len(job.dropped) for job in jobs if job.error is None)
    total_files = sum(1 for job in jobs if job.dropped and job.error is None)
    total_lines = sum(job.removed_lines for job in jobs if job.error is None)
    kept_total = sum(len(job.kept) for job in jobs)

    print()
    print(
        f"{total_comments} commentaire(s) supprimable(s) dans {total_files} fichier(s), "
        f"{total_lines} ligne(s) ; {kept_total} conservé(s)."
    )
    if written:
        print(f"{len(written)} fichier(s) nettoyé(s).")
    elif not args.write and total_comments:
        print("Aucun fichier modifié (ajouter --write pour appliquer).")

    if babel_failure is not None:
        print()
        print(
            f"TypeScript/JavaScript non traité ({len(typescript_jobs)} fichiers) : "
            f"{babel_failure}"
        )

    if errors:
        print()
        print("Fichiers laissés intacts :")
        for message in errors:
            print(f"  - {message}")

    if args.check:
        if babel_failure is not None:
            return 2
        return 1 if total_comments else 0
    return 2 if babel_failure is not None else 0


if __name__ == "__main__":
    sys.exit(main())
