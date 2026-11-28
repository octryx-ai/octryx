"""Golden sets for retrieval evaluation. A hit is correct only when it cites the expected source and contains the
expected passage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden"


@dataclass(frozen=True, slots=True)
class GoldenSource:
    key: str
    file: str
    title: str
    url: str
    products: str
    version: str | None


@dataclass(frozen=True, slots=True)
class GoldenQuery:
    id: str
    lang: str
    question: str
    source: str
    passage: str
    products: tuple[str, ...] = ()
    version: str | None = None


@dataclass(frozen=True, slots=True)
class GoldenSet:
    corpus: str
    sources: dict[str, GoldenSource]
    queries: tuple[GoldenQuery, ...]


def load_golden_set(name: str) -> GoldenSet:
    raw = json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))
    sources = {
        key: GoldenSource(
            key=key,
            file=value["file"],
            title=value["title"],
            url=value["url"],
            products=value["products"],
            version=value.get("version"),
        )
        for key, value in raw["sources"].items()
    }
    queries = tuple(
        GoldenQuery(
            id=item["id"],
            lang=item["lang"],
            question=item["question"],
            source=item["source"],
            passage=item["passage"],
            products=tuple(item.get("products") or ()),
            version=item.get("version"),
        )
        for item in raw["queries"]
    )
    if len({query.id for query in queries}) != len(queries):
        raise ValueError("duplicate golden query id")
    unknown = sorted({query.source for query in queries} - set(sources))
    if unknown:
        raise ValueError(f"golden queries name undeclared sources: {unknown}")
    return GoldenSet(corpus=raw["corpus"], sources=sources, queries=queries)


__all__ = ["GOLDEN_DIR", "GoldenQuery", "GoldenSet", "GoldenSource", "load_golden_set"]
