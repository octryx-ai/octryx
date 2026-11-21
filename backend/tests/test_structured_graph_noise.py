"""Handbook vs. reality without noise: comments, framework files, placeholders, variants, sections.

A working report can still be noisy. These rules come from the profile, never from
product names in code: commented-out lines are comments per format, logging/framework files and
placeholder sources are not compared with the manual, ``${Name}`` values are resolved from the
component's placeholder sources (or reported as unresolved, never compared), variant files
(``app.ini-test``) are judged once with their base file, and undocumented keys are split into
sections the manual knows and sections it does not know at all.
"""

from __future__ import annotations

import pytest

from app.services.knowledge.structured.config_families import NodeRow, Placeholders, families
from app.services.knowledge.structured.config_files import parse_config
from app.services.knowledge.structured.config_layer import rule_for, variant_of
from app.services.knowledge.structured.config_linkage_compute import compute_linkage
from app.services.knowledge.structured.facts import node_id
from app.services.knowledge.structured.profile import PROFILE_PATH, load_profile
from app.services.knowledge.structured.profile import structured_profile as profile
from app.services.knowledge.structured.profile_types import StructuredProfileError

LOG4J = """\
log4j.rootLogger=OFF, RssAppender
;log4j.logger.com.example.HttpService.Stream=TRACE
; log4j.logger.PerformanceCounter.ReuseCache.get=DEBUG
! log4j.logger.Other=DEBUG
# log4j.logger.Third=DEBUG
log4j.logger.com.example=INFO
"""


def _parse(text: str, file_format: str):
    return parse_config(text, file_format, profile().comment_prefixes[file_format], profile().continuation_prefixes)


def test_commented_lines_are_comments_per_format_from_the_profile():
    parsed = _parse(LOG4J, "properties")
    assert [entry.key for entry in parsed.entries] == ["log4j.rootLogger", "log4j.logger.com.example"]
    assert [line for line, _ in parsed.comments] == [2, 3, 4, 5]
    assert profile().comment_prefixes["properties"] == ("#", "!", ";")
    # The prefixes are the profile's: without ";" the same line is a key ";" again.
    legacy = parse_config(LOG4J, "properties", ("#", "!"), ())
    assert {entry.key for entry in legacy.entries} >= {";", ";log4j.logger.com.example.HttpService.Stream"}
    assert [entry.key for entry in _parse("[A]\n;B = 1\nC = 2\n", "ini").entries] == ["C"]
    assert [entry.key for entry in _parse("# a: 1\nb: 2\n", "yaml").entries] == ["b"]


@pytest.mark.parametrize(("path", "documented", "file_format"), [
    ("util/util/log4j.properties", False, "properties"),
    ("app/log4j2-test.properties", False, "properties"),
    ("app/logging.properties", False, "properties"),
    ("app/server.log.properties", False, "properties"),
    ("zotel/otel-javaagent.properties", False, "properties"),
    ("conf/shop_config.properties", False, "properties"),
    ("pp-logic/logic_config.properties", False, "properties"),
    ("conf/server.properties", True, "properties"),
    ("conf/app.ini", True, "ini"),
    ("worker/pricing_service.ini-test", True, "ini"),
])
def test_logging_framework_and_placeholder_files_are_not_compared_with_the_manual(path, documented, file_format):
    rule = rule_for(path, profile().config_files)
    assert rule is not None and rule.manual_documented is documented and rule.format == file_format


@pytest.mark.parametrize(("old", "new", "message"), [
    ('"yaml": ["#"]}', '"yml": ["#"]}', "comment_prefixes"),
    ("(?P<base>.+\\\\.ini)", "(?P<other>.+\\\\.ini)", "variant pattern"),
    ("(?P<name>[A-Za-z_]", "(?P<other>[A-Za-z_]", "placeholder_pattern"),
])
def test_the_profile_refuses_broken_comment_variant_and_placeholder_rules(tmp_path, old, new, message):
    raw = PROFILE_PATH.read_text(encoding="utf-8")
    assert old in raw
    broken = tmp_path / "structured.json"
    broken.write_text(raw.replace(old, new), encoding="utf-8")
    with pytest.raises(StructuredProfileError, match=message):
        load_profile(broken)


