"""The platform's pinned, offline blocklist for every web search result (search control plane).

It ships with the image as ``blocklist_v1.json`` and is never fetched at runtime, so what is blocked
is reviewable in the repository and cannot change underneath a running platform. Each category
blocks by:

- top-level domain (``.xxx``);
- a listed registrable domain and all its subdomains;
- a host substring (``porn`` anywhere in the host), for names that have no legitimate reading;
- a host token: a whole label part between dots and hyphens (``sex`` in ``free-sex.example``, but
  not in ``essex.ac.uk``).

This is the floor that holds even for an open search. It is not exhaustive and does not try to
be: knowledge research only uses trusted sources, and admins block further sources in the
registry (``registry.py``), which every search applies on top.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

_DATA = Path(__file__).with_name("blocklist_v1.json")
_TOKEN_SPLIT = re.compile(r"[.\-]")


@dataclass(frozen=True, slots=True)
class _Category:
    name: str
    tlds: frozenset[str]
    host_substrings: tuple[str, ...]
    host_tokens: frozenset[str]
    domains: frozenset[str]


@dataclass(frozen=True, slots=True)
class Blocklist:
    version: str
    categories: tuple[_Category, ...]

    def category_of(self, url: str) -> str | None:
        """The blocking category of ``url``'s host, or ``None`` when it is not blocked."""
        host = (urlsplit(url).hostname or "").strip(".").lower()
        if not host:
            return "invalid"
        labels = host.split(".")
        suffixes = {".".join(labels[index:]) for index in range(len(labels))}
        tokens = set(_TOKEN_SPLIT.split(host))
        for category in self.categories:
            if (
                labels[-1] in category.tlds
                or suffixes & category.domains
                or tokens & category.host_tokens
                or any(part in host for part in category.host_substrings)
            ):
                return category.name
        return None


@lru_cache(maxsize=1)
def platform_blocklist() -> Blocklist:
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    categories = tuple(
        _Category(
            name=name,
            tlds=frozenset(item["tlds"]),
            host_substrings=tuple(item["host_substrings"]),
            host_tokens=frozenset(item["host_tokens"]),
            domains=frozenset(item["domains"]),
        )
        for name, item in sorted(raw["categories"].items())
    )
    return Blocklist(version=raw["version"], categories=categories)


__all__ = ["Blocklist", "platform_blocklist"]
