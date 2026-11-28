"""Citation quality of parsed vendor manuals."""

from __future__ import annotations

import pytest

from app.services.knowledge.ingestion.docling_document import parse_document
from app.services.knowledge.ingestion.outline_sections import outline_index
from app.services.knowledge.ingestion.table_hyphens import document_vocabulary, repair_hyphen_breaks

PAGE_HEIGHT = 800.0


def _text(index: int, label: str, text: str, page: int, top: float = 100.0, **extra) -> dict:
    bbox = {"l": 50.0, "t": PAGE_HEIGHT - top, "r": 500.0, "b": PAGE_HEIGHT - top - 12, "coord_origin": "BOTTOMLEFT"}
    return {"self_ref": f"#/texts/{index}", "label": label, "text": text, "prov": [{"page_no": page, "bbox": bbox}],
            **extra}


def _document(texts: list[dict], tables: list[dict] = ()) -> dict:
    pages = {str(page): {"size": {"width": 600.0, "height": PAGE_HEIGHT}, "page_no": page} for page in range(1, 10)}
    children = [{"$ref": f"#/texts/{i}"} for i in range(len(texts))] + [
        {"$ref": f"#/tables/{i}"} for i in range(len(tables))
    ]
    return {"body": {"children": children}, "texts": texts, "tables": list(tables), "groups": [], "pages": pages}


def _section(spans, needle: str) -> tuple[str, ...]:
    return next(item.section_path for item in spans if needle in item.span.text)


@pytest.mark.parametrize("marker", ["® Note", "Ϫ Caution", "b Tip", "Warning", "Important", "Example", "Example 3",
                                    "Examples:", "NOTE", "Note: proxies"])
def test_3a_an_admonition_heading_is_body_text_in_the_enclosing_section(marker):
    spans = parse_document(_document([
        _text(0, "section_header", "1.2 The Desktop", 1, level=1),
        _text(1, "text", "The desktop is the first page after login.", 1),
        _text(2, "section_header", marker, 1, level=1),
        _text(3, "text", "Single sign-on skips the login page.", 1),
    ]))
    paths = {item.section_path for item in spans}
    assert paths == {("1.2 The Desktop",)}, (marker, paths)
    assert any(marker in item.span.text and "Single sign-on" in item.span.text for item in spans)


@pytest.mark.parametrize("heading", ["A Note on Licensing", "Notes and Limitations", "Tipping Points",
                                     "Example Configuration of the Datasource Layer",
                                     "Note: Configuring the Proxy for Outbound Datasource Calls"])
def test_3a_a_real_heading_that_contains_a_marker_word_stays_a_heading(heading):
    spans = parse_document(_document([
        _text(0, "section_header", "Chapter", 1, level=1),
        _text(1, "section_header", heading, 1, level=1),
        _text(2, "text", "Body text of the section.", 1),
    ]))
    assert spans[-1].section_path == (heading,)


def test_3a_the_markers_are_configurable():
    texts = [_text(0, "section_header", "Intro", 1, level=1), _text(1, "section_header", "® Hinweis", 1, level=1),
             _text(2, "text", "Body.", 1)]
    assert parse_document(_document(texts))[-1].section_path == ("® Hinweis",)
    assert parse_document(_document(texts), admonitions=("Hinweis",))[-1].section_path == ("Intro",)
    note = [_text(0, "section_header", "Intro", 1, level=1), _text(1, "section_header", "® Note", 1, level=1),
            _text(2, "text", "Body.", 1)]
    assert parse_document(_document(note), admonitions=())[-1].section_path == ("® Note",)


OUTLINE = [
    [0, "Configuration", 1],
    [1, "Tools", 2],
    [2, "Mass Closing", 2, 400.0],
    [1, "Statistics", 3],
    [2, "Datasources", 3],
    [3, "Investigation", 3, 300.0],
]


def test_3b_the_outline_gives_the_full_section_path_by_page_and_position():
    texts = [
        _text(0, "section_header", "Tools", 2, top=60, level=1),
        _text(1, "text", "Tools are configured per tenant.", 2, top=100),
        _text(2, "section_header", "Mass Closing", 2, top=400, level=1),
        _text(3, "text", "A mass closing tool closes many events.", 2, top=440),
        _text(4, "section_header", "Investigation", 3, top=300, level=1),
        _text(5, "text", "Investigation statistics show the status.", 3, top=340),
        _text(6, "code", "SELECT status FROM events", 4, top=50),
        _text(7, "text", "Above the bookmark on its own page.", 3, top=100),
    ]
    spans = parse_document(_document(texts), outline=OUTLINE)
    assert _section(spans, "Tools are configured") == ("Configuration", "Tools")
    assert _section(spans, "A mass closing tool") == ("Configuration", "Tools", "Mass Closing")
    deepest = ("Configuration", "Statistics", "Datasources", "Investigation")
    assert _section(spans, "Investigation statistics") == deepest
    assert _section(spans, "SELECT status") == deepest, "the next page continues the last section"
    assert _section(spans, "Above the bookmark") == ("Configuration", "Statistics", "Datasources")
    without = parse_document(_document(texts))
    assert _section(without, "A mass closing tool") == ("Mass Closing",), "no outline: today's behaviour"


def test_3b_paths_are_capped_and_a_malformed_outline_is_ignored():
    deep = [[level, f"L{level}", 1] for level in range(9)]
    assert outline_index(deep).path_at(1, 500.0) == tuple(f"L{level}" for level in range(6))
    texts = [_text(0, "section_header", "Heading", 1, level=1), _text(1, "text", "Body text.", 1)]
    for malformed in ([[0, "x"]], [[0, "x", 0]], [["0", "x", 1]], [[0, 5, 1]], [[0, "x", 1, -3]], "outline", []):
        assert outline_index(malformed) is None
        assert parse_document(_document(texts), outline=malformed)[-1].section_path == ("Heading",)
    late = [[0, "Later Chapter", 5]]
    assert parse_document(_document(texts), outline=late)[-1].section_path == ("Heading",), "before the first bookmark"


def test_3c_hyphen_breaks_in_table_cells_are_repaired_only_for_known_words():
    vocabulary = document_vocabulary(["You can restrict the events.", "The default behavior applies."])
    assert repair_hyphen_breaks("to re\u0002 strict the events", vocabulary) == "to restrict the events"
    assert repair_hyphen_breaks("behav-\nior of Jetty", vocabulary) == "behavior of Jetty"
    assert repair_hyphen_breaks("behav­ ior", vocabulary) == "behavior"
    assert repair_hyphen_breaks("an on- premises setup", vocabulary) == "an on-premises setup", "unknown: left"
    assert repair_hyphen_breaks("read-only and Single-Sign", vocabulary) == "read-only and Single-Sign"
    cell = lambda row, col, text: {"text": text, "start_row_offset_idx": row, "start_col_offset_idx": col}  # noqa: E731
    cells = [cell(0, 0, "Available"), cell(0, 1, "Optional attribute to re\u0002 strict the events")]
    table = {"label": "table", "prov": [{"page_no": 1}], "data": {"grid": [cells], "table_cells": cells}}
    texts = [_text(0, "text", "Mass closing can restrict tenants.", 1)]
    rendered = next(item.span.text for item in parse_document(_document(texts, [table])) if item.kind == "table")
    assert rendered == "Available | Optional attribute to restrict the events"