def test_variant_files_name_their_base_file():
    patterns = profile().variant_patterns
    assert variant_of("worker/pricing_service.ini-test", patterns) == ("worker/pricing_service.ini", "test")
    assert variant_of("app.ini-prod.eu", patterns) == ("app.ini", "prod.eu")
    assert variant_of("conf/app.ini", patterns) == ("conf/app.ini", None)
    assert variant_of("conf/app.ini-", patterns) == ("conf/app.ini-", None)


# --- Linkage over hand-made rows --------------------------------------------------------------------

MANUAL = "rev-manual"


def _setting(path: str, section: str | None, key: str, value: str, line: int, *, component: str | None = None,
             documented: bool = True, redacted: bool = False, section_type: str | None = None) -> NodeRow:
    base, variant = variant_of(path, profile().variant_patterns)
    props = {"repo": "repo", "path": path, "format": rule_for(path, profile().config_files).format,
             "component": component or path.split("/", 1)[0], "section": section,
             "section_type": section_type or section, "key": key, "value": value, "redacted": redacted,
             "line": line, "manual_documented": documented, "base_path": base, "variant": variant}
    label = f"[{section}] {key}" if section else key
    return NodeRow(node_id("ConfiguredSetting", f"repo:{path}|{section}|{key}@{line}"), "ConfiguredSetting",
                   f"rev:{path}", 1, line, label, props)


def _parameter(scope_kind: str, scope: str, name: str, default: str | None, ordinal: int) -> NodeRow:
    label = f"[{scope}] {name}" if scope_kind == "ini" else f"{scope}.{name}"
    return NodeRow(node_id("Parameter", f"server|{scope_kind}:{scope}|{name}"), "Parameter", MANUAL, ordinal, None,
                   label, {"name": name, "scope_kind": scope_kind, "scope": scope, "default": default})


PARAMETERS = [
    _parameter("ini", "Cache?", "RequestTimeout", "60000", 10),
    _parameter("ini", "Cache?", "ConnectTimeout", "60000", 11),
    _parameter("ini", "GeneralSettings", "ProjectConfig", "project.ini", 12),
    _parameter("ini", "GeneralSettings", "Format", "<Format>", 13),
    _parameter("ini", "GeneralSettings", "QueueSize", "<mandatory> if ThreadCount>0", 14),
    _parameter("ini", "GeneralSettings", "IncomingDir", '{BaseDir}+"/incoming"', 15),
]
DOCUMENTS = [
    NodeRow(node_id("Document", "server"), "Document", MANUAL, 1, None, "Server", {}),
    # A manual without parameter tables (a compatibility guide) never leaves a setting undocumented.
    NodeRow(node_id("Document", "guide"), "Document", "rev-guide", 1, None, "Guide", {}),
]


def _link(settings: list[NodeRow]) -> list:
    placeholders = Placeholders(settings, profile().placeholder_pattern, profile().placeholder_sources)
    return compute_linkage(settings, PARAMETERS, DOCUMENTS, profile().registry_sections, placeholders,
                           profile().non_comparable_defaults)


def _typed(edges, edge_type: str) -> list:
    return [edge for edge in edges if edge.edge_type == edge_type]


def test_a_resolved_placeholder_is_compared_and_cites_its_definition():
    same = _setting("conf/app.ini", "Cache1", "RequestTimeout", "${Conf_Timeout}", 3)
    source = _setting("conf/shop_config.properties", None, "Conf_Timeout", "60000", 7, documented=False)
    assert not _typed(_link([same, source]), "deviates_from_default")
    other = _setting("conf/shop_config.properties", None, "Conf_Timeout", "${Conf_Base}0", 7, documented=False)
    base = _setting("conf/shop_config.properties", None, "Conf_Base", "50", 8, documented=False)
    edges = _link([same, other, base])
    (deviation,) = _typed(edges, "deviates_from_default")
    assert deviation.source_id == same.node_id
    assert deviation.properties["value"] == "${Conf_Timeout}" and deviation.properties["resolved_value"] == "500"
    assert other.cite in deviation.citations and base.cite in deviation.citations
    assert not _typed(edges, "unresolved_placeholder")


