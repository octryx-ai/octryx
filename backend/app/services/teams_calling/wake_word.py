"""Wake-word policy for Teams Calling."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_DEFAULT_WAKE_WORDS = ("hey octryx", "octryx")

# Minimum similarity ratio for fuzzy wake word matching (0.0 - 1.0).
# 0.55 catches common whisper mis-transcriptions like "beautiful worker" for "virtual worker"
_FUZZY_THRESHOLD = 0.55


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def parse_wake_words(raw: object) -> list[str]:
    """Parse wake-word config from a string or list."""
    if isinstance(raw, str):
        words = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, list):
        words = [str(item).strip() for item in raw]
    else:
        words = list(_DEFAULT_WAKE_WORDS)
    normalized = [_normalize_text(word) for word in words if _normalize_text(word)]
    return normalized or list(_DEFAULT_WAKE_WORDS)


def _fuzzy_find_wake_word(text: str, wake_word: str) -> tuple[int, int] | None:
    """Find a wake word in text using fuzzy matching.

    Returns (start, end) character positions of the best match, or None.
    Handles whisper mis-transcriptions like "beautiful worker" for "virtual worker".

    Uses a sliding window approach: for each possible n-gram window in the text
    (where n varies from ww_word_count to ww_word_count+1), compare to wake word.
    """
    words = text.split()
    ww_words = wake_word.split()
    ww_len = len(ww_words)

    if not words or not ww_words:
        return None

    best_ratio = 0.0
    best_start = 0
    best_end = 0

    # Try window sizes from ww_len to ww_len+1 (in case whisper splits differently)
    for window_size in range(max(1, ww_len), min(ww_len + 2, len(words) + 1)):
        for i in range(len(words) - window_size + 1):
            candidate = " ".join(words[i : i + window_size])
            # Compare candidate (with spaces) against wake_word (with or without spaces)
            ratio = SequenceMatcher(None, candidate, wake_word).ratio()
            # Also compare without spaces (handles "virtualworker" vs "virtual worker")
            ratio_nospace = SequenceMatcher(None, candidate.replace(" ", ""), wake_word.replace(" ", "")).ratio()
            best_local = max(ratio, ratio_nospace)

            if best_local > best_ratio:
                best_ratio = best_local
                # Calculate character positions in original text
                prefix = " ".join(words[:i])
                best_start = len(prefix) + (1 if i > 0 else 0)
                best_end = best_start + len(candidate)

    if best_ratio >= _FUZZY_THRESHOLD:
        return (best_start, best_end)
    return None


@dataclass(frozen=True)
class WakeWordDecision:
    should_respond: bool
    command_text: str
    matched_wake_word: str | None = None


@dataclass(frozen=True)
class WakeWordPolicy:
    require_wake_word: bool = True
    wake_words: tuple[str, ...] = _DEFAULT_WAKE_WORDS

    @classmethod
    def from_config(cls, config: dict) -> "WakeWordPolicy":
        raw_require = config.get("call_require_wake_word")
        if raw_require is None:
            require = True
        elif isinstance(raw_require, str):
            require = raw_require.strip().lower() not in {"0", "false", "no", "off"}
        else:
            require = bool(raw_require)
        return cls(
            require_wake_word=require,
            wake_words=tuple(parse_wake_words(config.get("call_wake_words"))),
        )

    def evaluate(self, text: str) -> WakeWordDecision:
        normalized_text = _normalize_text(text)
        if not self.require_wake_word:
            return WakeWordDecision(should_respond=True, command_text=text.strip())

        for wake_word in self.wake_words:
            # Try exact regex match first
            pattern = rf"(^|[^\w]){re.escape(wake_word)}([,.:;!?]|\s|$)"
            match = re.search(pattern, normalized_text)
            if match:
                command_text = text[match.end() :].lstrip(" ,.:;!?")
                return WakeWordDecision(
                    should_respond=True,
                    command_text=command_text or text.strip(),
                    matched_wake_word=wake_word,
                )

            # Fuzzy match for whisper mis-transcriptions
            fuzzy_match = _fuzzy_find_wake_word(normalized_text, wake_word)
            if fuzzy_match:
                _, end_pos = fuzzy_match
                # Extract command text after the wake word match
                command_text = text[end_pos:].lstrip(" ,.:;!?")
                return WakeWordDecision(
                    should_respond=True,
                    command_text=command_text or text.strip(),
                    matched_wake_word=wake_word,
                )

        return WakeWordDecision(should_respond=False, command_text=text.strip())
