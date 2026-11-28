from __future__ import annotations

from tests.guards._support import Accepted


def within(path: str, definition: str, *lines: str | tuple[str, int]) -> tuple[str, ...]:
    # A count stands after a tab, which a normalized source line never holds (``test_legacy_words.counted_words``).
    keys = []
    for line in lines:
        text, count = line if isinstance(line, tuple) else (line, 1)
        key = f"{path} [{definition}]: {text}"
        keys.append(key if count == 1 else f"{key}\t(x{count})")
    return tuple(keys)


def concept(reason: str, *keys: str) -> tuple[Accepted, ...]:
    return tuple(Accepted(key, reason) for key in keys)
