"""Evidence for a specification decision, searched in the app's folder (``spec_decisions``). Reads files only;
nothing of the repository runs. Every hit is ``file:line kind: excerpt``.

- a technology (an entry of the code style's ``technologies`` catalog): a dependency in a manifest, a use in the
  non-test code (``uses``);
- a literal (a number with its unit, a quoted string): the decision's term and the literal near each other in the
  code or its data assets, or the term with another literal (e.g. a grind setting
  default was decided and the app shipped 0.0).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...engineering_knowledge import stacks as stack_data

MAX_FILES = 6000
MAX_FILE_BYTES = 1_000_000
NEAR_LINES = 2
_COMMENT = ("//", "#", "*", "/*", "--")


def named_technologies(text: str, catalog: dict[str, dict[str, Any]]) -> list[str]:
    """The catalog keys a decision names (whole words, case-insensitive)."""
    lowered = text.lower()
    return [key for key, entry in catalog.items()
            if any(re.search(rf"(?<!\w){re.escape(word.lower())}(?!\w)", lowered) for word in entry.get("words") or [])]


# A clause that defers or excludes what it names ("until the follow-up ticket "Persistence with drift/SQLite" (not
# part of this work)", "no cloud", "later", "not part of"): its technologies are no decision of this work.
_DEFERRED = re.compile(r"(?<!\w)(follow-up|follow up|followup|not part|not in scope|out of scope|later|without|"
                       r"no)(?!\w)", re.IGNORECASE)
_CLAUSES = re.compile(r"(?:;|(?<=[.!?])\s)")


def decided_technologies(text: str, catalog: dict[str, dict[str, Any]]) -> list[str]:
    """The catalog keys a decision commits to: named in at least one clause that does not defer or exclude them.
    Example: decision 16 ("Flag with shared_preferences … grinder and bean stay in memory until the follow-up
    ticket "Persistence with drift/SQLite" (not part of this work)") was "missing"
    because drift/SQLite were not built, and the story's PR went out with that high finding."""
    found: list[str] = []
    joined = re.sub(r"\s*\n\s*", " ", re.sub(r"\n\s*[-*]\s", "; ", text))  # bullets end a clause, wraps do not
    for clause in _CLAUSES.split(joined):
        if not clause.strip() or _DEFERRED.search(clause):
            continue
        found += [key for key in named_technologies(clause, catalog) if key not in found]
    return [key for key in named_technologies(text, catalog) if key in found]


def read_lines(path: Path) -> list[str]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def is_test(relative: str, stacks: dict[str, Any] | None = None) -> bool:
    """A test file by the stacks' ``tests`` folders and names (``engineering_knowledge/stacks.json``)."""
    return stack_data.is_test(relative, stacks)


@dataclass
class AppFiles:
    """The app folder's manifests, code and data files (read once per check)."""
    app: Path
    root: Path
    files: dict[str, list[str]] = field(default_factory=dict)  # relative path -> lines

    stacks: dict[str, Any] | None = None  # engineering_knowledge/stacks.py: manifests, suffixes, skipped folders

    @classmethod
    def read(cls, app: Path, root: Path, stacks: dict[str, Any] | None = None) -> AppFiles:
        found = cls(app, root, stacks=stacks)
        skipped, manifests = stack_data.skip_folders(stacks), stack_data.manifests(stacks)
        suffixes = stack_data.code_suffixes(stacks) | stack_data.data_suffixes(stacks)
        stack = [app]
        while stack and len(found.files) < MAX_FILES:
            folder = stack.pop()
            try:
                entries = sorted(folder.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in skipped and not entry.name.startswith("."):
                        stack.append(entry)
                elif entry.name in manifests or entry.suffix in suffixes:
                    found.files[entry.relative_to(root).as_posix()] = read_lines(entry)
        return found

    def code(self, *, data: bool = False) -> list[tuple[str, list[str]]]:
        suffixes = stack_data.code_suffixes(self.stacks)
        if data:
            suffixes |= stack_data.data_suffixes(self.stacks)
        manifests = stack_data.manifests(self.stacks)
        return [(path, lines) for path, lines in self.files.items()
                if Path(path).suffix in suffixes and Path(path).name not in manifests
                and not is_test(path, self.stacks)]


def _json_hits(lines: list[str], packages: list[str], keys: list[str]) -> list[int]:
    try:
        data = json.loads("\n".join(lines))
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    names = {name for key in keys for name in dict(data.get(key) or {})}
    wanted = {package for package in packages if package in names}
    return [index for index, line in enumerate(lines, 1)
            if any(re.search(rf'"{re.escape(package)}"\s*:', line) for package in wanted)]


def _manifest_hits(manifest: dict[str, Any], lines: list[str], packages: list[str]) -> list[int]:
    """The dependency lines of ``packages`` in a manifest of the stacks' ``format``: ``json_dependencies`` (its
    ``keys`` objects), ``lines`` (one dependency per line, ``comment`` cut off), ``module_lines`` (also a module path
    between spaces)."""
    if manifest.get("format") == "json_dependencies":
        return _json_hits(lines, packages, [str(key) for key in manifest.get("keys") or []])
    comment = str(manifest.get("comment") or "")
    hits = []
    for index, line in enumerate(lines, 1):
        stripped = line.split(comment, 1)[0] if comment else line
        for package in packages:
            escaped = re.escape(package)
            if re.match(rf"^\s*['\"]?{escaped}['\"]?\s*(:|=|==|>=|<=|~=|\^|$|\[)", stripped) \
                    or re.search(rf"['\"]{escaped}([<>=~! \[;,:'\"]|$)", stripped) \
                    or re.search(rf"<artifactId>{escaped}</artifactId>", stripped) \
                    or (manifest.get("format") == "module_lines" and re.search(rf"\s{escaped}\s", stripped)):
                hits.append(index)
                break
    return hits


def technology_evidence(files: AppFiles, entry: dict[str, Any]) -> tuple[list[str], list[str]]:
    """``(dependency lines, use lines in non-test code)`` of one catalog entry."""
    dependencies: list[str] = []
    manifests = stack_data.manifests(files.stacks)
    for path, lines in files.files.items():
        manifest = manifests.get(Path(path).name)
        if manifest is not None:
            dependencies += [f"{path}:{index} dependency: {lines[index - 1].strip()[:120]}"
                             for index in _manifest_hits(manifest, lines, list(entry.get("packages") or []))]
    pattern = re.compile(str(entry.get("uses") or r"(?!)"))
    uses: list[str] = []
    for path, lines in files.code():
        for index, line in enumerate(lines, 1):
            if pattern.search(line) and not line.lstrip().startswith(_COMMENT):
                uses.append(f"{path}:{index} use: {line.strip()[:120]}")
                break
    return dependencies, uses


# ---- literals -------------------------------------------------------------------------------------------------------

_REFERENCE = re.compile(r"\((?:Section|see|R\d|PO)[^)]*\)"
                        r"|\b(?:Section|Chapter)\s+[\d.]+|\bR\d{1,2}\b|\bUC\d{1,2}\b|\bLF\d{1,2}\b|\d+(?:[.,]\d+)?\s*[-–]\s*\d+(?:[.,]\d+)?",
                        re.IGNORECASE)  # references, and ranges (``25–30 s``: no single value)
_QUOTED = re.compile(r"[“\"']([^“\"'\n]{2,60})[”\"']")
_NUMBER = re.compile(r"(?<![\w.:/#–-])(\d{1,6}(?:[.,]\d{1,4})?)(?![\w:/]|\.\d|\s*[-–]\s*\d)")
_STOP = frozenset("""the a an and or for of to in on at by with without per as is are be
default standard standards value min max""".split())


@dataclass(frozen=True)
class Literal:
    value: str  # as the decision writes it
    number: bool
    terms: tuple[str, ...]  # the words just before it (the setting it is the value of)


def literals(text: str) -> list[Literal]:
    """The concrete values a decision states, each with the term before it (``Grind size default 15`` → 15,
    ("grind", "size")); references (``R9``, ``(Section 3)``) are no values."""
    clean = _REFERENCE.sub(" ", text)
    found: list[Literal] = []
    for clause in re.split(r"[;\n]|,\s(?=[A-Za-z])", clean):
        for match in [*_QUOTED.finditer(clause), *_NUMBER.finditer(clause)]:
            before = re.findall(r"[A-Za-z_][\w-]{3,}", clause[:match.start()])
            terms = tuple(word.lower() for word in before if word.lower() not in _STOP)[-2:]
            if terms:
                found.append(Literal(match.group(1).strip(), match.re is _NUMBER, terms))
    return found[:12]


def _squash(text: str) -> str:
    return re.sub(r"[\s_\-]", "", text.lower())


def _number_pattern(value: str) -> re.Pattern[str]:
    number = value.replace(",", ".")
    whole = number.split(".", 1)[0] if re.fullmatch(r"\d+(\.0+)?", number) else ""
    options = [re.escape(number)] + ([rf"{re.escape(whole)}(?:\.0+)?"] if whole else [])
    return re.compile(rf"(?<![\w.])(?:{'|'.join(options)})(?![\w])")


_ASSIGNED = re.compile(r"([A-Za-z_][\w]*)\s*(?::|=|\?\?|\|\|)\s*(-?\d+(?:\.\d+)?)\b")


def literal_evidence(files: AppFiles, literal: Literal) -> tuple[str, list[str]]:
    """``(state, evidence)``: ``found`` (the term and the literal within :data:`NEAR_LINES` lines), ``differs``
    (the term assigned another number), else ``unknown``."""
    value = _number_pattern(literal.value) if literal.number else re.compile(re.escape(literal.value), re.IGNORECASE)
    terms = [_squash(term) for term in literal.terms if len(_squash(term)) >= 4]
    differs: list[str] = []
    for path, lines in files.code(data=True):
        for index, line in enumerate(lines):
            if line.lstrip().startswith(_COMMENT) or not any(term in _squash(line) for term in terms):
                continue
            window = [item for item in lines[max(0, index - NEAR_LINES): index + NEAR_LINES + 1]
                      if not item.lstrip().startswith(_COMMENT)]
            if any(value.search(item) for item in window):
                return "found", [f"{path}:{index + 1} value: {line.strip()[:120]}"]
            # Another value only where the term names the setting itself (``grindSetting = 0.0``,
            # ``defaultGrindSetting: 0``), never a longer name that merely contains it.
            other = _ASSIGNED.search(line) if literal.number else None
            if other and any(_squash(other.group(1)).endswith(term) for term in terms):
                differs.append(f"{path}:{index + 1} other value {other.group(2)}: {line.strip()[:120]}")
    return ("differs", differs[:2]) if differs else ("unknown", [])


__all__ = ["AppFiles", "Literal", "decided_technologies", "is_test", "literal_evidence", "literals",
           "named_technologies", "read_lines", "technology_evidence"]
