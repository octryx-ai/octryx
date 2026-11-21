"""Contract: the ServiceNow connector's record limit, assignment groups part.

Every ServiceNow read of the Workspace returns only records of the configured groups: the chat and Knowledge MCP
tools (the MCP tools run these same classes), the Knowledge Source Sync and the work item intake, on the Table API
(server-side condition, re-checked client-side) and on Scripted REST (client-side). Empty means no limit; a
limit never widens; the intake may only narrow the connector's list. Against the ``servicenow.test`` stub.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.knowledge.sources.sync.service_run import build_connector
from app.services.knowledge.sources.sync.servicenow_connection import servicenow_connection
from app.services.servicenow_record_limit import (
    NOTHING,
    RecordLimitError,
    collapse,
    narrowed,
    record_in_limit,
    record_limit,
)
from app.services.servicenow_record_limit import normalize_entries as normalize_groups
from app.services.servicenow_record_query import encoded_clause
from app.services.tool_config.validation import validate_tool_config
from app.tools.context import ToolContext
from tests.servicenow_intake_support import INCIDENTS_PATH, TABLE_PATH
from tests.servicenow_record_limit_support import DESK, DESK_ID, NET, NET_ID, as_all, sn  # noqa: F401
from tests.servicenow_stub_support import config, record, sys_id


def grouped(index: int, group: dict | str | None, prefix: str = "INC") -> dict:
    row = {**record(index, prefix), "assignment_group": group}
    if group is None:
        row.pop("assignment_group")
    return row


def _context(cfg: dict) -> ToolContext:
    return ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1", project_config=cfg,
                       workspace_root="/tmp")


async def _tool(name: str, params: dict, cfg: dict) -> dict:
    from app.tools.connectors import servicenow as tools

    tool = {"incidents": tools.ListServiceNowIncidentsTool, "records": tools.ListServiceNowRecordsTool,
            "record": tools.GetServiceNowRecordTool}[name]()
    return await tool.execute(params, _context(cfg))


TABLE = {"servicenow_api_style": "table", "servicenow_assignment_groups": ["Network Ops"]}


# --- Knowledge Source Sync ---------------------------------------------------------------------------------------


async def _list_all(connector) -> list:
    items, token = [], None
    while True:
        page = await connector.list_items(token, limit=50)
        items.extend(page.items)
        token = page.next_token
        if token is None:
            return items


# --- the limit itself --------------------------------------------------------------------------------------------


def test_groups_are_normalised_and_refused_when_they_could_widen_or_inject():
    assert normalize_groups(None) == [] and normalize_groups([]) == []
    assert normalize_groups([" Network  Ops ", "network ops", NET_ID.upper()]) == ["Network Ops", NET_ID]
    for bad in ("Network Ops", ["a^NQactive=true"], ["a,b"], ["javascript:gs.log()"], [""], [7], ["x" * 101],
                ["g"] * 51):
        with pytest.raises(RecordLimitError):
            normalize_groups(bad)


def test_an_invalid_stored_limit_matches_nothing_and_an_empty_one_is_no_limit():
    assert record_limit({}) is None and record_limit({"servicenow_assignment_groups": []}) is None
    assert record_limit({"servicenow_assignment_groups": "Network Ops"}) is NOTHING
    assert not record_in_limit({"assignment_group": "Network Ops"}, NOTHING)
    assert encoded_clause(NOTHING) == "sys_idISEMPTY^sys_idISNOTEMPTY"


def test_records_match_by_sys_id_or_display_name_and_never_without_a_group():
    limit = record_limit({"servicenow_assignment_groups": ["network ops", DESK_ID]})
    assert record_in_limit({"assignment_group": NET}, limit)  # name, case-insensitive
    assert record_in_limit({"assignment_group": {"value": DESK_ID, "link": "x"}}, limit)  # sys_id
    assert record_in_limit({"assignment_group": "Network Ops"}, limit)  # Scripted REST display value
    assert record_in_limit({"assignment_group": "", "assignment_group.name": "Network Ops"}, limit)  # dot-walk
    assert not record_in_limit({"assignment_group": {"display_value": "DBA", "value": "c" * 32}}, limit)
    assert not record_in_limit({"number": "INC1"}, limit)
    assert record_in_limit({"number": "INC1"}, None)
    assert encoded_clause(limit) == f"assignment_groupIN{DESK_ID}^ORassignment_group.nameSTARTSWITHnetwork ops"


def test_the_intake_may_only_narrow_the_connectors_groups():
    connector = {"servicenow_assignment_groups": ["Network Ops", "Service Desk"]}
    assert narrowed(connector, {}) == record_limit(connector)
    assert narrowed(connector, {"assignment_groups": ["service desk"]}).groups.entries == ("service desk",)
    with pytest.raises(RecordLimitError):
        narrowed(connector, {"assignment_groups": ["Network Ops", "DBA"]})
    # no connector limit: the intake narrows from everything
    assert narrowed({}, {"assignment_groups": ["DBA"]}).groups.entries == ("DBA",)


def test_display_all_records_collapse_to_the_asked_representation():
    row = {"number": {"display_value": "INC1", "value": "INC1"}, "assignment_group": NET}
    assert collapse(row, "true") == {"number": "INC1", "assignment_group": "Network Ops"}
    assert collapse(row, "false")["assignment_group"] == NET_ID
    assert collapse(row, "all") == row


def test_the_connector_save_refuses_an_invalid_group_list():
    base = {"servicenow_url": "https://servicenow.test", "servicenow_auth_mode": "bearer_token", "servicenow_token": "t"}
    validate_tool_config("servicenow", {**base, "servicenow_assignment_groups": ["Network Ops", NET_ID]})
    with pytest.raises(ValueError):
        validate_tool_config("servicenow", {**base, "servicenow_assignment_groups": ["a^NQb"]})
    with pytest.raises(ValueError):
        validate_tool_config("servicenow", {**base, "servicenow_assignment_groups": "Network Ops"})


async def test_table_api_listings_carry_the_condition_and_drop_other_groups(sn):  # noqa: F811
    # The stub ignores the query, like an instance that ignores a condition it cannot apply.
    sn.api_answer[TABLE_PATH] = (200, {"result": [as_all(grouped(1, NET)), as_all(grouped(2, DESK)),
                                                  as_all(grouped(3, None))]})
    result = await _tool("incidents", {"query": "active=true"}, config(**TABLE))
    _path, params, _auth = sn.api_requests[-1]
    assert params["sysparm_query"] == "assignment_group.nameSTARTSWITHNetwork Ops^active=true"
    assert params["sysparm_display_value"] == "all" and "assignment_group" in params["sysparm_fields"]
    assert [row["number"] for row in result["incidents"]] == ["INC0000001"]
    assert result["incidents"][0]["assignment_group"] == "Network Ops"  # the asked (display) representation


async def test_without_groups_the_table_api_request_is_unchanged(sn):  # noqa: F811
    sn.api_answer[TABLE_PATH] = (200, {"result": [grouped(1, "Service Desk")]})
    result = await _tool("records", {"table": "incident", "query": "active=true"},
                         config(servicenow_api_style="table"))
    _path, params, _auth = sn.api_requests[-1]
    assert (params["sysparm_query"], params["sysparm_display_value"]) == ("active=true", "true")
    assert result["count"] == 1


async def test_a_query_that_would_widen_is_refused_and_another_groups_record_is_not_found(sn):  # noqa: F811
    refused = await _tool("records", {"table": "incident", "query": "active=true^NQactive=false"}, config(**TABLE))
    assert refused["code"] == "servicenow_query_widens_group_limit" and sn.api_requests == []
    sn.api_answer[f"{TABLE_PATH}/{sys_id(2)}"] = (200, {"result": as_all(grouped(2, DESK))})
    hidden = await _tool("record", {"table": "incident", "sys_id": sys_id(2)}, config(**TABLE))
    assert hidden["code"] == "servicenow_record_not_found"
    sn.api_answer[f"{TABLE_PATH}/{sys_id(1)}"] = (200, {"result": as_all(grouped(1, NET))})
    shown = await _tool("record", {"table": "incident", "sys_id": sys_id(1), "display_value": "false"}, config(**TABLE))
    assert shown["record"]["assignment_group"] == NET_ID


async def test_scripted_listings_are_filtered_while_paging_to_the_limit(sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [grouped(i, "Network Ops" if i % 3 == 0 else "Service Desk") for i in range(1, 31)]
    cfg = config(servicenow_page_size=5, servicenow_assignment_groups=["network ops"])
    result = await _tool("incidents", {"limit": 4}, cfg)
    assert [row["number"] for row in result["incidents"]] == ["INC0000003", "INC0000006", "INC0000009", "INC0000012"]
    assert result["total"] is None and len(sn.api_requests) == 3  # 15 records read to keep 4
    everything = await _tool("incidents", {"limit": 4}, config(servicenow_page_size=5))
    assert everything["count"] == 4 and everything["total"] == 30


async def test_the_table_api_source_sync_lists_only_the_groups_records(sn):  # noqa: F811
    sn.api_answer[TABLE_PATH] = (200, {"result": [
        {**grouped(1, NET_ID), "assignment_group.name": "Network Ops", "sys_updated_on": "2026-10-01 10:00:00",
         "sys_mod_count": "1", "sys_domain": "global"},
        {**grouped(2, DESK_ID), "assignment_group.name": "Service Desk", "sys_updated_on": "2026-10-01 10:00:00",
         "sys_mod_count": "1", "sys_domain": "global"},
    ]})
    connection = servicenow_connection(config(**TABLE))
    items = await _list_all(build_connector(connection, SimpleNamespace(kind="servicenow",
                                                                        scope={"tables": ["incident"]})))
    assert [item.external_id for item in items] == [sys_id(1)]
    _path, params, _auth = sn.api_requests[-1]
    assert params["sysparm_query"].startswith("assignment_group.nameSTARTSWITHNetwork Ops^sys_idISNOTEMPTY")
    assert params["sysparm_fields"].endswith("assignment_group,assignment_group.name,business_service,business_service.name")


async def test_the_scripted_source_sync_lists_only_the_groups_records(sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [grouped(1, "Network Ops"), grouped(2, "Service Desk"), grouped(3, None)]
    connection = servicenow_connection(config(servicenow_assignment_groups=["Network Ops"]))
    items = await _list_all(build_connector(connection, SimpleNamespace(kind="servicenow",
                                                                        scope={"tables": ["incident"]})))
    assert [item.external_id for item in items] == [sys_id(1)]
    unlimited = servicenow_connection(config())
    assert len(await _list_all(build_connector(unlimited, SimpleNamespace(kind="servicenow",
                                                                          scope={"tables": ["incident"]})))) == 3
