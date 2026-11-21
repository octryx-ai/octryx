"""Scripted REST configuration is validated on save, the connection test reports each endpoint or the Table API, and knowledge sync lists both endpoints with stable markers and refuses scopes without a scripted equivalent."""

from __future__ import annotations

import httpx
import pytest

from app.services.atlassian_auth_modes import AtlassianAuthConfigError
from app.services.atlassian_auth_validation import validate_auth_config
from app.services.connector_test.servicenow import test_servicenow_connection as connection_test
from app.services.knowledge.sources.sync.contract import (
    REASON_SCOPE_NOT_ALLOWED,
    REASON_SOURCE_CONTRACT_VIOLATION,
    ConnectorError,
)
from app.services.knowledge.sources.sync.servicenow_connection import servicenow_connection
from app.services.servicenow_scripted import path_problem
from tests.servicenow_scripted_api_support import sn  # noqa: F401
from tests.servicenow_stub_support import CHANGES_PATH, INCIDENTS_PATH, SN_URL, config, record, sys_id

# --- Knowledge sync ----------------------------------------------------------------------------------------------


def _source(tables=("incident", "change_request"), **scope):
    from app.services.knowledge.sources.sync.servicenow_scripted_source import ServiceNowScriptedConnector

    return ServiceNowScriptedConnector(servicenow_connection(config(servicenow_page_size=40)), tables=tables,
                                       **scope)


# --- validation -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("path", "ok"), [
    ("/api/x_test/integration/incidents", True),
    ("/api/x_test/v1/changes_2.list", True),
    ("https://servicenow.test/api/x/incidents", False),
    ("//servicenow.test/api/x/incidents", False),
    ("/api//x/incidents", False),
    ("/api/x/../now/table/incident", False),
    ("/api/x/incidents?sysparm_query=active=true", False),
    ("/api/x/incidents#top", False),
    ("/now/table/incident", False),
    ("api/x/incidents", False),
    ("/api/x/inci dents", False),
    ("", False),
    (None, False),
])
def test_scripted_paths_are_validated(path, ok):
    assert (path_problem(path) is None) is ok


@pytest.mark.parametrize("change", [
    {"servicenow_incidents_path": "https://servicenow.test/api/x/i"},
    {"servicenow_journal_path": "/api/../x"},
    {"servicenow_incidents_path": "", "servicenow_changes_path": ""},
    {"servicenow_page_size": 201},
    {"servicenow_page_size": 0},
    {"servicenow_page_size": "100"},
    {"servicenow_api_style": "graphql"},
])
def test_save_validation_refuses_a_bad_scripted_configuration(change):
    with pytest.raises(AtlassianAuthConfigError) as refused:
        validate_auth_config("servicenow", config(**change))
    assert refused.value.code == "servicenow_api_invalid"


def test_a_valid_scripted_configuration_and_the_table_style_pass():
    validate_auth_config("servicenow", config(servicenow_page_size=200, servicenow_journal_path="/api/x/journal"))
    validate_auth_config("servicenow", config(servicenow_api_style="table", servicenow_incidents_path=""))
    validate_auth_config("servicenow", {"servicenow_auth_mode": "bearer_token", "servicenow_token": "tok"})


# --- connection test ------------------------------------------------------------------------------------------


async def test_the_connection_test_reports_each_endpoint(sn):  # noqa: F811
    result = await connection_test(config(), httpx_module=httpx)
    assert result["ok"] is True
    assert result["endpoints"] == {"incident": {"ok": True, "total": 95}, "change_request": {"ok": True, "total": 2}}
    assert {params["sysparm_limit"] for _path, params, _auth in sn.api_requests} == {"1"}
    sn.api_answer[CHANGES_PATH] = (500, None)
    sn.api_answer[INCIDENTS_PATH] = (200, {"result": {"a": [], "b": []}})
    failed = await connection_test(config(), httpx_module=httpx)
    assert failed["ok"] is False
    assert failed["endpoints"]["change_request"] == {"ok": False, "code": "servicenow_endpoint_http_status",
                                                     "http_status": 500}
    assert failed["endpoints"]["incident"]["code"] == "servicenow_endpoint_unexpected_shape"


