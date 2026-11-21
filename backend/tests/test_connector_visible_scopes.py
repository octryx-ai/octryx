"""A connection test shows what the account can see; no network (MockTransport fakes).

- Confluence: the configured spaces against the spaces the account lists; the swapped-client case (an account that
  sees SPACE2 configured for SPACE1) is a warning naming SPACE1, the test itself stays ok;
- a cut listing never decides "not visible": the configured keys are then asked for one by one;
- Jira projects (unrestricted = nothing to compare), ServiceNow tables (each configured table, Table API only);
- a failed listing is a closed code, not a warning; keys outside the binding pattern are never reported;
- only admin tests probe (``scope_check=True``): the health worker's test sends no extra request;
- a named connection compares its bound keys (the admin route), the global connector its allowlist.
"""

from __future__ import annotations

import httpx
import pytest

from app.models import BuiltInToolConfig
from app.services.connector_test import collab, servicenow, visible_scopes
from app.services.connector_test_service import run_connector_connection_test
from tests.conftest import ADMIN_PASSWORD

WIKI = "https://wiki.example.test/wiki"
JIRA = "https://jira.example.test"
SNOW = "https://snow.example.test"
PANEL = "/admin/chat/api/panel"


class _Fake:
    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        for prefix, answer in self.routes.items():
            if path == prefix:
                value = answer(request) if callable(answer) else answer
                status, payload = value if isinstance(value, tuple) else (200, value)
                return httpx.Response(status, json=payload)
        return httpx.Response(404, json={})

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


@pytest.fixture
def fake(monkeypatch):
    holder: dict[str, _Fake] = {}

    def install(routes: dict[str, object]) -> _Fake:
        holder["fake"] = _Fake(routes)
        transport = lambda _connection: httpx.MockTransport(holder["fake"].handler)  # noqa: E731
        for module in (collab, servicenow, visible_scopes):
            monkeypatch.setattr(module, "egress_transport", transport)
        return holder["fake"]

    return install


def _spaces(*keys: str, more: bool = False) -> dict:
    return {"results": [{"key": key, "name": f"Name of {key}"} for key in keys],
            "_links": {"next": "/rest/api/space?start=2"} if more else {}}


CONFLUENCE = {"confluence_url": WIKI, "confluence_auth_mode": "bearer_pat", "confluence_token": "fake-pat",
              "confluence_allowed_spaces": [{"space_key": "SPACE1", "enabled": True}]}


async def test_the_swapped_account_is_a_warning_naming_the_space(fake) -> None:
    wiki = fake({"/wiki/rest/api/space": _spaces("SPACE2", "<b>x</b>")})
    result = await run_connector_connection_test("confluence", CONFLUENCE, scope_check=True)
    assert result["ok"] is True and result["scope_warning"] is True
    assert result["warnings"] == ["Space SPACE1 is configured but not visible to this account."]
    assert result["summary"].endswith("Not visible to this account: SPACE1.")
    check = result["scope_check"]
    assert (check["configured"], check["visible"], check["missing"]) == (["SPACE1"], ["SPACE2"], ["SPACE1"])
    assert check["visible_complete"] is True
    assert "<b>" not in str(result) and "Name of" not in str(result), "only keys of the binding pattern are kept"
    assert wiki.requests[-1].headers["Authorization"] == "Bearer fake-pat"


async def test_a_visible_configured_space_is_no_warning(fake) -> None:
    fake({"/wiki/rest/api/space": _spaces("space1", "SPACE2")})  # compared in the binding's canonical case
    result = await run_connector_connection_test("confluence", CONFLUENCE, scope_check=True)
    assert "scope_warning" not in result and result["scope_check"]["missing"] == []
    assert result["summary"] == "Connected to Confluence."


async def test_a_cut_listing_asks_for_each_configured_space_directly(fake, monkeypatch) -> None:
    monkeypatch.setattr(visible_scopes, "PAGE_SIZE", 2)
    monkeypatch.setattr(visible_scopes, "MAX_PAGES", 1)
    config = {**CONFLUENCE, "confluence_allowed_spaces": ["SPACE1", "SPACE9", "SPACE8"]}
    wiki = fake({
        "/wiki/rest/api/space": _spaces("SPACE1", "SPACE2", more=True),
        "/wiki/rest/api/space/SPACE9": {"key": "SPACE9"},
        "/wiki/rest/api/space/SPACE8": (403, {}),
    })
    result = await run_connector_connection_test("confluence", config, scope_check=True)
    assert result["scope_check"]["visible_complete"] is False
    assert result["scope_check"]["missing"] == ["SPACE8"], "SPACE9 is visible though beyond the cut listing"
    assert "/wiki/rest/api/space/SPACE1" not in wiki.paths(), "a listed space is not asked again"


async def test_a_failed_listing_is_a_code_not_a_warning(fake) -> None:
    fake({"/wiki/rest/api/space": lambda request: (200, _spaces()) if request.url.params.get("limit") == "1"
          else (500, {"message": "internal detail"})})
    result = await run_connector_connection_test("confluence", CONFLUENCE, scope_check=True)
    assert result["ok"] is True and "scope_warning" not in result
    assert result["scope_check"]["error"] == "visible_scopes_unavailable"
    assert result["scope_check"]["http_status"] == 500
    assert result["summary"].endswith("The visible spaces could not be listed.")
    assert "internal detail" not in str(result)


def _probe_only(answer):
    """The connection test's own request (``limit=1``) passes; the probe's requests get ``answer``."""
    return lambda request: (200, _spaces()) if request.url.params.get("limit") == "1" else answer(request)


