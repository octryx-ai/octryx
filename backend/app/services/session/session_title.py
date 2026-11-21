"""Deterministic chat titles.

No model call: the first sentence of the first message, with leading greetings and filler removed,
the composer's attachment block, code and URLs dropped, sentence case, cut at a word boundary within
``TITLE_MAX_CHARS``. ``metadata.title_source`` records where a title came from: ``prompt`` (this rule)
or ``user`` (renamed). A user title is never overwritten.
"""

from __future__ import annotations

import re
from typing import Any

TITLE_MAX_CHARS = 60
TITLE_SOURCE_KEY = "title_source"
TITLE_SOURCE_PROMPT = "prompt"
TITLE_SOURCE_USER = "user"
TITLE_SOURCE_RUN = "run"
FALLBACK_TITLE = "New chat"

# The block the chat composer appends for attached workspace files (useMessageSend.ts).
_ATTACHMENT_BLOCK = re.compile(r"\n*Attached workspace files:.*\Z", re.DOTALL)
_CODE_FENCE = re.compile(r"```.*?(```|\Z)", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s|\n")
_LEADING_FILLER = re.compile(
    r"^(?:"
    r"(?:hi|hello|hey|good (?:morning|afternoon|evening))(?:\s+there)?(?:[\s,!.:-]+|$)"
    r"|(?:can|could|would|will) you(?: please)?(?: help me(?: to| with)?)?\s+"
    r"|please\s+"
    r"|i (?:need|want|would like) (?:you )?to\s+"
    r"|help me(?: to| with)?\s+"
    r")",
    re.IGNORECASE,
)


def _strip_filler(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _LEADING_FILLER.sub("", text).lstrip(" ,.:;-!")
    return text


def _cut_at_word(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit + 1]
    boundary = cut.rfind(" ")
    return (cut[:boundary] if boundary > limit // 2 else text[:limit]).rstrip(" ,.;:-")


def title_from_prompt(prompt: str) -> str:
    """The title of a chat whose first message is ``prompt``."""
    text = _ATTACHMENT_BLOCK.sub("", str(prompt or ""))
    text = _CODE_FENCE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _URL.sub(" ", text)
    candidates = [part.strip() for part in _SENTENCE_END.split(text)]
    for candidate in candidates:
        sentence = _strip_filler(re.sub(r"\s+", " ", candidate)).rstrip(" ?!.,;:")
        if re.search(r"\w", sentence):
            title = _cut_at_word(sentence, TITLE_MAX_CHARS)
            return title[0].upper() + title[1:]
    return FALLBACK_TITLE


def apply_prompt_title(metadata: dict[str, Any], prompt: str) -> None:
    """Sets the prompt title unless the chat already has a title (a user title is never replaced)."""
    if metadata.get("title"):
        return
    metadata["title"] = title_from_prompt(prompt)
    metadata[TITLE_SOURCE_KEY] = TITLE_SOURCE_PROMPT


def apply_run_title(metadata: dict[str, Any], title: str) -> None:
    """A workflow run's main thread is named after the run ("<work item key> <title>"); a user title stays."""
    clean = re.sub(r"\s+", " ", str(title or "")).strip()[:120]
    if not clean or metadata.get(TITLE_SOURCE_KEY) == TITLE_SOURCE_USER:
        return
    metadata["title"] = clean
    metadata[TITLE_SOURCE_KEY] = TITLE_SOURCE_RUN


def apply_user_title(metadata: dict[str, Any], title: str) -> bool:
    clean = re.sub(r"\s+", " ", str(title or "")).strip()[:120]
    if not clean:
        return False
    metadata["title"] = clean
    metadata[TITLE_SOURCE_KEY] = TITLE_SOURCE_USER
    return True


__all__ = [
    "FALLBACK_TITLE",
    "TITLE_MAX_CHARS",
    "TITLE_SOURCE_KEY",
    "apply_prompt_title",
    "apply_run_title",
    "apply_user_title",
    "title_from_prompt",
]
