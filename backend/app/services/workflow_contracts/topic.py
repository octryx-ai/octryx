"""Topic extraction: the subject a request names, read as a parameter (never a routing decision)."""

from __future__ import annotations

import re

_TOPIC_CAPTURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"['\"]([^'\"]{3,120})['\"]"),
    re.compile(
        r"\b(?:research|analyse|analysis|study|investigate)\b\s+(.+?)\s+\b(?:and\s+(?:create|build|draft|write|produce|generate)|covering)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:about|on)\b\s+(.+?)\s+(?:benefits?|risks?|use\s+cases?|adoption|governance|recommendations?|limitations?|rollout)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:about|on)\b\s+(.+?)"
        r"(?:\s+(?:with|using|including|and\s+use|and\s+(?:create|build|draft|write|produce|generate))\b"
        r"|[.!?]|$)",
        re.IGNORECASE,
    ),
    re.compile(r"about\s+['\"]([^'\"]{3,120})['\"]", re.IGNORECASE),
    re.compile(r"knowledge\s+about\s+([a-zA-Z0-9._/-]+)", re.IGNORECASE),
    re.compile(r"about\s+([a-zA-Z0-9._/-]+)", re.IGNORECASE),
    # Capture the whole "for" phrase up to a list marker or sentence end -
    # the single-token version titled "for the loan approval process" as
    # "the" (visible in rendered diagram titles, audit follow-up).
    re.compile(
        r"\bfor\s+(.+?)"
        # locative/qualifier prepositions end the topic: "for Octryx in
        # eu-central-1" is about Octryx, not about the region.
        r"(?:\s+(?:with|using|including|in|on|at)\b|[.!?]|$)",
        re.IGNORECASE,
    ),
)
_TOPIC_ARTIFACT_SUFFIX_PATTERN = re.compile(
    r"\s+(?:(?:and\s+)?(?:a|an|the))\s+"
    r"(?:presentation|powerpoint|pptx?|deck|slides?|"
    r"word|docx?|document|report|brief|briefing|whitepaper)\b.*$",
    re.IGNORECASE,
)
# A trailing save instruction is never part of the topic ("... and save it as reports/x.docx").
_TOPIC_SAVE_CLAUSE_PATTERN = re.compile(
    r"\s*,?\s+(?:and\s+)?(?:save|store)\b.*$", re.IGNORECASE
)
# A file path or name with an artifact extension is a parameter, not topic text.
_TOPIC_PATH_TOKEN_PATTERN = re.compile(r"\S+\.(?:pptx|potx|docx|xlsx|pdf|md|json|csv)\b", re.IGNORECASE)
_TOPIC_MAX_FALLBACK_CHARS = 200
_TOPIC_LEADING_PREPOSITION_PATTERN = re.compile(r"^(?:on|about)\s+", re.IGNORECASE)
_TOPIC_LEADING_ARTICLE_PATTERN = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
_TOPIC_STOPWORDS: set[str] = {
    "create",
    "write",
    "presentation",
    "powerpoint",
    "deck",
    "slides",
    "word",
    "document",
    "report",
    "knowledge",
    "integration",
    "llm",
    "research",
    "output",
    "folder",
}


# Words that never name a subject on their own (articles, prepositions, conjunctions).
_TOPIC_FILLER_WORDS = frozenset(
    {"the", "a", "an", "and", "or", "of", "for", "with", "about", "on", "to", "this", "that", "it"}
)


def _topic_has_content(topic: str) -> bool:
    return any(
        len(word) >= 3 and word.lower() not in _TOPIC_FILLER_WORDS
        for word in re.findall(r"[^\W\d_][\w.-]*", topic)
    )


def _without_parameters(text: str) -> str:
    cleaned = _TOPIC_SAVE_CLAUSE_PATTERN.sub("", text)
    cleaned = _TOPIC_PATH_TOKEN_PATTERN.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" .,:;!?")


def infer_topic_capture(user_message: str) -> str:
    text = _without_parameters(str(user_message or "").strip())
    for pattern in _TOPIC_CAPTURE_PATTERNS:
        match = pattern.search(text)
        if match:
            topic = str(match.group(1) or "").strip(" .,:;!?")
            if topic:
                normalized = re.sub(r"\s+", " ", topic)
                normalized = _TOPIC_ARTIFACT_SUFFIX_PATTERN.sub("", normalized).strip(" .,:;!?")
                normalized = _TOPIC_LEADING_PREPOSITION_PATTERN.sub("", normalized).strip(" .,:;!?")
                normalized = _TOPIC_LEADING_ARTICLE_PATTERN.sub("", normalized).strip(" .,:;!?")
                if normalized and _topic_has_content(normalized):
                    return normalized
    return ""


def infer_topic(user_message: str) -> str:
    captured = infer_topic_capture(user_message)
    if captured:
        return captured
    text = _without_parameters(str(user_message or "").strip())
    # The fallback needs a word beyond the request's own verbs and artifact nouns
    # ("Create a presentation." names no subject).
    if any(
        len(word) >= 3 and word.lower() not in _TOPIC_FILLER_WORDS and word.lower() not in _TOPIC_STOPWORDS
        for word in re.findall(r"[^\W\d_][\w.-]*", text)
    ):
        return text[:_TOPIC_MAX_FALLBACK_CHARS].rstrip()
    return "knowledge"