def _refused(request: httpx.Request):
    raise httpx.ConnectError("connection refused by 10.0.0.1", request=request)


async def test_a_transport_error_of_the_probe_keeps_the_passed_test(fake) -> None:
    fake({"/wiki/rest/api/space": _probe_only(_refused)})
    result = await run_connector_connection_test("confluence", CONFLUENCE, scope_check=True)
    assert result["ok"] is True and "scope_warning" not in result
    assert result["scope_check"]["error"] == "visible_scopes_unavailable"
    assert result["scope_check"]["http_status"] is None
    assert "10.0.0.1" not in str(result), "no transport detail is kept"


async def test_an_answer_that_is_not_json_keeps_the_passed_test(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("limit") == "1":
            return httpx.Response(200, json=_spaces())
        return httpx.Response(200, text="<html>login page</html>")

    for module in (collab, visible_scopes):
        monkeypatch.setattr(module, "egress_transport", lambda _connection: httpx.MockTransport(handler))
    result = await run_connector_connection_test("confluence", CONFLUENCE, scope_check=True)
    assert result["ok"] is True and "scope_warning" not in result
    assert result["scope_check"]["error"] == "visible_scopes_unavailable"
    assert "login page" not in str(result)


async def test_without_scope_check_nothing_is_probed(fake) -> None:
    wiki = fake({"/wiki/rest/api/space": _spaces("SPACE2")})
    result = await run_connector_connection_test("confluence", CONFLUENCE)
    assert "scope_check" not in result and len(wiki.requests) == 1, "the health worker's test only"


async def test_a_failed_connection_test_is_not_probed(fake) -> None:
    wiki = fake({"/wiki/rest/api/space": (401, {})})
    result = await run_connector_connection_test("confluence", CONFLUENCE, scope_check=True)
    assert result["ok"] is False and "scope_check" not in result and len(wiki.requests) == 1


JIRA_CONFIG = {"jira_url": JIRA, "jira_auth_mode": "bearer_pat", "jira_token": "fake-jira",
               "jira_allowed_projects": ["PROJ1", "PROJ2"]}


async def test_jira_projects_compare_the_allowlist_and_unrestricted_compares_nothing(fake) -> None:
    fake({"/rest/api/3/myself": {"accountId": "x"}, "/rest/api/2/project": [{"key": "PROJ2"}, {"key": "1bad"}]})
    result = await run_connector_connection_test("jira", JIRA_CONFIG, scope_check=True)
    assert result["scope_check"]["missing"] == ["PROJ1"] and result["scope_check"]["visible"] == ["PROJ2"]
    assert result["warnings"] == ["Project PROJ1 is configured but not visible to this account."]

    open_config = {key: value for key, value in JIRA_CONFIG.items() if key != "jira_allowed_projects"}
    unrestricted = await run_connector_connection_test("jira", open_config, scope_check=True)
    assert unrestricted["scope_check"]["configured"] is None and "scope_warning" not in unrestricted


SNOW_CONFIG = {"servicenow_url": SNOW, "servicenow_auth_mode": "bearer_token", "servicenow_token": "fake-snow",
               "servicenow_allowed_tables": ["incident", "x_custom"]}


async def test_servicenow_tables_are_read_one_by_one_on_the_table_api(fake) -> None:
    instance = fake({"/api/now/table/incident": {"result": []}, "/api/now/table/x_custom": (403, {})})
    result = await run_connector_connection_test("servicenow", SNOW_CONFIG, scope_check=True)
    assert result["ok"] is True and result["scope_check"]["missing"] == ["x_custom"]
    assert result["warnings"] == ["Table x_custom is configured but not visible to this account."]
    assert instance.paths().count("/api/now/table/x_custom") == 1

    no_tables = {key: value for key, value in SNOW_CONFIG.items() if key != "servicenow_allowed_tables"}
    assert "scope_check" not in await run_connector_connection_test("servicenow", no_tables, scope_check=True)


async def _login(client) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303


async def test_a_named_connection_test_compares_its_bound_spaces(client, db, fake) -> None:
    await _login(client)
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=None, is_active=True, config={
        "confluence_url": WIKI, "confluence_auth_mode": "bearer_pat", "confluence_token": "fake-default",
        "confluence_allowed_spaces": [{"space_key": "SPACE2"}, {"space_key": "SPACE3"}]}))
    await db.commit()
    created = await client.post(f"{PANEL}/connectors/confluence/named-connections", json={
        "name": "client-rt", "bound_scopes": ["SPACE1"], "confluence_url": WIKI,
        "confluence_auth_mode": "bearer_pat", "confluence_token": "fake-named"})
    assert created.status_code == 201, created.text
    fake({"/wiki/rest/api/space": _spaces("SPACE2")})

    tested = await client.post(f"{PANEL}/connectors/confluence/named-connections/{created.json()['id']}/test", json={})
    body = tested.json()
    assert body["ok"] is True and body["scope_check"]["configured"] == ["SPACE1"], "its bound keys, not the default's"
    assert body["scope_check"]["missing"] == ["SPACE1"]
    listed = (await client.get(f"{PANEL}/connectors/confluence/named-connections")).json()
    assert "Not visible to this account: SPACE1." in listed["connections"][0]["last_test"]["summary"]

    default = (await client.post(f"{PANEL}/connectors/confluence/test")).json()
    assert default["scope_check"]["configured"] == ["SPACE2", "SPACE3"]
    assert default["scope_check"]["missing"] == ["SPACE3"]