@pytest.mark.parametrize("definitions", [
    [],  # nothing defines it
    [("data/shop_config.properties", "Conf_Timeout", "500", False)],  # another component's definition
    [("conf/shop_config.properties", "Conf_Timeout", "[redacted]", True)],  # a redacted definition
    [("conf/shop_config.properties", "Conf_Timeout", "${Conf_Loop}", False),
     ("conf/shop_config.properties", "Conf_Loop", "${Conf_Timeout}", False)],  # a cycle
    [("conf/server.properties", "Conf_Timeout", "500", False)],  # not a placeholder source of the profile
])
def test_an_unresolved_placeholder_is_never_compared(definitions):
    lock = _setting("conf/app.ini", "Cache1", "RequestTimeout", "${Conf_Timeout}", 3)
    peer = _setting("data/app.ini", "Cache1", "RequestTimeout", "500", 3)
    rows = [lock, peer] + [_setting(path, None, key, value, 1 + n, redacted=redacted, documented=False)
                           for n, (path, key, value, redacted) in enumerate(definitions)]
    edges = _link(rows)
    (unresolved,) = _typed(edges, "unresolved_placeholder")
    assert unresolved.source_id == lock.node_id
    assert unresolved.properties["placeholders"][0] in {"Conf_Timeout", "Conf_Loop"}
    assert not [edge for edge in _typed(edges, "deviates_from_default") if edge.source_id == lock.node_id]
    assert not [edge for edge in _typed(edges, "inconsistent_across") if lock.node_id in (edge.source_id,
                                                                                           edge.target_id)]


def test_inconsistencies_compare_resolved_values():
    conf = _setting("conf/app.ini", "Cache1", "RequestTimeout", "${Conf_Timeout}", 3)
    source = _setting("conf/shop_config.properties", None, "Conf_Timeout", "500", 1, documented=False)
    same = _setting("data/app.ini", "Cache1", "RequestTimeout", "500", 3)
    assert not _typed(_link([conf, source, same]), "inconsistent_across")
    differs = _setting("data/app.ini", "Cache1", "RequestTimeout", "600", 3)
    (edge,) = _typed(_link([conf, source, differs]), "inconsistent_across")
    assert sorted(edge.properties["values"]) == ["500", "600"]
    assert "${Conf_Timeout}" in edge.properties["raw_values"] and source.cite in edge.citations


def test_a_variant_file_is_judged_once_with_its_base_file():
    base = _setting("worker/app.ini", "Cache1", "RequestTimeout", "500", 3)
    test = _setting("worker/app.ini-test", "Cache1", "RequestTimeout", "700", 4)
    pool = _setting("worker/app.ini", "Cache1", "PoolSize", "8", 5)
    pool_test = _setting("worker/app.ini-test", "Cache1", "PoolSize", "9", 6)
    edges = _link([base, test, pool, pool_test])
    (deviation,) = _typed(edges, "deviates_from_default")
    assert deviation.source_id == base.node_id and deviation.properties["deviates"] is True
    (variant,) = deviation.properties["variants"]
    assert variant == {"path": "worker/app.ini-test", "variant": "test", "line": 4, "value": "700",
                       "deviates": True, "unresolved": []}
    assert test.cite in deviation.citations
    # Both members configure the parameter (a fact); the finding is stated once.
    assert {edge.source_id for edge in _typed(edges, "configures")} == {base.node_id, test.node_id}
    (undocumented,) = _typed(edges, "undocumented")
    assert undocumented.source_id == pool.node_id and undocumented.target_id == DOCUMENTS[0].node_id
    assert [item["path"] for item in undocumented.properties["variants"]] == ["worker/app.ini-test"]


def test_only_a_variant_deviating_is_still_reported_once_on_the_base():
    base = _setting("worker/app.ini", "Cache1", "RequestTimeout", "60000", 3)
    test = _setting("worker/app.ini-test", "Cache1", "RequestTimeout", "700", 4)
    (deviation,) = _typed(_link([base, test]), "deviates_from_default")
    assert deviation.source_id == base.node_id and deviation.properties["deviates"] is False
    assert deviation.properties["variants"][0]["deviates"] is True


