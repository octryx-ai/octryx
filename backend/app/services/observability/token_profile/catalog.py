"""The token profile's data: categories, the characters per token and the savings rules (``token_rules.json``).

Rules and thresholds are data, not code: the engine (``rules``) only computes facts and
evaluates a rule's ``match``/``when`` against them; a new rule or another threshold is a change to the JSON.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_PATH = Path(__file__).with_name("token_rules.json")


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    return json.loads(_PATH.read_text(encoding="utf-8"))


def chars_per_token() -> int:
    return int(catalog().get("chars_per_token") or 4)


def tokens_of(chars: int) -> int:
    """An estimate of the tokens of ``chars`` characters of text (the API does not count a tool result alone)."""
    return (max(chars, 0) + chars_per_token() - 1) // chars_per_token()


def categories() -> list[dict[str, str]]:
    return list(catalog().get("categories") or [])


def status_tools() -> frozenset[str]:
    return frozenset(catalog().get("status_tools") or [])


def rules() -> list[dict[str, Any]]:
    return list(catalog().get("rules") or [])


__all__ = ["catalog", "categories", "chars_per_token", "rules", "status_tools", "tokens_of"]
