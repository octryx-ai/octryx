"""Custom REST connector: SAP and OData.

A published SAP Gateway OData spec ("Business Partner"; ``tests/fixtures/odata`` is a small self-written spec of the
same shape) must not read as an unusable first server ``https://:/sap/...``, with op_keys cut to
``get_a_business_partner_business``, a ``$select`` parameter no model provider accepts as a tool property, no records
or next page for OData answers, and PATCH operations SAP Gateway refuses without a CSRF token. These tests prove each
fix end to end through the import, the executor and the real pinned egress transport, plus two admin API items.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from app.services.rest_connector.common import OP_KEY_RE
from app.services.rest_connector.definitions import create_definition, update_definition
from app.services.rest_connector.executor import execute_rest_tool
from app.services.rest_connector.op_keys import MAX_KEY
from app.services.rest_connector.openapi_reader import read_openapi
from app.services.rest_connector.param_names import TOOL_PARAM_NAME_RE, alias_parameters
from app.services.rest_connector.tool_surface import list_rest_tool_definitions
from tests.egress_support import public_source_dns  # noqa: F401 - fixture
from tests.rest_connector_odata_support import _admin, _context, _import_sap, _sap, api  # noqa: F401

pytestmark = pytest.mark.usefixtures("public_source_dns")


SANDBOX = "https://sandbox.example.test/s4hanacloud/sap/opu/odata/sap/API_BUSINESS_PARTNER"


@pytest.mark.parametrize("fixture", ["business-partner.yaml", "business-partner-with-select.yaml"])
def test_the_sap_business_partner_spec_reads_with_a_usable_server_readable_keys_and_basic_auth(fixture):
    spec = read_openapi(_sap(fixture))

    # {host}:{port} with empty defaults is left out with a warning naming it; the sandbox stays.
    assert spec["servers"] == [SANDBOX]
    assert any("https://:/sap/opu/odata/sap/API_BUSINESS_PARTNER" in warning for warning in spec["warnings"])
    assert {operation["op_key"] for operation in spec["operations"]} == {
        "get_a_business_partner_by_key", "patch_a_business_partner_by_key"}
    assert spec["auth"]["scheme"] == "basic"
    # x-sap-api-type ODATA with a PATCH: the token fetch SAP Gateway needs is on by default.
    assert spec["odata_version"] == "v2" and spec["auth"]["csrf"] == {"fetch": True, "header": "x-csrf-token"}


def test_server_variables_take_their_defaults_and_a_server_still_without_host_is_dropped():
    spec = read_openapi(json.dumps({
        "openapi": "3.0.0", "info": {"title": "T"},
        "servers": [{"url": "https://{tenant}.example.test:{port}/api",
                     "variables": {"tenant": {"default": "acme"}, "port": {"default": "8443"}}},
                    {"url": "https://{host}/api", "variables": {"host": {"default": ""}}},
                    {"url": "ftp://files.example.test"}],
        "paths": {"/x": {"get": {}}},
    }))

    assert spec["servers"] == ["https://acme.example.test:8443/api"]
    assert sum("was left out" in warning for warning in spec["warnings"]) == 2


def test_keys_without_operation_id_are_readable_unique_and_the_same_on_every_read():
    entity = "/A_BusinessPartnerAddress(BusinessPartner='{BusinessPartner}',AddressID='{AddressID}')"
    paths = {
        "/A_BusinessPartner": ["get", "post"],
        "/A_BusinessPartner('{BusinessPartner}')": ["get", "patch"],
        "/A_BusinessPartner('{BusinessPartner}')/to_BusinessPartnerAddress": ["get", "post"],
        entity: ["get", "patch", "delete"],
        f"{entity}/to_EmailAddress": ["get", "post"],
        f"{entity}/to_FaxNumber": ["get"],
        f"{entity}/to_AddressUsage": ["get", "post"],
        "/A_Business_PartnerAddress": ["get"],  # derives the same base key as the entity set below
        "/A_BusinessPartnerAddress": ["get"],
        "/users/{id}/orders": ["get"],
    }
    document = json.dumps({"openapi": "3.0.0", "info": {"title": "BP"},
                           "paths": {path: {method: {} for method in methods} for path, methods in paths.items()}})

    first = [operation["op_key"] for operation in read_openapi(document)["operations"]]
    second = [operation["op_key"] for operation in read_openapi(document)["operations"]]

    assert first == second
    assert len(set(first)) == len(first) == sum(len(methods) for methods in paths.values())
    assert all(OP_KEY_RE.fullmatch(key) and len(key) <= MAX_KEY for key in first)
    assert {"get_a_business_partner", "post_a_business_partner", "get_a_business_partner_by_key",
            "get_abp_address_to_email_address", "get_abp_address_to_fax_number", "post_abp_address_address_usage",
            "get_users_by_id_orders"} <= set(first)
    # Both entity sets derive get_a_business_partner_address: the second gets the hash of its own method and path.
    collided = sorted(key for key in first if key.startswith("get_a_business_partner_ad"))
    assert collided[0] == "get_a_business_partner_ad_" + collided[0][-6:] and len(collided[0]) == MAX_KEY
    assert collided[1] == "get_a_business_partner_address"


def test_dollar_and_other_invalid_parameter_names_get_aliases_that_fit_the_provider_limits():
    aliased = alias_parameters([
        {"name": "filter", "in": "query"}, {"name": "$filter", "in": "query"}, {"name": "$top", "in": "query"},
        {"name": "page[size]", "in": "query"}, {"name": "x" * 80, "in": "query"},
    ])

    names = [param["name"] for param in aliased]
    assert names[:4] == ["filter", "odata_filter", "top", "page_size"]
    assert all(TOOL_PARAM_NAME_RE.fullmatch(name) for name in names)
    assert [param.get("wire_name") for param in aliased[:4]] == [None, "$filter", "$top", "page[size]"]
    assert alias_parameters(aliased) == aliased  # stable: a stored alias stays as it is


@pytest.mark.asyncio
async def test_the_model_sends_select_and_the_request_carries_dollar_select_as_one_comma_list(db, api):  # noqa: F811
    api.answer = lambda request: httpx.Response(200, json={"d": {"BusinessPartner": "11"}})
    await _import_sap(db, "business-partner-with-select.yaml", enable=("get_a_business_partner_by_key",))
    admin = await _admin(db)

    tools = await list_rest_tool_definitions(db, _context(db, admin.id))
    properties = tools[0]["function"]["parameters"]["properties"]
    assert set(properties) == {"BusinessPartner", "select"}
    assert all(TOOL_PARAM_NAME_RE.fullmatch(name) for name in properties)

    result = await execute_rest_tool("rest__bp__get_a_business_partner_by_key",
                                     {"BusinessPartner": "11", "select": ["BusinessPartner", "Customer"]},
                                     _context(db, admin.id))

    assert result["status_code"] == 200, result
    sent = api.requests[0].url
    assert sent.path == "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner('11')"
    assert sent.params.get_list("$select") == ["BusinessPartner,Customer"] and "select" not in sent.params


@pytest.mark.asyncio
async def test_servers_are_validated_with_field_and_index(db):
    admin = await _admin(db)
    definition = await create_definition(db, {"key": "srv"}, actor_user_id=admin.id)

    with pytest.raises(HTTPException) as refused:
        await update_definition(db, definition["id"], {"servers": [SANDBOX, "https://:/sap/opu"]})

    assert refused.value.status_code == 422
    assert refused.value.detail[0]["loc"] == ["body", "servers", 1]
    saved = await update_definition(db, definition["id"], {"servers": [SANDBOX + "/"]})
    assert saved["servers"] == [SANDBOX]
