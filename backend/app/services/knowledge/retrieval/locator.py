"""Render where a cited span sits in its document, for the API and the agent tools."""

from __future__ import annotations

from .evidence import CitedEvidence

SECTION_SEPARATOR = " > "


def evidence_locator(item: CitedEvidence) -> dict[str, object]:
    """``kind``, ``pages``, ``lines`` and ``section`` of a span; null for text-native spans."""
    pages = None
    if item.page_start is not None:
        pages = [item.page_start, item.page_end if item.page_end is not None else item.page_start]
    lines = [item.line_start, item.line_end] if item.line_start is not None else None
    return {
        "cite_as": markdown_citation(item.source_title, item.source_url, item.section_path, line_range(item)),
        "kind": item.kind,
        "pages": pages,
        "lines": lines,
        "section": SECTION_SEPARATOR.join(item.section_path) if item.section_path else None,
    }


def line_range(citation: object) -> tuple[int, int] | None:
    """``(line_start, line_end)`` of a code span (``line_end`` defaults to ``line_start``), else ``None``."""
    start, end = getattr(citation, "line_start", None), getattr(citation, "line_end", None)
    if type(start) is not int:
        return None
    return start, end if type(end) is int else start


def markdown_citation(
    title: str, url: str | None, section_path: tuple[str, ...], lines: tuple[int, int] | None = None
) -> str:
    """The citation as the reader should see it: ``[Title § Section](url)``, or plain without a link.

    A code span names its lines: ``[<repository>:<path> L<from>-<to>](url)`` (``L<n>`` for one).
    """
    label = f"{title} § {section_path[-1]}" if section_path else title
    if lines is not None:
        label = f"{label} L{lines[0]}" if lines[0] == lines[1] else f"{label} L{lines[0]}-{lines[1]}"
    label = label.replace("[", "(").replace("]", ")")
    return f"[{label}]({url})" if url else f"{label} (no link)"


def citation_link(citation) -> str:
    """``markdown_citation`` of anything that carries ``source_title``, ``source_url`` and ``section_path``."""
    return markdown_citation(citation.source_title, citation.source_url, citation.section_path, line_range(citation))


# What a tool result may occupy: below the inline limit (12 000 bytes) and inside the compact
# budget the model reads a result through (about 2200 tokens). Beyond it, results are cut whole.
TOOL_RESULT_BUDGET_BYTES = 7500


def within_budget(items: list[dict], *, reserve: int = 1500, budget: int = TOOL_RESULT_BUDGET_BYTES) -> list[dict]:
    """The longest prefix of ``items`` whose JSON fits the budget after ``reserve`` bytes of envelope."""
    import json

    kept: list[dict] = []
    used = reserve
    for item in items:
        used += len(json.dumps(item, ensure_ascii=False)) + 2
        if used > budget:
            break
        kept.append(item)
    return kept


class SourceRefs:
    """Numbers each cited source once (``S1``, ``S2``, …) so a long result names it by reference.

    A tool result reaches the model inside a small token budget; repeating a title, section and URL
    on every fact would crowd the facts out of it.
    """

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}

    def ref(self, citation) -> str:
        return self.ref_link(citation_link(citation))

    def ref_link(self, link: str) -> str:
        if link not in self._ids:
            self._ids[link] = f"S{len(self._ids) + 1}"
        return self._ids[link]

    def listing(self) -> list[dict[str, str]]:
        return [{"id": ref, "cite_as": link} for link, ref in self._ids.items()]


__all__ = [
    "TOOL_RESULT_BUDGET_BYTES",
    "SourceRefs",
    "citation_link",
    "evidence_locator",
    "markdown_citation",
    "within_budget",
]
