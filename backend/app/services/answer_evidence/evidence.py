"""The evidence a turn's tool results carry, as the answer evidence guard reads it."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..knowledge.retrieval.locator import markdown_citation
from .urls import link_target, normalize_url, unique, urls_in_text

_MAX_DEPTH = 8


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    url: str
    cite_as: str


@dataclass(frozen=True, slots=True)
class TurnEvidence:
    linkable: tuple[EvidenceSource, ...] = ()
    plain_labels: tuple[str, ...] = ()
    result_urls: frozenset[str] = field(default_factory=frozenset)
    executed_writes: tuple[str, ...] = ()

    @property
    def evidence_bearing(self) -> bool:
        return bool(self.linkable)

    @property
    def evidence_urls(self) -> frozenset[str]:
        return frozenset(source.url for source in self.linkable)


def _source_of(item: Mapping[str, Any]) -> tuple[EvidenceSource | None, str | None]:
    cite_as = item.get("cite_as")
    url = normalize_url(item.get("source_url")) or link_target(cite_as)
    if url is not None:
        if isinstance(cite_as, str) and link_target(cite_as):
            return EvidenceSource(url=url, cite_as=cite_as.strip()), None
        title = str(item.get("source_title") or item.get("title") or "").strip() or url
        return EvidenceSource(url=url, cite_as=markdown_citation(title, str(item.get("source_url")), ())), None
    if isinstance(cite_as, str) and cite_as.strip():
        return None, cite_as.strip()
    return None, None


def _walk(value: Any, depth: int, sources: list[EvidenceSource], labels: list[str], urls: list[str]) -> None:
    if depth > _MAX_DEPTH:
        return
    if isinstance(value, str):
        urls.extend(urls_in_text(value))
    elif isinstance(value, Mapping):
        if "source_url" in value or "cite_as" in value:
            source, label = _source_of(value)
            if source is not None:
                sources.append(source)
            if label is not None:
                labels.append(label)
        for item in value.values():
            _walk(item, depth + 1, sources, labels, urls)
    elif isinstance(value, list | tuple):
        for item in value:
            _walk(item, depth + 1, sources, labels, urls)


def _successful_result(entry: object) -> Mapping[str, Any] | None:
    if not isinstance(entry, Mapping):
        return None
    result = entry.get("result")
    if not isinstance(result, Mapping) or result.get("error"):
        return None
    return result


_WRITE_RISKS = frozenset({"write", "admin"})


def _is_write_tool(tool_name: str) -> bool:
    from ...tools.definitions import get_tool_definition_metadata

    name = str(tool_name or "").strip()
    return bool(name) and get_tool_definition_metadata(name).risk in _WRITE_RISKS


def collect_turn_evidence(turn_tool_history: Iterable[object] | None) -> TurnEvidence:
    sources: list[EvidenceSource] = []
    labels: list[str] = []
    urls: list[str] = []
    writes: list[str] = []
    for entry in turn_tool_history or ():
        result = _successful_result(entry)
        if result is not None:
            _walk(result, 0, sources, labels, urls)
            tool_name = str(entry.get("tool_name") or "")
            if _is_write_tool(tool_name):
                writes.append(tool_name)
    # One entry per citation (two sections of one page stay two sources); the URL set is per page.
    by_citation: dict[str, EvidenceSource] = {}
    for source in sources:
        by_citation.setdefault(source.cite_as, source)
    return TurnEvidence(
        linkable=tuple(by_citation.values()),
        plain_labels=tuple(unique(labels)),
        result_urls=frozenset([*urls, *(source.url for source in sources)]),
        executed_writes=tuple(unique(writes)),
    )


__all__ = ["EvidenceSource", "TurnEvidence", "collect_turn_evidence"]
