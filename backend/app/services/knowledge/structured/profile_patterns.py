"""Which profile patterns the structured extractors may run, and the engine that runs them.

A Workspace can bring its own profile (``workspace_profile.py``), so its regular expressions run in
the shared knowledge worker over every manual, file and record of the Workspace. Python's ``re``
backtracks without a time limit (``(a|aa)*c`` on a long run of ``a`` never returns), so **no
profile pattern runs on ``re``**: every one, the instance default's too, runs on RE2
(``google-re2``), whose matching time is linear in the text. Each pattern:

- is at most :data:`MAX_PATTERN_CHARS` long and compiles as Python syntax;
- has no *ambiguous nested repeat* (the first line of defence): a repeated group
  (``*``, ``+``, ``{2,}``) whose body itself repeats something and has no mandatory single
  character of its own at its top level. ``(?: \\w+){3,}`` passes; ``(\\w+\\s?)*`` and ``(a+)+``
  are refused;
- compiles on RE2 (:class:`UnsupportedPatternError` otherwise: look-around, back-references,
  ``(?x)``, a program larger than RE2's memory budget), so a document that saves is one that runs.

Python semantics are kept where RE2 differs: ``\\w``, ``\\d``, ``\\s`` (and ``\\W``, ``\\D``, ``\\S``
outside a character class) are rewritten to their Unicode classes (RE2's are ASCII), ``\\Z`` to
``\\z``. ``\\b`` stays RE2's ASCII word boundary, and ``$`` without ``(?m)`` matches only at the very
end (Python also before a final newline). A negated class shorthand inside a class (``[^\\W]``) has
no Unicode form and is refused.

Every text a pattern sees is capped at :data:`MAX_MATCH_INPUT_CHARS` (the head of the text, so
offsets stay valid; ``sub`` leaves the tail as is, ``fullmatch`` of a longer text is no match).
The messages name the rule, never the pattern.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

import re2

try:  # Python 3.11+
    from re import _constants as _sre
    from re import _parser as _parse
except ImportError:  # pragma: no cover - older interpreters
    import sre_constants as _sre  # type: ignore[no-redef]
    import sre_parse as _parse  # type: ignore[no-redef]

MAX_PATTERN_CHARS = 300
MAX_MATCH_INPUT_CHARS = 200_000

_REPEATS = {_sre.MAX_REPEAT, _sre.MIN_REPEAT, *([_sre.POSSESSIVE_REPEAT] if hasattr(_sre, "POSSESSIVE_REPEAT") else [])}
_SINGLE = {_sre.LITERAL, _sre.NOT_LITERAL, _sre.IN, _sre.ANY, _sre.CATEGORY}

# Python's Unicode class shorthands as RE2 class bodies (``str.isspace``: \t-\r, \x1c-\x1f, \x85, Z*).
_WORD = r"\p{L}\p{N}_"
_DIGIT = r"\p{Nd}"
_SPACE = r"\t-\r\x1c-\x1f\x85\p{Z}"
_OUTSIDE = {
    "w": f"[{_WORD}]", "W": f"[^{_WORD}]", "d": _DIGIT, "D": r"\P{Nd}",
    "s": f"[{_SPACE}]", "S": f"[^{_SPACE}]", "Z": r"\z",
}
_INSIDE = {"w": _WORD, "d": _DIGIT, "D": r"\P{Nd}", "s": _SPACE}


class UnsafePatternError(ValueError):
    """The pattern is too long or could backtrack without bound."""


class UnsupportedPatternError(ValueError):
    """The pattern uses syntax the linear-time engine (RE2) does not run."""


def _options() -> re2.Options:
    options = re2.Options()
    options.log_errors = False
    return options


_RE2_OPTIONS = _options()


def _children(op, av) -> list:
    if op in _REPEATS:
        return [av[2]]
    if op == _sre.SUBPATTERN:
        return [av[-1]]
    if op == _sre.BRANCH:
        return list(av[1])
    if op in (_sre.ASSERT, _sre.ASSERT_NOT):
        return [av[1]]
    if op == getattr(_sre, "ATOMIC_GROUP", None):
        return [av]
    if op == _sre.GROUPREF_EXISTS:
        return [item for item in av[1:] if item is not None]
    return []


def _repeats_inside(items) -> bool:
    for op, av in items:
        if op in _REPEATS and av[1] > 1:
            return True
        if any(_repeats_inside(child) for child in _children(op, av)):
            return True
    return False


def _has_mandatory_single(items) -> bool:
    # A plain group is matched once per iteration, so a single character inside it is mandatory too.
    return any(op in _SINGLE or (op == _sre.SUBPATTERN and _has_mandatory_single(av[-1])) for op, av in items)


def _check(items) -> None:
    for op, av in items:
        if op in _REPEATS and av[1] > 1:
            body = av[2]
            if _repeats_inside(body) and not _has_mandatory_single(body):
                raise UnsafePatternError()
        for child in _children(op, av):
            _check(child)


def to_re2(pattern: str) -> str:
    """The pattern in RE2 syntax with Python's Unicode ``\\w``/``\\d``/``\\s``; :class:`UnsupportedPatternError`."""
    out: list[str] = []
    index, in_class = 0, False
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            letter = pattern[index + 1]
            table = _INSIDE if in_class else _OUTSIDE
            if letter in table:
                out.append(table[letter])
            elif in_class and letter in "WSZ":
                raise UnsupportedPatternError()
            else:
                out.append(pattern[index:index + 2])
            index += 2
            continue
        if not in_class and char == "[":
            in_class = True
            out.append(char)
            index += 1
            # A ``]`` right after ``[`` or ``[^`` is a literal member, not the end of the class.
            if pattern.startswith("^", index):
                out.append("^")
                index += 1
            if pattern.startswith("]", index):
                out.append("]")
                index += 1
            continue
        if in_class and char == "]":
            in_class = False
        out.append(char)
        index += 1
    return "".join(out)