async def test_the_table_style_connection_test_reads_the_table_api(sn):  # noqa: F811
    sn.data["/api/now/table/incident"] = [record(1)]
    sn.list_keys["/api/now/table/incident"] = "unused"
    result = await connection_test(config(servicenow_api_style="table"), httpx_module=httpx)
    assert result["ok"] is True and sn.api_requests[0][0] == "/api/now/table/incident"


async def test_an_invalid_configuration_is_refused_before_any_request(sn):  # noqa: F811
    result = await connection_test(config(servicenow_incidents_path="/api/../x"), httpx_module=httpx)
    assert result["ok"] is False and sn.api_requests == [] and sn.token_forms == []


async def test_knowledge_sync_lists_both_endpoints_with_links_and_renders_records(sn):  # noqa: F811
    from types import SimpleNamespace

    from app.services.knowledge.sources.sync.service_run import build_connector
    from app.services.knowledge.sources.sync.servicenow_scripted_source import ServiceNowScriptedConnector

    row = SimpleNamespace(kind="servicenow", scope={"tables": ["incident", "change_request"]})
    connector = build_connector(servicenow_connection(config(servicenow_page_size=40)), row)
    assert isinstance(connector, ServiceNowScriptedConnector)
    items, token, pages = [], None, 0
    while True:
        page = await connector.list_items(token, limit=100)
        items.extend(page.items)
        pages, token = pages + 1, page.next_token
        if token is None:
            break
    assert len(items) == 97 and pages == 4  # 40 + 40 + 15 incidents, 2 changes
    first = items[0]
    assert first.external_id == sys_id(1) and first.title == "INC0000001: Record 1"
    assert first.source_url == f"{SN_URL}/nav_to.do?uri=incident.do%3Fsys_id%3D{sys_id(1)}"
    assert first.acl.audience == "scope" and first.version_marker.startswith("sha256:")
    content = await connector.fetch(items[-1])
    assert b"CHG0001002" in content.data and content.media_type == "text/markdown"
    assert all(path in (INCIDENTS_PATH, CHANGES_PATH) for path, _params, _auth in sn.api_requests)


async def test_knowledge_records_keep_the_domain_rule_and_a_stable_marker(sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [{**record(1), "sys_domain": "tenant-a", "sys_updated_on": "2026-10-02 08:00:00",
                                "sys_mod_count": "4"}]
    page = await _source(("incident",)).list_items(None, limit=10)
    item = page.items[0]
    assert item.acl.audience == "restricted" and item.version_marker == "4@2026-10-02 08:00:00"


@pytest.mark.parametrize("scope", [
    {"knowledge_bases": (sys_id(5),)},
    {"record_filter": "active=true"},
    {"tables": ("problem",)},
])
def test_knowledge_scopes_without_a_scripted_equivalent_are_refused(sn, scope):  # noqa: F811
    tables = scope.pop("tables", ("incident",))
    with pytest.raises(ConnectorError) as refused:
        _source(tables, **scope)
    assert refused.value.reason == REASON_SCOPE_NOT_ALLOWED


async def test_a_knowledge_record_without_a_valid_sys_id_breaks_the_contract(sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [{**record(1), "sys_id": "not-hex"}]
    with pytest.raises(ConnectorError) as refused:
        await _source(("incident",)).list_items(None, limit=10)
    assert refused.value.reason == REASON_SOURCE_CONTRACT_VIOLATION


def test_the_table_style_knowledge_connection_has_no_scripted_api():
    assert servicenow_connection(config(servicenow_api_style="table")).api is None
    with pytest.raises(ConnectorError):
        servicenow_connection(config(servicenow_incidents_path="https://servicenow.test/api/x"))


async def test_the_connection_test_names_an_invalid_auth_field(sn):  # noqa: F811
    result = await connection_test(config(servicenow_token_url="http://servicenow.test/oauth_token.do"),
                                   httpx_module=httpx)
    assert result["ok"] is False and "servicenow_token_url" in result["summary"]
    assert sn.api_requests == [] and sn.token_forms == []