def test_variants_add_no_inconsistency_pairs_and_a_lone_variant_leads_itself():
    conf = _setting("conf/app.ini", "Cache1", "RequestTimeout", "500", 3)
    worker_conf = _setting("worker/app.ini", "Cache1", "RequestTimeout", "60000", 3)
    worker_test = _setting("worker/app.ini-test", "Cache1", "RequestTimeout", "700", 3)
    (pair,) = _typed(_link([conf, worker_conf, worker_test]), "inconsistent_across")
    assert {pair.source_id, pair.target_id} == {conf.node_id, worker_conf.node_id}
    assert [item["path"] for side in pair.properties["variants"] for item in side] == ["worker/app.ini-test"]
    lone = _setting("worker/other.ini-test", "Cache1", "RequestTimeout", "700", 3)
    (deviation,) = _typed(_link([lone]), "deviates_from_default")
    assert deviation.source_id == lone.node_id and deviation.properties["variants"] == []
    grouped = families([worker_conf, worker_test, conf])
    assert [(family.lead.node_id, len(family.variants)) for family in grouped] == [(worker_conf.node_id, 1),
                                                                                   (conf.node_id, 0)]


def test_unknown_sections_are_one_item_per_base_file_and_section_with_their_keys():
    rows = [
        _setting("conf/app.ini", "HttpRequestCustomerIds", "Url", "http://x", 10),
        _setting("conf/app.ini", "HttpRequestCustomerIds", "RequestTimeout", "5", 11),
        _setting("conf/app.ini-test", "HttpRequestCustomerIds", "Url", "http://y", 10),
        # A key only the variant file has joins its base file's section item.
        _setting("conf/app.ini-test", "HttpRequestCustomerIds", "Extra", "1", 12),
        _setting("conf/app.ini", "GeneralSettings", "Unknown", "1", 2),
        _setting("conf/app.properties", None, "app.mode", "x", 1),
        _setting("conf/app.properties", None, "app.size", "2", 2),
        _setting("util/log4j.properties", None, "RequestTimeout", "1", 1, documented=False),
    ]
    edges = _link(rows)
    unknown = {(edge.properties["section"], edge.source_id): edge.properties for edge in _typed(edges, "unknown_section")}
    assert unknown == {
        ("HttpRequestCustomerIds", rows[0].node_id): {"section": "HttpRequestCustomerIds", "key_count": 3,
                                                  "keys": ["Url", "RequestTimeout", "Extra"],
                                                  "variant_files": ["conf/app.ini-test"]},
        (None, rows[5].node_id): {"section": None, "key_count": 2, "keys": ["app.mode", "app.size"],
                                  "variant_files": []},
    }
    # [GeneralSettings] is documented: its unknown key is the important "undocumented" case.
    assert [edge.source_id for edge in _typed(edges, "undocumented")] == [rows[4].node_id]
    assert {edge.target_id for edge in _typed(edges, "undocumented") + _typed(edges, "unknown_section")} == {
        DOCUMENTS[0].node_id}
    # Keys of an unknown section keep their same-name hint; a logging file is never judged.
    hints = {(edge.source_id, edge.target_id) for edge in _typed(edges, "name_matches")}
    assert hints == {(rows[1].node_id, PARAMETERS[0].node_id)}


def test_a_documented_default_that_is_no_value_is_never_compared():
    rows = [_setting("conf/app.ini", "GeneralSettings", key, value, line) for line, (key, value) in enumerate(
        [("Format", "JSON"), ("QueueSize", "50"), ("IncomingDir", "/data/in"), ("ProjectConfig", "other.ini")], 1)]
    edges = _link(rows)
    assert {edge.source_id for edge in _typed(edges, "configures")} == {row.node_id for row in rows}
    assert [edge.source_id for edge in _typed(edges, "deviates_from_default")] == [rows[3].node_id]
    without = compute_linkage(rows, PARAMETERS, DOCUMENTS, profile().registry_sections)
    assert len(_typed(without, "deviates_from_default")) == 4  # the profile rule is what keeps them out


def test_a_placeholder_that_rebuilds_a_credential_is_withheld():
    # Neither line is a secret on its own; the substituted URL carries user:password.
    url = _setting("conf/app.ini", "GeneralSettings", "Url", "mysql://${Creds}@db/x", 3)
    creds = _setting("conf/shop_config.properties", None, "Creds", "scott:tiger", 7, documented=False)
    placeholders = Placeholders([url, creds], profile().placeholder_pattern, profile().placeholder_sources)
    resolved = placeholders.resolve(url)
    assert resolved.value is None
    assert "tiger" not in repr([edge.properties for edge in _link([url, creds])])
