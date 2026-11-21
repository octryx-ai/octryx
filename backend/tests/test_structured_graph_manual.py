"""A1–A4: the rule-based manual extractor on the span shapes Docling produces (synthetic Demo Shop guide).

Golden: the Demo Shop Console 3.1 compatibility row yields exactly the guide's requirements
(Java SE 21, Jakarta EE 11, Tomcat 10.1.20, MySQL 8.4, PostgreSQL 16-17, Kafka 3.6-3.8), the merged
``Tom- cat My- SQL`` column included.
"""

from __future__ import annotations

import dataclasses

from app.services.knowledge.structured.facts import NodeRef
from app.services.knowledge.structured.manual import extract_manual
from app.services.knowledge.structured.profile import structured_profile
from app.services.knowledge.structured.profile_types import Component
from tests.structured_graph_support import CONSOLE_MANUAL, SERVER_MANUAL, span

SERVER = "demo-shop-server-guide"
APP = "demo-shop-console-guide"


def _server():
    return extract_manual(SERVER_MANUAL, structured_profile(), document_key=SERVER, title="Demo Shop Server Guide 1.4")


def _app(spans=CONSOLE_MANUAL, profile=None):
    return extract_manual(spans, profile or structured_profile(), document_key=APP, title="Demo Shop Console 3.1")


def _labels(extraction, node_type):
    return {node.label for ref, node in extraction.nodes.items() if ref.node_type == node_type}


def _edges(extraction, edge_type):
    return {(source.node_key, target.node_key): edge for (kind, source, target), edge in extraction.edges.items()
            if kind == edge_type}


def test_outline_is_rebuilt_from_heading_numbers_with_implied_titled_chapters():
    extraction = _server()
    # The closest implied ancestor of "6.3.2" takes the heading before it; the outer one stays implied.
    assert _labels(extraction, "Chapter") == {"2 General Information", "6 Chapter 6"}
    assert {"6.3 Server Setup", "6.4 Providers"} <= _labels(extraction, "Section")
    assert {"6.3.2 Database Settings", "6.3.3 Cache Settings", "6.4.1 Cache providers",
            "RedisCacheProvider"} <= _labels(extraction, "Subsection")
    contains = _edges(extraction, "contains")
    assert (f"{SERVER}#6.3", f"{SERVER}#6.3.3") in contains
    assert (f"{SERVER}#6.4.1", f"{SERVER}#6.4.1/RedisCacheProvider") in contains
    assert (SERVER, f"{SERVER}#2") in contains
    # Admonitions and list-item headings are neither sections nor chapter titles.
    every = " ".join(node.label for node in extraction.nodes.values())
    assert "Caution" not in every and "Without TLS" not in every
    database = extraction.nodes[NodeRef("Subsection", f"{SERVER}#6.3.2")]
    assert database.properties["headings"] == []
    section = extraction.nodes[NodeRef("Section", f"{SERVER}#6.3")]
    assert section.properties["page_start"] == 31 and section.cite.span_ordinal == 4


def test_references_resolve_by_section_number_name_and_page():
    references = _edges(_server(), "references")
    assert (f"{SERVER}#2.1", f"{SERVER}#6.3.2") in references  # "Database Settings (page 118)"
    assert (f"{SERVER}#6.3.3", f"{SERVER}#6.4.1/RedisCacheProvider") in references  # named, page 156
    assert (f"{SERVER}#6.3.3", f"{SERVER}#6.3.2") in references  # "See section 6.3.2"
    edge = references[(f"{SERVER}#2.1", f"{SERVER}#6.3.2")]
    assert edge.cites[0].span_ordinal == 3 and "page 118" in edge.properties["anchor"]


def test_parameters_carry_ini_scope_default_unit_and_their_section():
    extraction = _server()
    lock = extraction.nodes[NodeRef("Parameter", f"{SERVER}|ini:Cache?|RequestTimeout")]
    assert lock.label == "[Cache?] RequestTimeout"
    assert lock.properties["default"] == "60000" and lock.properties["unit"] == "ms"
    assert lock.cite.span_ordinal == 9
    hosts = extraction.nodes[NodeRef("Parameter", f"{SERVER}|ini:Cache?|Hosts")]
    assert hosts.properties["mandatory"] is True and hosts.properties["default"] is None
    engine = extraction.nodes[NodeRef("Parameter", f"{SERVER}|ini:Database?|Engine")]
    assert engine.properties["allowed_values"] == "PostgreSQL, MySQL and H2"
    documented = _edges(extraction, "documented_in")
    assert (f"{SERVER}|ini:Cache?|RequestTimeout", f"{SERVER}#6.3.3") in documented


def test_a_table_continued_after_a_page_break_keeps_its_header_and_row_continuations():
    extraction = _server()
    retry = extraction.nodes[NodeRef("Parameter", f"{SERVER}|ini:Cache?|RetryInterval")]
    assert retry.cite.span_ordinal == 11 and retry.properties["default"] == "5"
    assert retry.properties["description"].endswith("Values far below the timeout work best.")


