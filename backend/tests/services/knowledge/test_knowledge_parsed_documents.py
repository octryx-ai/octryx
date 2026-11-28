"""PDF and Office documents become located, cited evidence through the parser sandbox: the DoclingDocument
mapping, the ``parse_revision`` obligation with a fake sandbox, and the adapter's answer handling."""

from __future__ import annotations

import pytest

from app.services.knowledge.ingestion.docling_document import parse_document
from app.services.knowledge.ingestion.parser_port import ParserError, ParserState
from tests.services.knowledge.knowledge_parsed_documents_support import _document, _text


def test_a_document_maps_to_spans_with_their_section_and_page():
    spans = parse_document(_document())
    rendered = [(item.kind, item.page_start, item.section_path, item.span.text) for item in spans]

    joined = "\n".join(text for *_, text in rendered)
    # Page furniture, the table of contents and a picture's inner labels never become evidence.
    for noise in ("Example Corp confidential", "Page 4", "........", "diagram label"):
        assert noise not in joined
    # A heading opens the span it introduces, and the path names every heading above it.
    # The span starts with the title on page 1 and runs into page 2.
    assert ("text", 1, ("Order Shipping Protocol", "Message Flow")) == rendered[0][:3]
    assert spans[0].page_end == 2
    assert rendered[0][3].startswith("Order Shipping Protocol\n\nMessage Flow\n\nThe carrier answers")
    challenge = next(item for item in rendered if "CReq" in item[3])
    assert challenge[2] == ("Order Shipping Protocol", "Message Flow", "Challenge")
    assert "1. The CReq carries the challenge data." in challenge[3]
    table = next(item for item in rendered if item[0] == "table")
    assert table[1] == 4 and "Version | Status\n2.3.1 | current" in table[3]
    # A heading of the same level replaces its sibling in the path.
    assert rendered[-1][2] == ("Order Shipping Protocol", "Error Handling")
    # Deterministic: the same document always yields the same spans.
    assert parse_document(_document()) == spans


def test_a_reference_outside_the_document_is_a_parser_contract_violation():
    document = _document()
    document["body"]["children"].append({"$ref": "#/texts/99"})
    with pytest.raises(ParserError) as raised:
        parse_document(document)
    assert raised.value.state == ParserState.CONTRACT_VIOLATION


def test_a_web_page_keeps_its_article_and_whole_sentences():
    code = lambda i, text: {"self_ref": f"#/texts/{i}", "label": "code", "text": text}  # noqa: E731
    plain = lambda i, text, **extra: {"self_ref": f"#/texts/{i}", "label": "text", "text": text, **extra}  # noqa: E731
    texts = [
        {
            "self_ref": "#/texts/0",
            "label": "title",
            "text": "Migration Guide",
            "children": [{"$ref": "#/groups/0"}, {"$ref": "#/groups/1"}],
        },
        code(1, "@JsonComponent"),
        plain(2, "is now"),
        code(3, "@JacksonComponent"),
        plain(4, "Skip to content"),
    ] + [
        {"self_ref": f"#/texts/{5 + i}", "label": "list_item", "text": f"Page {i}", "hyperlink": f"/wiki/Page-{i}"}
        for i in range(25)
    ]
    document = {
        "origin": {"mimetype": "text/html"},
        "body": {"children": [{"$ref": "#/texts/4"}, {"$ref": "#/texts/0"}]},
        "texts": texts,
        "groups": [
            {"label": "inline", "children": [{"$ref": "#/texts/1"}, {"$ref": "#/texts/2"}, {"$ref": "#/texts/3"}]},
            {"label": "list", "children": [{"$ref": f"#/texts/{5 + i}"} for i in range(25)]},
        ],
    }
    (span,) = parse_document(document)
    assert "`@JsonComponent` is now `@JacksonComponent`" in span.span.text
    assert "Skip to content" not in span.span.text and "Page 3" not in span.span.text


def test_an_html_list_item_wrapping_its_text_in_a_paragraph_is_read_once():
    # Confluence's view HTML is <li><p>text</p></li>: Docling gives the item its text and keeps the
    # paragraph as its child. The paragraph must not repeat every list entry in the evidence.
    document = {
        "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/groups/0"}]},
        "texts": [
            _text(0, "section_header", "Image Configuration", 1, level=1),
            {**_text(1, "list_item", "acmeordersbi: Superset image version", 1, marker="-"),
             "children": [{"$ref": "#/texts/2"}]},
            _text(2, "text", "acmeordersbi: Superset image version", 1),
            {**_text(3, "list_item", "proxybi: NGINX proxy image version", 1, marker="-"),
             "children": [{"$ref": "#/texts/4"}]},
            _text(4, "text", "A different sentence nested under the item.", 1),
        ],
        "groups": [{"self_ref": "#/groups/0", "label": "list",
                    "children": [{"$ref": "#/texts/1"}, {"$ref": "#/texts/3"}]}],
        "pictures": [],
        "tables": [],
    }
    text = "\n".join(item.span.text for item in parse_document(document))
    assert text.count("acmeordersbi: Superset image version") == 1
    assert "proxybi: NGINX proxy image version" in text
    # A child that says something else is still evidence.
    assert "A different sentence nested under the item." in text
