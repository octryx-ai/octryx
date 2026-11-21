"""Contract: ServiceNow Scripted REST endpoints instead of the Table API (``servicenow_api_style``).

Against a stub instance (``servicenow_stub_support.py``): paging across pages and the 200 cap, the list-key
auto-detect, normalisation and links, the generic table tools refused, a query refused, the connection test per
endpoint, path and page-size validation, an unknown style, and the Knowledge sync on the same switch.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.servicenow_scripted import ScriptedEndpointError, normalize_record, parse_page
from app.services.servicenow_scripted_fetch import fetch_records
from app.tools.context import ToolContext
from tests.servicenow_scripted_api_support import sn  # noqa: F401
from tests.servicenow_stub_support import CHANGES_PATH, INCIDENTS_PATH, SN_URL, config, record, sys_id


def _context(cfg: dict) -> ToolContext:
    return ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1", project_config=cfg,
                       workspace_root="/tmp")


async def _tool(name: str, params: dict | None = None, cfg: dict | None = None) -> dict:
    from app.tools.connectors import servicenow as tools

    tool = {"incidents": tools.ListServiceNowIncidentsTool, "changes": tools.ListServiceNowChangesTool,
            "records": tools.ListServiceNowRecordsTool, "record": tools.GetServiceNowRecordTool}[name]()
    return await tool.execute(params or {}, _context(cfg or config()))


# --- tools --------------------------------------------------------------------------------------------------


async def test_incidents_page_through_the_configured_endpoint_until_the_limit(sn):  # noqa: F811
    result = await _tool("incidents", {"limit": 90}, config(servicenow_page_size=40))
    assert result["count"] == 90 and result["total"] == 95 and result["api_style"] == "scripted"
    pages = [(params["sysparm_limit"], params["sysparm_offset"]) for path, params, _ in sn.api_requests]
    assert pages == [("40", "0"), ("40", "40"), ("10", "80")]
    assert {path for path, _params, _auth in sn.api_requests} == {INCIDENTS_PATH}


async def test_paging_stops_at_the_endpoints_total(sn):  # noqa: F811
    result = await _tool("changes", {"limit": 50})
    assert result["count"] == 2 and result["total"] == 2 and len(sn.api_requests) == 1
    assert sn.api_requests[0][0] == CHANGES_PATH


async def test_a_full_last_page_stops_at_the_total_without_another_request(sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = sn.data[INCIDENTS_PATH][:40]
    result = await _tool("incidents", {"limit": 100}, config(servicenow_page_size=20))
    assert result["count"] == 40 and len(sn.api_requests) == 2


async def test_records_are_normalised_with_links_and_pass_through_fields(sn):  # noqa: F811
    incident = (await _tool("incidents", {"limit": 1}))["incidents"][0]
    assert incident["sys_id"] == sys_id(1) and incident["number"] == "INC0000001"
    assert incident["state"] == "New", "display values are flattened"
    assert incident["u_custom"] == "custom-1" and incident["description"] == "Details"
    assert incident["url"] == f"{SN_URL}/nav_to.do?uri=incident.do%3Fsys_id%3D{sys_id(1)}"
    change = (await _tool("changes", {"limit": 1}))["changes"][0]
    assert "uri=change_request.do" in change["url"]


@pytest.mark.parametrize("name", ["records", "record"])
async def test_the_generic_table_tools_are_refused_and_never_fall_back(sn, name):  # noqa: F811
    result = await _tool(name, {"table": "incident", "sys_id": sys_id(1)})
    assert result["code"] == "servicenow_table_api_disabled"
    assert "Scripted REST API; use the incident/change tools" in result["error"]
    assert sn.api_requests == [] and sn.token_forms == []


async def test_a_query_filter_is_refused_not_dropped(sn):  # noqa: F811
    result = await _tool("incidents", {"query": "active=true"})
    assert result["code"] == "servicenow_query_unsupported" and sn.api_requests == []


async def test_an_unconfigured_kind_and_an_unknown_style_are_coded(sn):  # noqa: F811
    no_changes = config(servicenow_changes_path="")
    assert (await _tool("changes", cfg=no_changes))["code"] == "servicenow_endpoint_not_configured"
    unknown = await _tool("records", {"table": "incident"}, config(servicenow_api_style="graphql"))
    assert unknown["code"] == "servicenow_api_invalid"
    assert (await _tool("incidents", cfg=config(servicenow_api_style="graphql")))["code"] == "servicenow_api_invalid"


async def test_an_endpoint_error_status_is_coded(sn):  # noqa: F811
    sn.api_answer[INCIDENTS_PATH] = (403, {"error": {"message": "secret detail"}})
    result = await _tool("incidents")
    assert result["code"] == "servicenow_endpoint_http_status" and "403" in result["error"]
    assert "secret detail" not in str(result)


async def test_the_table_style_is_unchanged(sn):  # noqa: F811
    table = config(servicenow_api_style="table")
    sn.api_answer["/api/now/table/incident"] = (200, {"result": [record(1)]})
    result = await _tool("records", {"table": "incident"}, table)
    assert "code" not in result and sn.api_requests[0][0] == "/api/now/table/incident"


# --- paging, shape, normalisation -----------------------------------------------------------------------------


async def test_the_page_size_is_capped_at_200(sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [record(i) for i in range(1, 451)]
    transport = sn.transport()  # no grant yet: the stub expects tok-0
    async with httpx.AsyncClient(transport=transport) as client:
        records, total = await fetch_records(client, SN_URL, INCIDENTS_PATH, "incident", limit=450, page_size=500,
                                             headers={"Authorization": "Bearer tok-0"})
    assert len(records) == 450 and total == 450
    assert [params["sysparm_limit"] for _path, params, _auth in sn.api_requests] == ["200", "200", "50"]


@pytest.mark.parametrize(("payload", "count"), [
    ({"result": {"items": [record(1)], "total": 1}}, 1),
    ({"result": {"incidents": [record(1)], "attachments": [], "total": 1}}, 1),
    ({"result": [record(1), record(2)]}, 2),
])
def test_the_list_key_is_auto_detected(payload, count):
    assert len(parse_page(payload, "incident").records) == count


@pytest.mark.parametrize(("payload", "code"), [
    ({"result": {"a": [], "b": []}}, "servicenow_endpoint_unexpected_shape"),
    ({"result": {"total": 3}}, "servicenow_endpoint_unexpected_shape"),
    ({"result": {"incidents": ["not-a-record"]}}, "servicenow_endpoint_unexpected_shape"),
    ({"data": []}, "servicenow_endpoint_unexpected_shape"),
    (None, "servicenow_endpoint_empty_answer"),
    ({}, "servicenow_endpoint_empty_answer"),
])
def test_an_unexpected_shape_is_coded(payload, code):
    with pytest.raises(ScriptedEndpointError) as refused:
        parse_page(payload, "incident")
    assert refused.value.code == code


def test_the_total_is_read_from_the_metadata():
    assert parse_page({"result": {"changes": [], "total": "17"}}, "change_request").total == 17
    assert parse_page({"result": {"changes": [], "total": True}}, "change_request").total is None


def test_a_record_without_an_alphanumeric_sys_id_has_no_link():
    assert normalize_record({"sys_id": "../x"}, "incident", SN_URL)["url"] is None
