"""B1/B2: configuration parsing and the manual ↔ configuration linkage, on a synthetic shop configuration.

Golden (live acceptance shape): ``[QueueConnection] RequestTimeout`` is 500 in ``conf`` and 60000 in
``data`` and ``worker``. The Server manual documents ``RequestTimeout`` only for ``[Cache?]`` and nothing
of ``[QueueConnection]``, so the section is an ``unknown_section`` whose RequestTimeout key carries a
``name_matches`` hint to the cache parameter, and the three settings are ``inconsistent_across``
conf↔data and conf↔worker. The ``DynamoDBCacheProvider`` section (typed by the ``[Provider]``
registry) is unknown too; the undocumented keys of ``[HttpService_Ping]`` (a documented plugin type)
are the important ``undocumented`` ones.
"""

from __future__ import annotations

from app.services.knowledge.structured.config_families import NodeRow
from app.services.knowledge.structured.config_files import parse_ini, parse_properties, parse_yaml
from app.services.knowledge.structured.config_linkage_compute import compute_linkage
from app.services.knowledge.structured.config_linkage_rules import ini_matches, same_value
from app.services.knowledge.structured.facts import node_id
from app.services.knowledge.structured.manual import extract_manual
from app.services.knowledge.structured.profile import structured_profile
from tests.structured_graph_support import SERVER_MANUAL

PREFIXES = (";", "#", "\\")
CONTINUATIONS = ("+",)
REGISTRY = ("Services", "Provider")

CONF_APP_INI = """\
;------------------------------------------------------------------------------;
; Demo Shop Server Version: 1.4                                               ;
;------------------------------------------------------------------------------;
[GeneralSettings]
ProjectConfig                     = project.ini
KeyStorePassword                  = s3cr3t-Value
ApiAccessKey                      = AKIAEXAMPLE

[Services]
HttpService_Ping                  = HttpService(HttpServer, /ping, Ping)
;CsvFileService_OrderRequest2        = CsvFileService(OrderRequest2)

[HttpService_Ping]
ThreadCount                       = 4
SqlSelect                         = SELECT ID
+                                   FROM T
Pattern                           = [0-9]+

[Provider]
${CACHE_PREFIX}Customer_Profiles  = DynamoDBCacheProvider

[${CACHE_PREFIX}Customer_Profiles]
MaxEntries                        = 30
EntryLifetime                     = 86400

; Actual connection details for the queue are configured via environment variables
[QueueConnection]
; ACME-117: reduced from 5000ms to 500ms.
; Under peak load the single checkout worker thread was blocked for 5s per item.
RequestTimeout                    = {lock}
RetryInterval                     = 50
"""


def _ini(lock: str = "500"):
    return parse_ini(CONF_APP_INI.replace("{lock}", lock), PREFIXES, CONTINUATIONS)


def test_ini_sections_lines_continuations_and_comment_blocks():
    parsed = _ini()
    entries = {(entry.section, entry.key): entry for entry in parsed.entries}
    lock = entries[("QueueConnection", "RequestTimeout")]
    assert lock.value == "500" and lock.line == 30
    assert [text for _, text in lock.comments][0].startswith("; ACME-117")
    assert entries[("HttpService_Ping", "SqlSelect")].value == "SELECT ID FROM T"
    assert entries[("HttpService_Ping", "Pattern")].value == "[0-9]+"  # a trailing "+" continues nothing
    assert parsed.skipped_lines == 0
    assert ("Services", ";CsvFileService_OrderRequest2") not in entries  # a commented-out entry is no setting
    assert parsed.sections["QueueConnection"] == 27


def test_registry_sections_type_the_instance_sections():
    types = _ini().section_types(REGISTRY)
    assert types == {"HttpService_Ping": "HttpService", "${CACHE_PREFIX}Customer_Profiles": "DynamoDBCacheProvider"}


def test_secret_values_are_masked_by_key_camel_case_or_value_and_never_kept():
    entries = {entry.key: entry for entry in _ini().entries}
    for key in ("KeyStorePassword", "ApiAccessKey"):
        assert entries[key].redacted and entries[key].value == "[redacted]"
    assert "s3cr3t" not in repr(_ini().entries)
    # A continuation line that reads as a secret setting is never joined: it is its own, redacted setting.
    options, secret = parse_ini("[Db]\nOptions = timeout=5\n+ password=hunter2\n", PREFIXES, CONTINUATIONS).entries
    assert (options.key, options.value, options.redacted) == ("Options", "timeout=5", False)
    assert (secret.key, secret.value, secret.redacted) == ("password", "[redacted]", True)
    assert "hunter2" not in repr([options, secret])
    properties = parse_properties("db.url=jdbc:postgresql://u:pw@host/db\n# comment\nshop.timeout: 30\n")
    assert [(e.key, e.value, e.redacted) for e in properties.entries][1] == ("shop.timeout", "30", False)
    assert properties.entries[0].redacted


