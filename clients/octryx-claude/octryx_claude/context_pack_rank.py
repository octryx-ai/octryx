"""The pack's ranking: symbols by the item's words, the files the item names, the files its matching tests import;
anything below a score floor is left out rather than filling the cap."""

from __future__ import annotations

import fnmatch
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .context_pack_match import (
    EXACT,
    MAX_SAME_NAME,
    Terms,
    is_test,
    module_names,
    score_definitions,
    terms,
    word_score,
    words,
)
from .context_pack_routes import Route
from .context_pack_structure import Structure

FLOOR = 1.2  # times log(names): about one rare title word in a name; two common ones stay below
RELATIVE = 0.35  # and at least this share of the best entry
NAMED = 30.0  # a file the item names (a teamwork item's paths, a red test, a review finding)
TEST_SHARE = 0.6  # a file imported by a test whose name matches the item gets this share of the test's score
MAX_PATHS = 30
# Without a name, route or path the item names, the pack is sent only when its words find at least this many names
# above the floor: in the measurement the packs that held the target file had 16-72 such names, the misses 3 and 8.
MIN_MATCHES = 10
BOOST_CAP = 0.5
_IMPORTED = re.compile(r"[\w@][\w./@-]*")


@dataclass
class Ranking:
    symbols: list[tuple[float, str, str, int]] = field(default_factory=list)
    files: list[tuple[float, str, str]] = field(default_factory=list)  # score, file, why
    tests: list[str] = field(default_factory=list)
    confident: bool = False


def _named(file: str, patterns: list[str]) -> bool:
    return any(file == item or file.endswith("/" + item) or fnmatch.fnmatch(file, item)
               or fnmatch.fnmatch(file, "*/" + item) for item in patterns)


def floor_of(structure: Structure) -> float:
    return FLOOR * math.log(len({name for _file, name, _first, _last in structure.definitions}) + 1)


def _test_scores(structure: Structure, found: Terms) -> dict[str, float]:
    defined = Counter(name for _file, name, _first, _last in structure.definitions)
    frequency = Counter(word for name in defined for word in set(words(name)))
    scores: dict[str, float] = {}
    for file, name, _first, _last in structure.definitions:
        if is_test(file) and defined[name] <= MAX_SAME_NAME:
            score = word_score(set(words(name)), found, frequency, len(defined))
            scores[file] = max(scores.get(file, 0.0), score)
    return {file: score for file, score in scores.items() if score >= floor_of(structure)}


def _imported(structure: Structure, tests: dict[str, float]) -> dict[str, float]:
    modules: dict[str, set[str]] = {}
    for file in structure.files:
        if not is_test(file):
            for name in module_names(file):
                modules.setdefault(name, set()).add(file)
    boost: dict[str, float] = {}
    for test, text in structure.imports:
        if test not in tests:
            continue
        for token in _IMPORTED.findall(text):
            for file in modules.get(token.strip("./").removeprefix("@/"), ()):
                boost[file] = max(boost.get(file, 0.0), TEST_SHARE * tests[test])
    return boost


# A name the item writes like code, or its route, is kept whatever the rest scores; the words-only rest is cut
# relative to its own best.
def _kept(scores: list[float], floor: float) -> float:
    by_words = [score for score in scores if score < EXACT]
    return max(floor, RELATIVE * max(by_words)) if by_words else floor


def rank(structure: Structure, routes: list[Route], item: dict[str, Any], limits: dict[str, int]) -> Ranking:
    found = terms(str(item.get("title") or ""), str(item.get("description") or ""), structure)
    patterns = [str(path).strip("/") for path in item.get("paths") or [] if str(path).strip("/")][:MAX_PATHS]
    patterns += sorted(found.paths)
    tests = _test_scores(structure, found)
    boost = _imported(structure, tests)
    raw = score_definitions(structure, routes, found)
    matched = {file for _score, file, _name, _line in raw}
    # A matching test lifts what its files define at most by BOOST_CAP of the symbol's own score (a long test name
    # shares many words), and lists only files that also define a matching name.
    boost = {file: score for file, score in boost.items() if file in matched}
    symbols = [(-score + min(boost.get(file, 0.0), -score * BOOST_CAP) + (NAMED / 3 if _named(file, patterns) else 0.0),
                file, name, line) for score, file, name, line in raw]
    floor = _kept([score for score, *_rest in symbols], floor_of(structure))
    symbols = sorted([entry for entry in symbols if entry[0] >= floor],
                     key=lambda entry: (-entry[0], len(entry[1]), entry[1], entry[3]))[:limits["symbols"]]
    files: dict[str, tuple[float, str]] = {}
    for score, file, _name, _line in symbols:
        files[file] = max(files.get(file, (0.0, "")), (score, ""))
    for file, score in boost.items():
        files[file] = (max(files.get(file, (0.0, ""))[0], score), "its tests match the item")
    for file in structure.files:
        if _named(file, patterns):
            files[file] = (files.get(file, (0.0, ""))[0] + NAMED, "named by the item")
    floor = _kept([score for score, _why in files.values()], floor_of(structure))
    ranked_files = sorted(((score, file, why) for file, (score, why) in files.items()
                           if score >= floor or why == "named by the item"), key=lambda entry: (-entry[0], entry[1]))
    ranking = Ranking(symbols, ranked_files[:limits["files"]])
    named = bool(found.identifiers) or any(-score >= EXACT for score, *_rest in raw) or any(
        why == "named by the item" for _score, _file, why in ranked_files)
    ranking.confident = named or sum(1 for score, *_rest in raw if -score >= floor_of(structure)) >= MIN_MATCHES
    ranking.tests = [test for test, _score in sorted(tests.items(), key=lambda entry: (-entry[1], entry[0]))]
    return ranking


__all__ = ["Ranking", "rank"]