def test_a_plain_parameter_table_takes_the_plugin_heading_as_scope():
    extraction = _server()
    values = extraction.nodes[NodeRef("Parameter", f"{SERVER}|plugin:RedisCacheProvider|MaxEntries")]
    assert values.label == "RedisCacheProvider.MaxEntries"
    documented = _edges(extraction, "documented_in")
    assert (values.ref.node_key, f"{SERVER}#6.4.1/RedisCacheProvider") in documented
    # A Docling-split name ("Entry" + "Lifetime") is only joined on a "- " break, never guessed.
    names = {node.properties["name"] for ref, node in extraction.nodes.items() if ref.node_type == "Parameter"}
    assert "EntryLifetime" in names


def test_golden_console_compatibility_edges_match_the_guide():
    extraction = _app()
    release = "product:demoshopconsole@3.1"
    found = {(kind, target.node_key.split(":", 1)[1], edge.properties["versions"])
             for (kind, source, target), edge in extraction.edges.items()
             if source.node_key == release and kind in ("requires", "supports")}
    assert found == {
        ("requires", "javase", "21"), ("requires", "jakartaee", "11"), ("supports", "tomcat", "10.1.20"),
        ("supports", "mysql", "8.4"), ("supports", "postgresql", "16-17"), ("supports", "kafka", "3.6-3.8"),
    }
    version = extraction.nodes[NodeRef("Version", release)]
    assert version.label == "Demo Shop Console 3.1" and version.cite.span_ordinal == 3
    assert ("requires", "javase", "17, 21") in {
        (kind, target.node_key.split(":", 1)[1], edge.properties["versions"])
        for (kind, source, target), edge in extraction.edges.items()
        if source.node_key.endswith("@2.9") and kind == "requires"
    }


def test_a_merged_header_whose_value_does_not_split_evenly_yields_a_table_row_not_a_guess():
    extraction = _app()
    release = "product:demoshopconsole@2.8"
    targets = {target.node_key for (kind, source, target) in extraction.edges if source.node_key == release}
    assert "component:tomcat" not in targets and "component:mysql" not in targets
    assert "component:kafka" in targets  # unambiguous columns still yield edges
    rows = [node for ref, node in extraction.nodes.items() if ref.node_type == "TableRow"]
    assert len(rows) == 1 and rows[0].properties["cells"][0] == "2.8"
    assert extraction.warnings["table_header_ambiguous"] == 1


def test_a_header_that_is_not_two_known_components_is_no_compatibility_table():
    profile = dataclasses.replace(structured_profile(), components=(Component("Java SE", "requires"),))
    extraction = _app(profile=profile)
    assert not _labels(extraction, "Version")


def test_terms_come_from_the_gazetteer_and_suffix_rule_and_link_to_their_section():
    extraction = _server()
    mentions = _edges(extraction, "mentions")
    assert (f"{SERVER}#6.4.1", "term:MemoryCacheProvider") in mentions
    assert (f"{SERVER}#6.3.3", "term:RedisCacheProvider") in mentions
    assert (f"{SERVER}#6.3.3", "term:RequestTimeout") not in mentions  # table rows are not mentions
    assert extraction.nodes[NodeRef("Term", "term:RedisCacheProvider")].properties["kind"] == "plugin"


def test_extraction_is_deterministic_and_independent_of_span_order():
    first = _server()
    second = extract_manual(list(reversed(SERVER_MANUAL)), structured_profile(), document_key=SERVER, title="x")
    assert set(first.nodes) == set(second.nodes)
    assert set(first.edges) == set(second.edges)


def test_an_empty_manual_yields_only_its_document_node():
    extraction = extract_manual([span(1, "Cover")], structured_profile(), document_key="m", title="Manual")
    assert set(extraction.nodes) == {NodeRef("Document", "m")} and not extraction.edges


def test_a_lower_number_after_a_deeper_section_is_a_folded_heading_not_a_new_chapter():
    spans = [span(1, "1.1 Overview", section=["1.1 Overview"]),
             span(2, "2.3 Release Policy", section=["2.3 Release Policy"]),
             span(3, "1 Release steps", section=["1 Release steps"]),
             span(4, "2019 Changes", section=["2019 Changes"])]
    extraction = extract_manual(spans, structured_profile(), document_key="m", title="Manual")
    assert _labels(extraction, "Chapter") == {"1 Chapter 1", "2 Chapter 2"}
    assert extraction.nodes[NodeRef("Section", "m#2.3")].properties["headings"] == ["1 Release steps", "2019 Changes"]


def test_a_named_reference_on_another_page_follows_the_page():
    spans = [*SERVER_MANUAL, span(18, "Remarks\n\nSee Configuration (page 31) and Cache Settings (page 124).",
                                  page=158, section=["1. Without TLS"])]
    references = _edges(extract_manual(spans, structured_profile(), document_key=SERVER, title="x"), "references")
    # "Configuration" names a heading on pages 156-157 only, so page 31 decides: the outermost section
    # starting there is chapter 6.
    assert (f"{SERVER}#6.4.1/RedisCacheProvider", f"{SERVER}#6") in references
    assert (f"{SERVER}#6.4.1/RedisCacheProvider", f"{SERVER}#6.3.3") in references
    assert all(source != target for source, target in references)
