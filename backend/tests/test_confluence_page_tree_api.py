"""The global page picker's read, through the real panel route; no network.

- top level of a space (``depth=root``) and the children of one page, id and title only, bounded and paged;
- each space is read with the saved connection that serves it: a global named connection binding the space
  (its own token), else the default entry when its allowlist allows the space; any other space is refused
  (``connection_not_configured_for_scope``) before any request;
- a child reported in another space is left out; Confluence failures are fixed codes; bad input is a 422;
- with several named connections every connection's spaces are readable (not only the first connection's),
  globally and in a Workspace (its own connections first).
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.models import BuiltInToolConfig, Project
from app.services.confluence_pages import tree
from tests.conftest import ADMIN_PASSWORD

PANEL = "/admin/chat/api/panel"
URL = f"{PANEL}/connectors/confluence/page-tree"
WIKI = "https://wiki.example.test/wiki"
DEFAULT_PAT = "fake-default-pat"
NAMED_PAT = "fake-named-pat"
SECOND_PAT = "fake-second-pat"
WORKSPACE_PAT = "fake-workspace-pat"


class _Wiki:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "internal detail never shown"})
        path = request.url.path.removeprefix("/wiki")
        if path.endswith("/content/page"):
            start = int(request.url.params["start"])
            pages = [{"id": str(100 + start + i), "title": f"Top {start + i}"} for i in range(2)]
            links = {"next": "/rest/api/space/X/content/page?start=2"} if start == 0 else {}
            return httpx.Response(200, json={"results": pages, "_links": links})
        if path.endswith("/child/page"):
            return httpx.Response(200, json={"results": [
                {"id": "201", "title": "  Child\n one ", "space": {"key": "SPACE1"}},
                {"id": "202", "title": "Moved", "space": {"key": "OTHER"}},
                {"id": "not-a-page", "title": "Bad"},
            ]})
        return httpx.Response(404, json={})


@pytest.fixture
def wiki(monkeypatch):
    fake = _Wiki()
    monkeypatch.setattr(tree, "egress_transport", lambda _connection: httpx.MockTransport(fake.handler))
    return fake


async def _setup(client, db) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=None, is_active=True, config={
        "confluence_url": WIKI, "confluence_auth_mode": "bearer_pat", "confluence_token": DEFAULT_PAT,
        "confluence_allowed_spaces": [{"space_key": "SPACE1", "enabled": True}, {"space_key": "SPACE2"}],
    }))
    await db.commit()
    created = await client.post(f"{PANEL}/connectors/confluence/named-connections", json={
        "name": "client-b", "bound_scopes": ["SPACE2"], "confluence_url": WIKI,
        "confluence_auth_mode": "bearer_pat", "confluence_token": NAMED_PAT,
    })
    assert created.status_code == 201, created.text


async def test_top_level_and_children_are_read_with_the_connection_of_the_space(client, db, wiki) -> None:
    await _setup(client, db)

    top = await client.get(URL, params={"space_key": "SPACE1"})
    assert top.status_code == 200, top.text
    assert top.json() == {"space_key": "SPACE1", "parent_id": None, "start": 0, "next_start": 2,
                          "pages": [{"id": "100", "title": "Top 0"}, {"id": "101", "title": "Top 1"}]}
    request = wiki.requests[-1]
    assert request.url.path == "/wiki/rest/api/space/SPACE1/content/page"
    assert request.url.params["depth"] == "root" and request.url.params["limit"] == "25"
    assert request.headers["Authorization"] == f"Bearer {DEFAULT_PAT}"

    more = (await client.get(URL, params={"space_key": "SPACE1", "start": 2})).json()
    assert more["next_start"] is None and [page["id"] for page in more["pages"]] == ["102", "103"]

    children = await client.get(URL, params={"space_key": "SPACE2", "parent_id": "200", "limit": 10})
    assert wiki.requests[-1].url.path == "/wiki/rest/api/content/200/child/page"
    assert wiki.requests[-1].headers["Authorization"] == f"Bearer {NAMED_PAT}", "SPACE2 is the named connection's"
    assert children.json()["pages"] == [], "children reported in SPACE1/OTHER are not SPACE2 pages"

    own = (await client.get(URL, params={"space_key": "SPACE1", "parent_id": "200"})).json()
    assert own["pages"] == [{"id": "201", "title": "Child one"}], "another space and a non-page id are left out"
    assert DEFAULT_PAT not in str(own) and NAMED_PAT not in str(own)


async def test_a_space_no_saved_connection_serves_is_refused_before_any_request(client, db, wiki) -> None:
    await _setup(client, db)
    refused = await client.get(URL, params={"space_key": "SPACE3"})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "connection_not_configured_for_scope"
    assert wiki.requests == []


@pytest.mark.parametrize("params", [
    {"space_key": "bad key"}, {"space_key": "SPACE1", "parent_id": "12a"}, {"space_key": "SPACE1", "limit": 51},
    {"space_key": "SPACE1", "start": -1}, {},
])
async def test_bad_input_is_a_422(client, db, wiki, params) -> None:
    await _setup(client, db)
    response = await client.get(URL, params=params)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "page_tree_request_invalid"
    assert wiki.requests == []


@pytest.mark.parametrize(("status", "code", "http"), [
    (401, "confluence_unauthorized", 502), (403, "confluence_unauthorized", 502),
    (404, "confluence_page_not_found", 404), (500, "confluence_unavailable", 502),
])
async def test_confluence_failures_are_fixed_codes(client, db, wiki, status, code, http) -> None:
    await _setup(client, db)
    wiki.status = status
    response = await client.get(URL, params={"space_key": "SPACE1"})
    assert response.status_code == http and response.json()["detail"]["code"] == code
    assert "internal detail" not in response.text


async def test_without_a_saved_connector_nothing_is_read(client, db, wiki) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303
    refused = await client.get(URL, params={"space_key": "SPACE1"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "connector_not_configured"
    assert wiki.requests == []


async def _named(client, path: str, name: str, scopes: list[str], token: str) -> None:
    created = await client.post(f"{PANEL}{path}/connectors/confluence/named-connections", json={
        "name": name, "bound_scopes": scopes, "confluence_url": WIKI, "confluence_auth_mode": "bearer_pat",
        "confluence_token": token,
    })
    assert created.status_code == 201, created.text


async def test_every_named_connection_serves_the_picker_not_only_the_first(client, db, wiki) -> None:
    await _setup(client, db)
    await _named(client, "", "client-c", ["SPACE3"], SECOND_PAT)  # not in the default's allowed spaces

    for space, token in (("SPACE2", NAMED_PAT), ("SPACE3", SECOND_PAT), ("SPACE1", DEFAULT_PAT)):
        response = await client.get(URL, params={"space_key": space})
        assert response.status_code == 200, response.text
        assert wiki.requests[-1].url.path == f"/wiki/rest/api/space/{space}/content/page"
        assert wiki.requests[-1].headers["Authorization"] == f"Bearer {token}", space


async def test_a_workspace_reads_each_space_with_its_serving_connection(client, db, wiki) -> None:
    await _setup(client, db)  # global: default SPACE1 (+SPACE2), named client-b SPACE2
    project = Project(name=f"tree-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    workspace_url = f"{PANEL}/projects/{project.id}/connectors/confluence/page-tree"
    refused = await client.get(workspace_url, params={"space_key": "SPACE1"})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "connector_not_enabled_in_workspace"

    db.add(BuiltInToolConfig(tool_name="confluence", project_id=project.id, is_active=True, config={}))
    await db.commit()
    await _named(client, f"/projects/{project.id}", "workspace-a", ["SPACE4"], WORKSPACE_PAT)
    await _named(client, f"/projects/{project.id}", "workspace-b", ["SPACE2"], SECOND_PAT)  # overrides client-b

    for space, token in (("SPACE4", WORKSPACE_PAT), ("SPACE2", SECOND_PAT), ("SPACE1", DEFAULT_PAT)):
        response = await client.get(workspace_url, params={"space_key": space, "parent_id": "200"})
        assert response.status_code == 200, response.text
        assert wiki.requests[-1].headers["Authorization"] == f"Bearer {token}", space
    unserved = await client.get(workspace_url, params={"space_key": "SPACE9"})
    assert unserved.status_code == 409
    assert unserved.json()["detail"]["code"] == "connection_not_configured_for_scope"