def _capped(text: str) -> str:
    return text if len(text) <= MAX_MATCH_INPUT_CHARS else text[:MAX_MATCH_INPUT_CHARS]


class ProfileMatch:
    """One RE2 match with the ``re.Match`` calls the extractors use (group names work everywhere)."""

    __slots__ = ("_match", "_names")

    def __init__(self, match, names: dict[str, int]) -> None:
        self._match = match
        self._names = names

    def _index(self, group: int | str) -> int:
        if isinstance(group, str):
            if group not in self._names:
                raise IndexError("no such group")
            return self._names[group]
        return group

    def group(self, *groups: int | str):
        return self._match.group(*(self._index(group) for group in groups)) if groups else self._match.group()

    def __getitem__(self, group: int | str):
        return self._match.group(self._index(group))

    def groups(self, default=None) -> tuple:
        return self._match.groups(default)

    def groupdict(self, default=None) -> dict:
        return self._match.groupdict(default)

    def start(self, group: int | str = 0) -> int:
        return self._match.start(self._index(group))

    def end(self, group: int | str = 0) -> int:
        return self._match.end(self._index(group))

    def span(self, group: int | str = 0) -> tuple[int, int]:
        return self._match.span(self._index(group))


class ProfilePattern:
    """A checked profile pattern on RE2; every call sees at most :data:`MAX_MATCH_INPUT_CHARS`."""

    __slots__ = ("pattern", "groupindex", "_regexp")

    def __init__(self, pattern: str, regexp) -> None:
        self.pattern = pattern
        self._regexp = regexp
        self.groupindex: dict[str, int] = dict(regexp.groupindex)

    def __repr__(self) -> str:
        return f"ProfilePattern({self.pattern!r})"

    def _wrap(self, match) -> ProfileMatch | None:
        return None if match is None else ProfileMatch(match, self.groupindex)

    def search(self, text: str) -> ProfileMatch | None:
        return self._wrap(self._regexp.search(_capped(text)))

    def match(self, text: str) -> ProfileMatch | None:
        return self._wrap(self._regexp.match(_capped(text)))

    def fullmatch(self, text: str) -> ProfileMatch | None:
        if len(text) > MAX_MATCH_INPUT_CHARS:
            return None
        return self._wrap(self._regexp.fullmatch(text))

    def finditer(self, text: str) -> Iterator[ProfileMatch]:
        for match in self._regexp.finditer(_capped(text)):
            yield ProfileMatch(match, self.groupindex)

    def sub(self, repl: Callable[[ProfileMatch], str], text: str) -> str:
        head = self._regexp.sub(lambda match: repl(ProfileMatch(match, self.groupindex)), _capped(text))
        return head + text[MAX_MATCH_INPUT_CHARS:]


def check_pattern(pattern: str) -> ProfilePattern:
    """The pattern on RE2; :class:`UnsafePatternError`, :class:`UnsupportedPatternError`, ``re.error`` as is."""
    if len(pattern) > MAX_PATTERN_CHARS:
        raise UnsafePatternError()
    re.compile(pattern)
    _check(_parse.parse(pattern))
    try:
        regexp = re2.compile(to_re2(pattern), _RE2_OPTIONS)
    except re2.error:
        raise UnsupportedPatternError() from None
    return ProfilePattern(pattern, regexp)


__all__ = [
    "MAX_MATCH_INPUT_CHARS",
    "MAX_PATTERN_CHARS",
    "ProfileMatch",
    "ProfilePattern",
    "UnsafePatternError",
    "UnsupportedPatternError",
    "check_pattern",
    "to_re2",
]