def test_yaml_values_flatten_to_dotted_paths_with_their_own_line():
    parsed = parse_yaml("shop:\n  image:\n    tag: 3.2-3\n  env:\n    - name: A\n  password: hunter2\n")
    entries = {entry.key: entry for entry in parsed.entries}
    assert entries["shop.image.tag"].value == "3.2-3" and entries["shop.image.tag"].line == 3
    assert entries["shop.env[0].name"].line == 5
    assert entries["shop.password"].redacted and entries["shop.password"].value == "[redacted]"
    assert parse_yaml("a: [unclosed").entries == []


def test_value_comparison_and_section_patterns_are_exact():
    assert same_value("60000", "60000.0") and same_value("TRUE", "true") and not same_value("500", "60000")
    assert ini_matches("Cache?", "Cache1") and ini_matches("Database?", "Database_Orders")
    assert not ini_matches("Cache?", "QueueConnection") and not ini_matches("GeneralSettings", "generalsettings")
    assert not ini_matches("<Source>", "Anything")


def _settings(component: str, lock: str) -> list[NodeRow]:
    parsed = _ini(lock)
    types = parsed.section_types(REGISTRY)
    path = f"{component}/app.ini"
    return [
        NodeRow(node_id("ConfiguredSetting", f"repo:{path}|{e.section}|{e.key}"), "ConfiguredSetting", f"rev-{component}",
                1, e.line, f"[{e.section}] {e.key}",
                {"repo": "repo", "path": path, "format": "ini", "component": component, "section": e.section,
                 "section_type": types.get(e.section, e.section), "key": e.key, "value": e.value,
                 "redacted": e.redacted, "line": e.line, "manual_documented": True})
        for e in parsed.entries
    ]


def _manual() -> tuple[list[NodeRow], list[NodeRow]]:
    extraction = extract_manual(SERVER_MANUAL, structured_profile(), document_key="guide", title="Server")
    parameters = [NodeRow(ref.id, "Parameter", "rev-manual", node.cite.span_ordinal, None, node.label, node.properties)
                  for ref, node in extraction.nodes.items() if ref.node_type == "Parameter"]
    # A plugin-scoped parameter that the fixture INI configures through the [Services] registry type.
    parameters.append(NodeRow(node_id("Parameter", "guide|plugin:HttpService|ThreadCount"), "Parameter",
                              "rev-manual", 30, None, "HttpService.ThreadCount",
                              {"name": "ThreadCount", "scope_kind": "plugin", "scope": "HttpService", "default": "1"}))
    parameters.append(NodeRow(node_id("Parameter", "guide|plugin:HttpService|SendError"), "Parameter",
                              "rev-manual", 31, None, "HttpService.SendError",
                              {"name": "SendError", "scope_kind": "plugin", "scope": "HttpService", "default": "true"}))
    parameters.append(NodeRow(node_id("Parameter", "guide|ini:GeneralSettings|KeyStorePassword"), "Parameter",
                              "rev-manual", 32, None, "[GeneralSettings] KeyStorePassword",
                              {"name": "KeyStorePassword", "scope_kind": "ini", "scope": "GeneralSettings",
                               "default": "changeit"}))
    documents = [NodeRow(node_id("Document", "guide"), "Document", "rev-manual", 1, None, "Server", {})]
    return parameters, documents


def _golden_edges():
    settings = _settings("conf", "500") + _settings("data", "60000") + _settings("worker", "60000")
    parameters, documents = _manual()
    edges = compute_linkage(settings, parameters, documents, REGISTRY)
    labels = {row.node_id: (row.properties.get("component"), row.label) for row in settings}
    labels.update({row.node_id: ("manual", row.label) for row in parameters + documents})
    for row in settings:
        labels.setdefault(node_id("ConfigFile", f"repo:{row.properties['path']}"), ("file", row.properties["path"]))
    return [(edge.edge_type, labels[edge.source_id], labels[edge.target_id], edge) for edge in edges]


def test_golden_requesttimeout_is_in_an_unknown_section_with_a_cache_hint_and_inconsistent_across_components():
    edges = _golden_edges()
    lock = [(kind, source, target) for kind, source, target, _ in edges
            if source[1] == "[QueueConnection] RequestTimeout"]
    assert ("unknown_section", ("conf", "[QueueConnection] RequestTimeout"), ("manual", "Server")) in lock
    section = next(edge for kind, source, _, edge in edges
                   if kind == "unknown_section" and source == ("conf", "[QueueConnection] RequestTimeout"))
    assert section.properties == {"section": "QueueConnection", "key_count": 2,
                                  "keys": ["RequestTimeout", "RetryInterval"], "variant_files": []}
    assert not [item for item in lock if item[0] == "undocumented"]
    assert ("name_matches", ("conf", "[QueueConnection] RequestTimeout"), ("manual", "[Cache?] RequestTimeout")) in lock
    assert not [item for item in lock if item[0] == "configures"]
    inconsistent = {frozenset((source[0], target[0])) for kind, source, target, _ in edges
                    if kind == "inconsistent_across" and source[1] == "[QueueConnection] RequestTimeout"}
    assert inconsistent == {frozenset({"conf", "data"}), frozenset({"conf", "worker"})}
    settings = {source for kind, source, _, _ in edges if source[1] == "[QueueConnection] RequestTimeout"}
    assert settings == {("conf", "[QueueConnection] RequestTimeout"), ("data", "[QueueConnection] RequestTimeout"),
                        ("worker", "[QueueConnection] RequestTimeout")}


