"""OData presets find records and follow the next page, writes fetch the SAP CSRF token, batch operations stay disabled, and the admin API filters calls and lets each operation override the preset."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import RestApiCallRun
from app.services.rest_connector.connections import create_connection
from app.services.rest_connector.definitions import (
    create_definition,
    import_definition,
    recent_calls,
    update_definition,
    update_operation,
)
from app.services.rest_connector.executor import execute_rest_tool
from tests.conftest import ADMIN_PASSWORD
from tests.egress_support import public_source_dns  # noqa: F401 - fixture
from tests.services.rest_connector.rest_connector_odata_support import (  # noqa: F401
    GRANT,
    SAP_ROOT,
    _admin,
    _context,
    _import_sap,
    api,
)
from tests.support.rest_connector_support import SECRET

pytestmark = pytest.mark.usefixtures("public_source_dns")


async def _people(db, preset: str) -> tuple[dict, dict]:
    admin = await _admin(db)
    definition = await create_definition(db, {"key": "people", "auth": {"scheme": "none"}, "operations": [
        {"op_key": "list_people", "method": "GET", "path": "/People",
         "parameters": [{"name": "$top", "in": "query", "schema": {"type": "integer"}}]}]}, actor_user_id=admin.id)
    await create_connection(db, definition["id"], {"base_url": "https://odata.example.test/svc"})
    operation = await update_operation(db, definition["id"], definition["operations"][0]["id"],
                                       {"enabled": True, "grants": GRANT, "preset": preset})
    return definition, operation


def _csrf_api(api, *, write_answers: list[httpx.Response]):  # noqa: F811
    tokens = iter(["T1", "T2"])
    writes = iter(write_answers)

    def answer(request):
        if request.method == "GET":
            assert request.headers["x-csrf-token"] == "Fetch" and request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, headers=[("x-csrf-token", next(tokens)),
                                                ("set-cookie", "SAP_SESSIONID_X=sess-COOKIE-42; path=/")])
        return next(writes)

    api.answer = answer


@pytest.mark.asyncio
@pytest.mark.parametrize(("preset", "page", "next_key"), [
    ("odata_v2", lambda records, link: {"d": {"results": records, "__next": link}}, "$skiptoken"),
    ("odata_v4", lambda records, link: {"value": records, "@odata.nextLink": link}, "$skiptoken"),
])
async def test_odata_presets_find_the_records_and_follow_the_next_page(db, api, preset, page, next_key):  # noqa: F811
    def answer(request):
        if next_key in request.url.params:
            return httpx.Response(200, json=page([{"Name": "C"}], None))
        return httpx.Response(200, json=page([{"Name": "A"}, {"Name": "B"}],
                                             "https://odata.example.test/svc/People?$skiptoken=2"))

    api.answer = answer
    _, operation = await _people(db, preset)
    assert operation["preset"] == preset
    admin = await _admin(db)

    first = await execute_rest_tool("rest__people__list_people", {"top": 2}, _context(db, admin.id))
    assert first["record_count"] == 2 and first["next_cursor"], first
    assert api.requests[0].url.params.get("$top") == "2"
    second = await execute_rest_tool("rest__people__list_people", {"cursor": first["next_cursor"]},
                                     _context(db, admin.id))

    assert second["record_count"] == 1 and second["next_cursor"] is None, second
    assert api.requests[1].url.params.get("$skiptoken") == "2"


@pytest.mark.asyncio
async def test_an_odata_import_prefills_the_v2_preset_for_collection_reads_only(db):
    admin = await _admin(db)
    document = {"openapi": "3.0.0", "info": {"title": "S"}, "x-sap-api-type": "ODATA",
                "servers": [{"url": SAP_ROOT}],
                "paths": {"/A_X": {"get": {}}, "/A_X('{K}')": {"get": {}}, "/A_X/$count": {"get": {}}}}

    definition = await import_definition(db, {"key": "sx", "spec_text": json.dumps(document)}, actor_user_id=admin.id)

    presets = {operation["path"]: operation["preset"] for operation in definition["operations"]}
    assert presets == {"/A_X": "odata_v2", "/A_X('{K}')": "", "/A_X/$count": ""}


@pytest.mark.asyncio
async def test_a_write_fetches_the_csrf_token_and_refetches_once_when_sap_says_required(db, api):  # noqa: F811
    required = httpx.Response(403, headers={"x-csrf-token": "Required"}, json={"error": "CSRF token validation"})
    _csrf_api(api, write_answers=[required, httpx.Response(204)])
    await _import_sap(db, "business-partner.yaml", enable=("patch_a_business_partner_by_key",))
    admin = await _admin(db)

    result = await execute_rest_tool("rest__bp__patch_a_business_partner_by_key",
                                     {"BusinessPartner": "11", "body": {"FirstName": "Ada"}}, _context(db, admin.id))

    assert result["status_code"] == 204, result
    assert [(request.method, request.url.path) for request in api.requests] == [
        ("GET", "/sap/opu/odata/sap/API_BUSINESS_PARTNER/"),
        ("PATCH", "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner('11')"),
        ("GET", "/sap/opu/odata/sap/API_BUSINESS_PARTNER/"),
        ("PATCH", "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner('11')"),
    ]
    first_write, second_write = api.requests[1], api.requests[3]
    assert first_write.headers["x-csrf-token"] == "T1" and second_write.headers["x-csrf-token"] == "T2"
    assert "SAP_SESSIONID_X=sess-COOKIE-42" in second_write.headers["cookie"]
    runs = list((await db.execute(select(RestApiCallRun))).scalars().all())
    for leaked in ("sess-COOKIE-42", "T2", SECRET):
        assert leaked not in json.dumps(result, default=str)
        assert all(leaked not in json.dumps([run.error, run.arguments_json, run.scope_json]) for run in runs)


@pytest.mark.asyncio
async def test_a_403_without_required_is_not_refetched_and_a_read_fetches_no_token(db, api):  # noqa: F811
    _csrf_api(api, write_answers=[httpx.Response(403, json={"error": "no authorization"})])
    await _import_sap(db, "business-partner.yaml",
                      enable=("patch_a_business_partner_by_key", "get_a_business_partner_by_key"))
    admin = await _admin(db)

    refused = await execute_rest_tool("rest__bp__patch_a_business_partner_by_key",
                                      {"BusinessPartner": "11", "body": {}}, _context(db, admin.id))
    assert refused["code"] == "http_error" and len(api.requests) == 2

    api.answer = lambda request: httpx.Response(200, json={"d": {}})
    await execute_rest_tool("rest__bp__get_a_business_partner_by_key", {"BusinessPartner": "11"},
                            _context(db, admin.id))
    assert "x-csrf-token" not in api.requests[2].headers


@pytest.mark.asyncio
async def test_an_odata_batch_operation_is_marked_and_cannot_be_enabled(db):
    admin = await _admin(db)
    document = {"openapi": "3.0.0", "info": {"title": "S"}, "servers": [{"url": SAP_ROOT}], "paths": {
        "/$batch": {"post": {"requestBody": {"content": {"multipart/mixed;boundary=batch": {"schema": {}}}}}},
        "/A_X": {"get": {}}}}

    definition = await import_definition(db, {"key": "sb", "spec_text": json.dumps(document)}, actor_user_id=admin.id)

    batch = next(operation for operation in definition["operations"] if operation["path"] == "/$batch")
    assert batch["unsupported"] == "odata_batch"
    assert any(batch["op_key"] in warning and "$batch" in warning for warning in definition["warnings"])
    with pytest.raises(HTTPException) as refused:
        await update_operation(db, definition["id"], batch["id"], {"enabled": True, "grants": GRANT})
    assert refused.value.status_code == 400 and "$batch" in refused.value.detail


@pytest.mark.asyncio
async def test_admin_api_refuses_bad_servers_and_filters_calls_by_definition_and_operation(client, db, api):  # noqa: F811
    api.answer = lambda request: httpx.Response(200, json={"d": {}})
    sap = await _import_sap(db, "business-partner.yaml", enable=("get_a_business_partner_by_key",))
    people, _ = await _people(db, "odata_v4")
    admin = await _admin(db)
    await execute_rest_tool("rest__bp__get_a_business_partner_by_key", {"BusinessPartner": "1"}, _context(db, admin.id))
    await execute_rest_tool("rest__people__list_people", {}, _context(db, admin.id))
    await db.commit()
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303

    bad = await client.put(f"/admin/chat/api/panel/rest-apis/{sap['id']}", json={"servers": ["https://:/x"]})
    assert bad.status_code == 422 and bad.json()["detail"][0]["loc"] == ["body", "servers", 0]

    get_op = next(op for op in sap["operations"] if op["op_key"] == "get_a_business_partner_by_key")
    by_definition = (await client.get("/admin/chat/api/panel/rest-api-calls",
                                      params={"definition_id": people["id"]})).json()
    by_operation = (await client.get("/admin/chat/api/panel/rest-api-calls", params={"op_id": get_op["id"]})).json()
    assert [call["tool_name"] for call in by_definition] == ["rest__people__list_people"]
    assert [call["tool_name"] for call in by_operation] == ["rest__bp__get_a_business_partner_by_key"]
    assert len(await recent_calls(db)) == 2


@pytest.mark.asyncio
async def test_the_odata_preset_is_a_definition_default_each_operation_can_override(db):
    admin = await _admin(db)
    spec = {"openapi": "3.0.0", "info": {"title": "Orders"}, "x-sap-api-type": "ODATA",
            "servers": [{"url": "https://erp.example.test/sap/opu/odata/sap/API_ORDERS"}],
            "paths": {"/A_Order": {"get": {"responses": {"200": {"description": "ok"}}}},
                      "/A_Order('{Id}')": {"get": {"parameters": [{"name": "Id", "in": "path", "required": True,
                                                                   "schema": {"type": "string"}}],
                                                   "responses": {"200": {"description": "ok"}}}}}}
    definition = await import_definition(db, {"key": "orders", "spec_text": json.dumps(spec)}, actor_user_id=admin.id)
    assert definition["default_preset"] == "odata_v2"
    by_path = {operation["path"]: operation for operation in definition["operations"]}
    collection, single = by_path["/A_Order"], by_path["/A_Order('{Id}')"]
    assert (collection["preset"], collection["preset_source"]) == ("odata_v2", "definition")
    assert (single["preset"], single["preset_source"]) == ("", "none")

    switched = await update_definition(db, definition["id"], {"default_preset": "odata_v2_offset"})
    assert next(op for op in switched["operations"] if op["path"] == "/A_Order")["preset"] == "odata_v2_offset"
    own = await update_operation(db, definition["id"], collection["id"], {"preset": "odata_v4"})
    assert (own["preset"], own["preset_source"]) == ("odata_v4", "operation")
    off = await update_operation(db, definition["id"], collection["id"], {"preset": "none"})
    assert (off["preset"], off["preset_source"]) == ("", "operation")
    back = await update_operation(db, definition["id"], collection["id"], {"preset": "inherit"})
    assert (back["preset"], back["preset_source"]) == ("odata_v2_offset", "definition")

    with pytest.raises(HTTPException) as refused:
        await update_definition(db, definition["id"], {"default_preset": "odata_v9"})
    assert refused.value.status_code == 422 and refused.value.detail["field"] == "default_preset"
