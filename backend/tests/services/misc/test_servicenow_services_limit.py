"""Contract: services in the ServiceNow record limit, the filter mode, the query rule under a limit, newest-first
intake listings and the known-values suggestions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.knowledge.sources.sync.service_run import build_connector
from app.services.knowledge.sources.sync.servicenow_connection import servicenow_connection
from app.services.named_connections.resolver import connection_config
from app.services.named_connections.routes_model import EMPTY_ROUTES, ResolvedNamedConnection
from app.services.servicenow_record_limit import (
    NOTHING,
    RecordLimitError,
    narrowed,
    normalize_entries,
    record_in_limit,
    record_limit,
)
from app.services.servicenow_record_query import encoded_clause, widens
from app.services.tool_config.validation import validate_tool_config
from app.tools.context import ToolContext
from tests.servicenow_intake_support import INCIDENTS_PATH, TABLE_PATH
from tests.servicenow_stub_support import config, record, sys_id
from tests.support.servicenow_services_limit_support import CLOUD, DESK, row, sn  # noqa: F401

CHECKOUT_ID = "c" * 32


def _context(cfg: dict) -> ToolContext:
    return ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1", project_config=cfg,
                       workspace_root="/tmp")


async def _tool(name: str, params: dict, cfg: dict) -> dict:
    from app.tools.connectors import servicenow as tools

    tool = {"incidents": tools.ListServiceNowIncidentsTool, "records": tools.ListServiceNowRecordsTool}[name]()
    return await tool.execute(params, _context(cfg))


def test_names_match_after_collapsing_whitespace_and_sys_ids_exactly():
    limit = record_limit({"servicenow_assignment_groups": ["shop support desk"],
                          "servicenow_services": [CHECKOUT_ID]})
    assert record_in_limit({"assignment_group": DESK, "business_service": {"value": CHECKOUT_ID, "display_value": "Checkout"}},
                           limit)
    assert record_in_limit({"assignment_group": "Shop  Support\tDesk", "service": CHECKOUT_ID.upper()}, limit)
    assert not record_in_limit({"assignment_group": DESK, "service": "c" * 31 + "d"}, limit)
    assert not record_in_limit({"assignment_group": "Shop Support Desk Team", "service": CHECKOUT_ID}, limit)


def test_all_needs_every_list_and_any_never_widens_beyond_the_lists():
    both = {"servicenow_assignment_groups": [DESK], "servicenow_services": ["Checkout"]}
    every, either = record_limit(both), record_limit({**both, "servicenow_filter_mode": "any"})
    cases = {
        (DESK, "Checkout"): (True, True),
        (DESK, "Parcel Tracking"): (False, True),
        (CLOUD, "Checkout"): (False, True),
        (CLOUD, "Payment platform service - Checkout"): (False, False),
        (None, None): (False, False),
    }
    for (group, service), expected in cases.items():
        record = {key: value for key, value in (("assignment_group", group), ("service", service)) if value}
        assert (record_in_limit(record, every), record_in_limit(record, either)) == expected, (group, service)
    services_only = {"servicenow_services": ["Checkout"]}
    for mode in ("all", "any"):
        limit = record_limit({**services_only, "servicenow_filter_mode": mode})
        assert record_in_limit({"service": "checkout"}, limit) and not record_in_limit({"assignment_group": DESK}, limit)


def test_the_table_api_clause_is_and_per_list_or_one_or_group_and_fails_closed():
    both = {"servicenow_assignment_groups": [DESK, CHECKOUT_ID], "servicenow_services": ["Checkout"]}
    assert encoded_clause(record_limit(both)) == (
        f"assignment_groupIN{CHECKOUT_ID}^ORassignment_group.nameSTARTSWITHShop Support Desk"
        "^business_service.nameSTARTSWITHCheckout")
    assert encoded_clause(record_limit({**both, "servicenow_filter_mode": "any"})) == (
        f"assignment_groupIN{CHECKOUT_ID}^ORassignment_group.nameSTARTSWITHShop Support Desk"
        "^ORbusiness_service.nameSTARTSWITHCheckout")
    for invalid in ({"servicenow_services": "Checkout"}, {"servicenow_services": ["a^NQb"]},
                    {"servicenow_assignment_groups": [DESK], "servicenow_filter_mode": "or"}):
        assert record_limit(invalid) is NOTHING
    assert not record_in_limit({"assignment_group": DESK, "service": "Checkout"}, NOTHING)
    assert record_limit({"servicenow_services": [], "servicenow_filter_mode": "any"}) is None


def test_the_connector_save_validates_services_and_the_mode():
    base = {"servicenow_url": "https://servicenow.test", "servicenow_auth_mode": "bearer_token", "servicenow_token": "t"}
    validate_tool_config("servicenow", {**base, "servicenow_services": ["Checkout", CHECKOUT_ID],
                                        "servicenow_filter_mode": "any"})
    for bad in ({"servicenow_services": ["a,b"]}, {"servicenow_services": "Checkout"}, {"servicenow_filter_mode": "or"}):
        with pytest.raises(ValueError):
            validate_tool_config("servicenow", {**base, **bad})
    assert normalize_entries([" Checkout ", "checkout", "Parcel  Tracking"], field="servicenow_services") == ["Checkout", "Parcel Tracking"]


def test_intake_overrides_only_narrow_and_never_add_an_ored_list():
    groups_only = {"servicenow_assignment_groups": [DESK, CLOUD]}
    added = narrowed(groups_only, {"services": ["Checkout"]})
    assert added.groups.entries == ("Shop Support Desk", CLOUD) and added.services.entries == ("Checkout",)
    with pytest.raises(RecordLimitError):
        narrowed({**groups_only, "servicenow_filter_mode": "any"}, {"services": ["Checkout"]})
    with pytest.raises(RecordLimitError):
        narrowed({"servicenow_services": ["Checkout"]}, {"services": ["Parcel Tracking"]})
    assert narrowed({"servicenow_services": ["Checkout", "Parcel Tracking"], "servicenow_filter_mode": "any"},
                    {"services": ["checkout"]}).services.entries == ("checkout",)
    assert narrowed({"servicenow_services": "Checkout"}, {}) is NOTHING


def test_a_query_under_a_limit_must_be_plain_narrowing_conditions():
    for refused in ("ORactive=true", "^ORactive=true", "active=true^NQactive=false", "NQactive=true",
                    "RLQUERYsomething", "short_descriptionLIKEjavascript:x", "EQ", "^active=true"):
        assert widens(refused), refused
    for allowed in (None, "", "active=true", "active=true^ORpriority=1", "active=true^ORDERBYDESCnumber",
                    "ORDERBYnumber", "assignment_group.name=Network Ops"):
        assert not widens(allowed), allowed


async def test_a_leading_or_query_is_refused_under_a_limit(sn):  # noqa: F811
    cfg = config(servicenow_api_style="table", servicenow_services=["Checkout"])
    refused = await _tool("records", {"table": "incident", "query": "ORactive=false"}, cfg)
    assert refused["code"] == "servicenow_query_widens_group_limit" and sn.api_requests == []
    sn.api_answer[TABLE_PATH] = (200, {"result": []})
    unlimited = await _tool("records", {"table": "incident", "query": "ORactive=false"},
                            config(servicenow_api_style="table"))
    assert "error" not in unlimited


async def test_table_api_tools_and_both_lists_and_recheck_each_record(sn):  # noqa: F811
    def all_values(index, group, service):
        return {**{key: {"display_value": value, "value": value} for key, value in record(index).items()},
                "assignment_group": {"display_value": group, "value": "a" * 32},
                "business_service": {"display_value": service, "value": CHECKOUT_ID}}

    sn.api_answer[TABLE_PATH] = (200, {"result": [all_values(1, DESK, "Checkout"), all_values(2, DESK, "Parcel Tracking"),
                                                  all_values(3, CLOUD, "Checkout")]})
    cfg = config(servicenow_api_style="table", servicenow_assignment_groups=["Shop Support Desk"],
                 servicenow_services=["Checkout"])
    result = await _tool("incidents", {}, cfg)
    _path, params, _auth = sn.api_requests[-1]
    assert params["sysparm_query"] == ("assignment_group.nameSTARTSWITHShop Support Desk"
                                       "^business_service.nameSTARTSWITHCheckout")
    assert "business_service" in params["sysparm_fields"].split(",")
    assert [item["number"] for item in result["incidents"]] == ["INC0000001"]


async def test_scripted_tools_and_source_sync_filter_by_service(sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [row(1, DESK, "Checkout"), row(2, DESK, "Payment platform service - Checkout"),
                               row(3, CLOUD, "Checkout"), row(4, DESK, None)]
    cfg = config(servicenow_assignment_groups=["Shop Support Desk"], servicenow_services=["checkout"])
    listed = await _tool("incidents", {"limit": 10}, cfg)
    assert [item["number"] for item in listed["incidents"]] == ["INC0000001"]
    either = await _tool("incidents", {"limit": 10}, {**cfg, "servicenow_filter_mode": "any"})
    assert [item["number"] for item in either["incidents"]] == ["INC0000001", "INC0000002", "INC0000003",
                                                                 "INC0000004"]
    connector = build_connector(servicenow_connection(cfg), SimpleNamespace(kind="servicenow",
                                                                            scope={"tables": ["incident"]}))
    page = await connector.list_items(None, limit=50)
    assert [item.external_id for item in page.items] == [sys_id(1)]


def test_a_named_connection_keeps_the_default_entrys_limit():
    base = {"servicenow_url": "https://default.test", "servicenow_auth_mode": "bearer_token", "servicenow_token": "t", "servicenow_services": ["Checkout"],
            "servicenow_assignment_groups": [DESK], "servicenow_filter_mode": "all"}
    named = ResolvedNamedConnection(id="n1", tool_name="servicenow", name="emea", scope="workspace", bound_scopes=frozenset({"incident"}),
                                    config={"servicenow_url": "https://emea.test", "servicenow_auth_mode": "bearer_token", "servicenow_token": "u"})
    scoped = connection_config(base, "servicenow", EMPTY_ROUTES, named)
    assert scoped["servicenow_url"] == "https://emea.test"
    assert record_limit(scoped) == record_limit(base) and record_limit(scoped) is not None