def test_golden_dynamodb_cache_provider_section_is_unknown_and_known_sections_keep_their_keys():
    edges = _golden_edges()
    unknown = {edge.properties["section"]: edge.properties["keys"] for kind, source, _, edge in edges
               if kind == "unknown_section" and source[0] == "conf"}
    assert unknown["${CACHE_PREFIX}Customer_Profiles"] == ["MaxEntries", "EntryLifetime"]
    # [HttpService_Ping] is an HttpService, a plugin type the manual documents: its unknown keys matter.
    undocumented = {source[1] for kind, source, _, _ in edges if kind == "undocumented" and source[0] == "conf"}
    assert undocumented == {"[HttpService_Ping] SqlSelect", "[HttpService_Ping] Pattern",
                            "[GeneralSettings] ProjectConfig", "[GeneralSettings] ApiAccessKey"}
    assert "HttpService_Ping" not in unknown
    hints = {target[1] for kind, source, target, _ in edges
             if kind == "name_matches" and source == ("conf", "[${CACHE_PREFIX}Customer_Profiles] MaxEntries")}
    assert hints == {"RedisCacheProvider.MaxEntries"}
    # Registry entries declare instances; they are never judged as parameters.
    assert not any(source[1].startswith(("[Services]", "[Provider]")) for _, source, _, _ in edges)


def test_registry_typed_sections_configure_plugin_parameters_and_deviations_carry_both_values():
    edges = _golden_edges()
    configures = {(source, target[1], edge.properties["match"]) for kind, source, target, edge in edges
                  if kind == "configures"}
    assert (("conf", "[HttpService_Ping] ThreadCount"), "HttpService.ThreadCount", "plugin_type") in configures
    deviation = next(edge for kind, source, _, edge in edges
                     if kind == "deviates_from_default" and source == ("conf", "[HttpService_Ping] ThreadCount"))
    assert deviation.properties == {"value": "4", "default": "1", "unit": None, "deviates": True, "variants": []}
    assert deviation.citations == [("rev-conf", 1, 14), ("rev-manual", 30, None)]
    unused = {(source[1], target) for kind, source, target, _ in edges if kind == "documented_unused"}
    # SendError is documented for HttpService, a type in use, but no file sets it.
    assert {target for source, target in unused if source == "HttpService.SendError"} == {
        ("file", "conf/app.ini"), ("file", "data/app.ini"), ("file", "worker/app.ini")}
    assert not any(source == "HttpService.ThreadCount" for source, _ in unused)


def test_redacted_values_are_never_compared():
    edges = _golden_edges()
    assert ("configures", ("conf", "[GeneralSettings] KeyStorePassword"), ("manual", "[GeneralSettings] KeyStorePassword")
            ) in {(kind, source, target) for kind, source, target, _ in edges}
    assert not any(kind in ("inconsistent_across", "deviates_from_default") and "KeyStorePassword" in source[1]
                   for kind, source, _, _ in edges)
    # One component's value looks like a credential URL and is redacted: it is not compared either.
    plain = _settings("conf", "500")
    secret = _settings("data", "500")
    url = next(row for row in plain if row.properties["key"] == "ProjectConfig")
    hidden = next(row for row in secret if row.properties["key"] == "ProjectConfig")
    url.properties["value"] = "jdbc:postgresql://db/shop"
    hidden.properties.update(value="[redacted]", redacted=True)
    parameters, documents = _manual()
    found = compute_linkage(plain + secret, parameters, documents, REGISTRY)
    assert not [edge for edge in found if edge.edge_type == "inconsistent_across"]


def test_documented_unused_only_for_scopes_in_use_and_inconsistencies_only_across_components():
    edges = _golden_edges()
    unused = {source[1] for kind, source, _, _ in edges if kind == "documented_unused"}
    assert "[Database?] Engine" not in unused  # no [Database…] section is configured anywhere
    # A [Cache1] section with only an undocumented key does not put the cache scope in use.
    settings = _settings("conf", "500")
    template = settings[0]
    settings.append(NodeRow(node_id("ConfiguredSetting", "repo:conf/app.ini|Cache1|Custom"), "ConfiguredSetting",
                            "rev-conf", 1, 40, "[Cache1] Custom",
                            {**template.properties, "section": "Cache1", "section_type": "Cache1", "key": "Custom",
                             "value": "1", "line": 40}))
    parameters, documents = _manual()
    found = compute_linkage(settings, parameters, documents, REGISTRY)
    cache = {row.node_id for row in parameters if row.properties.get("scope") == "Cache?"}
    assert not [edge for edge in found if edge.edge_type == "documented_unused" and edge.source_id in cache]
    first, second = _settings("conf", "500"), _settings("conf", "60000")
    for row in second:
        row.properties["path"] = "conf/other.ini"
    parameters, documents = _manual()
    found = compute_linkage(first + second, parameters, documents, REGISTRY)
    assert not [edge for edge in found if edge.edge_type == "inconsistent_across"]
