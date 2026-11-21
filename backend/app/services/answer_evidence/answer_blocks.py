"""The statement blocks of a markdown answer: what the answer evidence guard requires a citation on.

The answer is split by its markdown structure only:

- every list item (with its continuation lines) is one block; every table data row is one block;
- every other run of non-blank lines is a paragraph block;
- headings, horizontal rules, table header and separator rows, and fenced code are not blocks.

A block is a *statement* when it has at least :data:`MIN_STATEMENT_WORDS` words of visible text
and does not end with ``:`` (it introduces what follows) or ``?`` (it asks). A statement must
carry a source link. The meaning of the text is never read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MIN_STATEMENT_WORDS = 6

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")
_TABLE_ROW = re.compile(r"^\s*\|")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_QUOTE = re.compile(r"^\s{0,3}(>\s?)+")
_LINK = re.compile(r"\[([^\[\]\n]*)\]\([^()\s]*\)")
_URL = re.compile(r"https?://\S+")
_WORD = re.compile(r"[^\W_]+(?:[-'.][^\W_]+)*")


@dataclass(frozen=True, slots=True)
class AnswerBlock:
    """One block and where it sits: ``last_line`` is the index of its last line in the answer's lines."""

    text: str
    last_line: int
    kind: str  # "paragraph" | "item" | "row"


def answer_block_spans(text: str) -> list[AnswerBlock]:
    """The answer's blocks in order, with their position and kind (see the module docstring for the split)."""
    lines = str(text or "").splitlines()
    blocks: list[AnswerBlock] = []
    current: list[str] = []
    state = {"kind": "paragraph", "last": -1}
    in_fence = False

    def flush() -> None:
        if current:
            blocks.append(AnswerBlock("\n".join(current), state["last"], state["kind"]))
            current.clear()

    for index, raw in enumerate(lines):
        if _FENCE.match(raw):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = _QUOTE.sub("", raw)
        if not line.strip() or _HEADING.match(line) or _RULE.match(line) or _TABLE_SEPARATOR.match(line):
            flush()
            continue
        if _TABLE_ROW.match(line):
            flush()
            following = lines[index + 1] if index + 1 < len(lines) else ""
            if not _TABLE_SEPARATOR.match(_QUOTE.sub("", following)):
                blocks.append(AnswerBlock(line, index, "row"))
            continue
        if _LIST_ITEM.match(line):
            flush()
            state["kind"] = "item"
        elif not current:
            state["kind"] = "paragraph"
        current.append(line)
        state["last"] = index
    flush()
    return blocks


def answer_blocks(text: str) -> list[str]:
    """The answer's blocks in order (see the module docstring for the split)."""
    return [block.text for block in answer_block_spans(text)]


def answer_text_outside_code(text: str) -> str:
    """The answer without fenced code: the text whose links count."""
    kept: list[str] = []
    in_fence = False
    for line in str(text or "").splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(line)
    return "\n".join(kept)


def _visible_text(block: str) -> str:
    return _URL.sub(" ", _LINK.sub(r"\1", block))


def asks_or_introduces(block: str) -> bool:
    """A block ending with ``?`` (a question back) or ``:`` (it introduces what follows), or without text."""
    tail = _visible_text(block).strip().rstrip("*_` ").strip()
    return not tail or tail.endswith((":", "?"))


def is_statement(block: str) -> bool:
    if asks_or_introduces(block):
        return False
    return len(_WORD.findall(_visible_text(block))) >= MIN_STATEMENT_WORDS


def has_words(text: str) -> bool:
    return bool(_WORD.search(_visible_text(text)))


__all__ = [
    "MIN_STATEMENT_WORDS",
    "AnswerBlock",
    "answer_block_spans",
    "answer_blocks",
    "answer_text_outside_code",
    "asks_or_introduces",
    "has_words",
    "is_statement",
]
