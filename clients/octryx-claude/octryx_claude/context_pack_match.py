"""Which symbols, routes and tests a Work item's text points at: fixed weights, a stable order, no model."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .context_pack_routes import Route
from .context_pack_structure import Structure

# A rare shared word weighs its inverse frequency among the app's names (about 8 for a word in one name in 5,000),
# a common one (tool, result, start) little; a name the item writes like code, its route or its path outweighs them.
EXACT, ROUTE, TITLE_WORD, TEXT_WORD = 40.0, 40.0, 2.0, 1.0
MIN_WORD = 4
MAX_SHARE = 0.25  # a word in more than a quarter of the names (test, data, get) tells nothing; no word list
MAX_SAME_NAME = 3  # a name defined more often is too ambiguous to follow its callers
MIN_SHARED_WORDS = 2
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CODE_LIKE = re.compile(r"_|[a-z][A-Z]|[A-Za-z]\d")
_ROUTE = re.compile(r"(?<![\w.])/[A-Za-z0-9_{}:\-./]*[A-Za-z][A-Za-z0-9_{}:\-./]*")
_PATH = re.compile(r"[\w.\-]+(?:/[\w.\-]+)*\.[A-Za-z]{1,5}\b")
_PARTS = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\b|\d)|[A-Z]?[a-z]+|\d+")
_TEST_MARKERS = ("/tests/", "/test/", "/__tests__/", "/spec/")
_TEST_NAME = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.|Test\.java$|_spec\.rb$)")


def words(text: str) -> list[str]:
    found = []
    for token in _IDENTIFIER.findall(text):
        found += [part.lower() for part in _PARTS.findall(token)]
    return [_stem(word) for word in found if len(word) >= MIN_WORD]


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > MIN_WORD else word


def is_test(name: str) -> bool:
    path = "/" + name
    return any(marker in path for marker in _TEST_MARKERS) or bool(_TEST_NAME.search(PurePosixPath(name).name))


def _route_pattern(path: str) -> re.Pattern[str]:
    parts = [r"[^/]+" if part.startswith(("{", ":", "<")) else re.escape(part) for part in path.strip("/").split("/")]
    return re.compile("^/?" + "/".join(parts) + "/?$")


@dataclass
class Terms:
    identifiers: set[str] = field(default_factory=set)
    routes: set[str] = field(default_factory=set)
    paths: set[str] = field(default_factory=set)
    title: set[str] = field(default_factory=set)
    text: set[str] = field(default_factory=set)


def terms(title: str, description: str, structure: Structure) -> Terms:
    names = Counter(word for _file, name, _first, _last in structure.definitions for word in set(words(name)))
    common = max(5, int(len(structure.definitions) * MAX_SHARE))
    both = f"{title}\n{description}"
    code = set(re.findall(r"`([^`]+)`", both))
    defined = {name for _file, name, _first, _last in structure.definitions}
    found = Terms()
    # In prose only a word written like code (snake_case, camelCase) names a symbol; in backticks any does.
    found.identifiers = {token for chunk in code for token in _IDENTIFIER.findall(chunk) if token in defined}
    found.identifiers |= {token for token in _IDENTIFIER.findall(both)
                          if token in defined and _CODE_LIKE.search(token)}
    found.routes = {item.rstrip(".,;:)") for item in _ROUTE.findall(both) if len(item) > 2}
    found.paths = {item for item in _PATH.findall(both) if "/" in item or item in {PurePosixPath(name).name
                                                                                   for name in structure.files}}
    found.title = {word for word in words(title) if names[word] <= common}
    found.text = {word for word in words(description) if names[word] <= common} - found.title
    return found


def word_score(named: set[str], found: Terms, frequency: Counter[str], total: int) -> float:
    shared = named & (found.title | found.text)
    if len(shared) < MIN_SHARED_WORDS:
        return 0.0
    weight = sum((TITLE_WORD if word in found.title else TEXT_WORD) * math.log((total + 1) / (frequency[word] + 1))
                 for word in shared)
    return weight * (0.5 + 0.5 * len(shared) / len(named))  # a name made of the item's words beats a long one


def score_definitions(structure: Structure, routes: list[Route], found: Terms) -> list[tuple[float, str, str, int]]:
    handlers = {(route[0], route[4]) for route in routes
                if any(_route_pattern(route[3]).match(asked) or asked.rstrip("/") == route[3].rstrip("/")
                       for asked in found.routes)}
    defined = Counter(name for _file, name, _first, _last in structure.definitions)
    frequency = Counter(word for name in defined for word in set(words(name)))
    scored = []
    for file, name, first, _last in structure.definitions:
        score = (EXACT if name in found.identifiers else 0) + (ROUTE if (file, name) in handlers else 0)
        # One shared word (stop, chat) or a name defined all over says nothing by its words alone.
        if defined[name] <= MAX_SAME_NAME:
            score += word_score(set(words(name)), found, frequency, len(defined))
        if score and not is_test(file):
            scored.append((-round(score, 3), file, name, first))
    return sorted(scored, key=lambda item: (item[0], len(item[1]), item[1], item[3]))


def enclosing(structure: Structure, file: str, line: int) -> str:
    inside = [(last - first, name) for name_file, name, first, last in structure.definitions
              if name_file == file and first <= line <= last]
    return min(inside)[1] if inside else ""


def callers(structure: Structure, file: str, name: str, limit: int) -> list[tuple[str, int, str]]:
    if sum(1 for _file, other, _first, _last in structure.definitions if other == name) > MAX_SAME_NAME:
        return []
    found = [(call_file, line, enclosing(structure, call_file, line)) for call_file, line, callee in structure.calls
             if callee == name and not is_test(call_file)]
    found = [item for item in found if not (item[0] == file and item[2] == name)]
    return sorted(found, key=lambda item: (item[0] != file, item[0], item[1]))[:limit]


def module_names(file: str) -> set[str]:
    stem = str(PurePosixPath(file).with_suffix(""))
    parts = stem.split("/")
    names = {"/".join(parts[index:]) for index in range(len(parts))} | {".".join(parts[index:])
                                                                       for index in range(len(parts))}
    return {name for name in names if len(name) >= MIN_WORD and name not in ("index", "__init__")}


def tests_for(structure: Structure, file: str, name: str) -> list[str]:
    modules = module_names(file)
    importing = {test for test, text in structure.imports if is_test(test) and any(
        re.search(rf"(?<![\w]){re.escape(module)}(?![\w])", text) for module in modules)}
    calling = {test for test, _line, callee in structure.calls if is_test(test) and callee == name}
    return sorted(importing | calling, key=lambda item: (item not in calling, len(item), item))


__all__ = ["Terms", "callers", "enclosing", "is_test", "module_names", "score_definitions", "terms", "tests_for",
           "word_score", "words"]
