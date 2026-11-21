"""The literal ``tools.<name>(...)`` calls of one Codex ``exec`` input (a small JavaScript literal reader).

Only string, number, boolean and null literals and objects/arrays of them count; anything else (a variable, an
interpolation, a computed key, a spread) makes the call non-literal, so it can never earn evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# The recorder's mask for a secret-looking span (``transcript.bounded_tool_input``).
REDACTED_MARK = "[redacted]"


class _DynamicError(Exception):
    """An argument that is not a literal."""


@dataclass(frozen=True, slots=True)
class ExecOccurrence:
    """One ``tools.<name>(...)`` inside an exec input; ``args`` is ``None`` when they are not literal."""

    name: str
    args: Any
    literal: bool


_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_NUMBER = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_CALL = re.compile(r"tools\s*\.\s*([A-Za-z_$][\w$]*)\s*\(")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


class _Parser:
    def __init__(self, text: str, constants: dict[str, Any] | None = None) -> None:
        self.text = text
        self.pos = 0
        self.constants = constants or {}  # ``const NAME = <literal>`` declared before this point (still literal)

    def _peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def skip(self) -> None:
        text = self.text
        while self.pos < len(text):
            if text[self.pos].isspace():
                self.pos += 1
            elif text.startswith("//", self.pos):
                end = text.find("\n", self.pos)
                self.pos = len(text) if end < 0 else end + 1
            elif text.startswith("/*", self.pos):
                end = text.find("*/", self.pos + 2)
                self.pos = len(text) if end < 0 else end + 2
            else:
                return

    def string(self) -> str:
        """A ``"…"``/``'…'`` literal or a template literal without ``${}``; raises ``_DynamicError`` otherwise."""
        quote = self._peek()
        self.pos += 1
        out: list[str] = []
        text = self.text
        while self.pos < len(text):
            char = text[self.pos]
            if char == quote:
                self.pos += 1
                return "".join(out)
            if quote == "`" and text.startswith("${", self.pos):
                raise _DynamicError
            if char in "\r\n" and quote != "`":
                raise _DynamicError
            if char == "\\":
                out.append(self._escape())
                continue
            out.append(char)
            self.pos += 1
        raise _DynamicError  # unterminated (a truncated input)

    def _escape(self) -> str:
        text = self.text
        self.pos += 1
        char = text[self.pos] if self.pos < len(text) else ""
        self.pos += 1
        if char in _ESCAPES and not (char == "0" and self._peek().isdigit()):
            return _ESCAPES[char]
        if char == "x":
            digits = text[self.pos:self.pos + 2]
            self.pos += 2
            return chr(int(digits, 16)) if re.fullmatch(r"[0-9a-fA-F]{2}", digits) else _raise()
        if char == "u":
            if self._peek() == "{":
                end = text.find("}", self.pos)
                digits = text[self.pos + 1:end] if end > 0 else ""
                self.pos = end + 1
                return chr(int(digits, 16)) if re.fullmatch(r"[0-9a-fA-F]{1,6}", digits) else _raise()
            digits = text[self.pos:self.pos + 4]
            self.pos += 4
            return chr(int(digits, 16)) if re.fullmatch(r"[0-9a-fA-F]{4}", digits) else _raise()
        if char == "\r" and self._peek() == "\n":
            self.pos += 1
            return ""
        if char in "\n\r  ":
            return ""  # a line continuation
        if not char:
            raise _DynamicError
        return char

    def value(self) -> Any:
        self.skip()
        char = self._peek()
        if char in "\"'`":
            return self.string()
        if char == "{":
            return self._object()
        if self.text.startswith(REDACTED_MARK, self.pos):
            # The recorder masked a secret-looking span here (``transcript.bounded_tool_input``): Codex's
            # ``max_output_tokens:20000`` can be stored as ``max_output_tokens:[redacted]``, and without this every
            # exec_command would lose its evidence. The mark stands for itself: an argument the matching compares (a
            # command, a path, an MCP argument) never equals it, so it can never make a call count that did not run.
            self.pos += len(REDACTED_MARK)
            return REDACTED_MARK
        if char == "[":
            return self._array()
        number = _NUMBER.match(self.text, self.pos)
        if number:
            self.pos = number.end()
            raw = number.group(0)
            return float(raw) if any(mark in raw for mark in ".eE") else int(raw)
        word = _IDENT.match(self.text, self.pos)
        if word and word.group(0) in ("true", "false", "null"):
            self.pos = word.end()
            return {"true": True, "false": False, "null": None}[word.group(0)]
        if word and word.group(0) in self.constants and not re.match(r"\s*[.\[(]", self.text[word.end():]):
            # A ``const`` bound to a literal earlier in the script (Codex builds its patch as
            # ``const patch = "*** Begin Patch…"`` and calls ``tools.apply_patch(patch)``): the value is still literal.
            self.pos = word.end()
            return self.constants[word.group(0)]
        raise _DynamicError  # a variable, a call, a spread, an expression

    def _object(self) -> dict[str, Any]:
        self.pos += 1
        out: dict[str, Any] = {}
        while True:
            self.skip()
            char = self._peek()
            if char == "}":
                self.pos += 1
                return out
            if char in "\"'":
                key = self.string()
            elif (word := _IDENT.match(self.text, self.pos)) is not None:
                key = word.group(0)
                self.pos = word.end()
            else:
                raise _DynamicError  # a computed key, a spread
            self.skip()
            if self._peek() != ":":
                raise _DynamicError  # a shorthand property: a variable
            self.pos += 1
            out[key] = self.value()
            self.skip()
            if self._peek() == ",":
                self.pos += 1
            elif self._peek() != "}":
                raise _DynamicError

    def _array(self) -> list[Any]:
        self.pos += 1
        out: list[Any] = []
        while True:
            self.skip()
            if self._peek() == "]":
                self.pos += 1
                return out
            out.append(self.value())
            self.skip()
            if self._peek() == ",":
                self.pos += 1
            elif self._peek() != "]":
                raise _DynamicError

    def arguments(self) -> Any:
        """The single literal argument after ``(`` up to ``)`` (none: ``{}``)."""
        self.skip()
        if self._peek() == ")":
            self.pos += 1
            return {}
        value = self.value()
        self.skip()
        if self._peek() == ",":  # a trailing comma only
            self.pos += 1
            self.skip()
        if self._peek() != ")":
            raise _DynamicError
        self.pos += 1
        return value


def _raise() -> str:
    raise _DynamicError


def _code_positions(text: str, word: str = "tools") -> list[int]:
    """Where ``word`` (``tools.`` by default) starts in code (not inside a string, template or comment, not a member
    like ``x.tools.``)."""
    found: list[int] = []
    pos, size = 0, len(text)
    while pos < size:
        char = text[pos]
        if char in "\"'`":
            parser = _Parser(text)
            parser.pos = pos
            try:
                parser.string()
                pos = parser.pos
            except _DynamicError:
                pos = _skip_template(text, pos) if char == "`" else size
            continue
        if text.startswith("//", pos):
            end = text.find("\n", pos)
            pos = size if end < 0 else end + 1
            continue
        if text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            pos = size if end < 0 else end + 2
            continue
        if text.startswith(word, pos) and (pos == 0 or not re.match(r"[\w$.]", text[pos - 1])) and not re.match(
                r"[\w$]", text[pos + len(word):pos + len(word) + 1]):
            found.append(pos)
            pos += len(word)
            continue
        pos += 1
    return found


def _skip_template(text: str, start: int) -> int:
    """The end of a template literal with ``${}`` parts; its expressions are scanned as code by the caller's
    next round only through this simple skip (calls inside ``${}`` are dynamic anyway)."""
    end = text.find("`", start + 1)
    while end > 0 and text[end - 1] == "\\":
        end = text.find("`", end + 1)
    return len(text) if end < 0 else end + 1


_CONST = re.compile(r"const\s+([A-Za-z_$][\w$]*)\s*=")


def _constants(script: str) -> list[tuple[int, str, Any]]:
    """``(position, name, value)`` of each ``const NAME = <literal>`` in code; a name declared twice is left out
    (another scope could mean another value)."""
    found: list[tuple[int, str, Any]] = []
    for start in _code_positions(script, "const"):
        declared = _CONST.match(script, start)
        if declared is None:
            continue
        parser = _Parser(script)
        parser.pos = declared.end()
        try:
            value = parser.value()
        except (_DynamicError, ValueError, IndexError):
            continue
        rest = script[parser.pos:]
        following = rest.lstrip(" \t")
        if following and following[0] not in ";\r\n":
            continue  # ``const x = "a" + y``: not one literal
        found.append((start, declared.group(1), value))
    names = [name for _, name, _ in found]
    return [item for item in found if names.count(item[1]) == 1]


def exec_occurrences(script: str) -> list[ExecOccurrence]:
    """Every ``tools.<name>(...)`` call in an exec input, in order, with its literal argument or ``None``; an
    argument may name a ``const`` bound to a literal before the call."""
    found: list[ExecOccurrence] = []
    constants = _constants(script)
    for start in _code_positions(script):
        call = _CALL.match(script, start)
        if call is None:
            continue
        parser = _Parser(script, {name: value for pos, name, value in constants if pos < start})
        parser.pos = call.end()
        try:
            found.append(ExecOccurrence(call.group(1), parser.arguments(), True))
        except (_DynamicError, ValueError, IndexError):
            found.append(ExecOccurrence(call.group(1), None, False))
    return found


__all__ = ["REDACTED_MARK", "ExecOccurrence", "exec_occurrences"]
