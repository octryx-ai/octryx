"""Citation and bibliography block for generated Word scripts."""

from __future__ import annotations


def _word_script_inline_citations() -> str:
    return """\
def _resolve_citation_numbers(value: object) -> list[int]:
    raw_values: list[object]
    if isinstance(value, list):
        raw_values = value
    elif value is None:
        raw_values = []
    else:
        raw_values = [value]
    numbers: list[int] = []
    seen: set[int] = set()
    for item in raw_values:
        if isinstance(item, int):
            number = item
        else:
            cleaned = _clean_key(item)
            number = SOURCE_INDEX.get(cleaned) if cleaned else None
        if not number or number in seen:
            continue
        seen.add(number)
        numbers.append(number)
    return numbers


def _format_inline_citation(numbers: list[int]) -> str:
    if not numbers or CITATION_STYLE == "none":
        return ""
    refs = [NORMALIZED_SOURCES[number - 1] for number in numbers if 0 < number <= len(NORMALIZED_SOURCES)]
    if not refs:
        return ""
    if CITATION_STYLE == "ieee":
        return " [" + ", ".join(str(number) for number in numbers) + "]"
    if CITATION_STYLE in {"apa", "harvard", "chicago"}:
        parts = [f"{_author_surname(source)}, {_year_for_source(source)}" for source in refs]
        return " (" + "; ".join(parts) + ")"
    if CITATION_STYLE == "mla":
        parts = [_author_surname(source) for source in refs]
        return " (" + "; ".join(parts) + ")"
    return ""


"""


def _word_script_reference_entry_ieee_apa() -> str:
    return """\
def _format_reference_entry(number: int, source: dict[str, object]) -> str:
    authors = _author_label(source)
    title = _source_title(source)
    publisher = str(source.get("publisher") or source.get("organization") or "").strip()
    year = _year_for_source(source)
    url = _source_url(source)
    accessed = _accessed_at(source)
    doi = _source_doi(source)
    isbn = _source_isbn(source)
    if CITATION_STYLE == "ieee":
        parts = [f"[{number}] {authors}", f'"{title}."']
        if publisher:
            parts.append(publisher)
        if year and year != "n.d.":
            parts.append(year)
        entry = ", ".join(part for part in parts if part)
        if doi:
            entry += f". doi:{doi}"
        if isbn:
            entry += f". ISBN {isbn}"
        if url:
            entry += f". {url}"
        if accessed:
            entry += f" (accessed {accessed})"
        return entry
    if CITATION_STYLE in {"apa", "harvard"}:
        entry = f"{authors} ({year}). {title}."
        if publisher:
            entry += f" {publisher}."
        if doi:
            entry += f" https://doi.org/{doi}"
        elif isbn:
            entry += f" ISBN {isbn}."
        if url:
            entry += f" {url}"
        return entry.strip()
    if CITATION_STYLE == "mla":
        entry = f'{authors}. "{title}."'
        if publisher:
            entry += f" {publisher},"
        entry += f" {year}."
        if doi:
            entry += f" doi:{doi}."
        elif isbn:
            entry += f" ISBN {isbn}."
        if url:
            entry += f" {url}."
        if accessed:
            entry += f" Accessed {accessed}."
        return entry.strip()
"""


def _word_script_reference_entry_mla_chicago() -> str:
    return """\
    if CITATION_STYLE == "chicago":
        entry = f'{authors}. {year}. "{title}."'
        if publisher:
            entry += f" {publisher}."
        if doi:
            entry += f" https://doi.org/{doi}."
        elif isbn:
            entry += f" ISBN {isbn}."
        if url:
            entry += f" {url}."
        return entry.strip()
    return title


"""


def _word_script_render_bibliography() -> str:
    return """\
def _render_bibliography() -> None:
    if not INCLUDE_BIBLIOGRAPHY or CITATION_STYLE == "none" or not NORMALIZED_SOURCES:
        return
    heading = "Works Cited" if CITATION_STYLE == "mla" else "References"
    add_heading(heading, 1)
    for index, source in enumerate(NORMALIZED_SOURCES, start=1):
        add_paragraph(_format_reference_entry(index, source))
"""


__all__ = [
    "_word_script_inline_citations",
    "_word_script_reference_entry_ieee_apa",
    "_word_script_reference_entry_mla_chicago",
    "_word_script_render_bibliography",
]
