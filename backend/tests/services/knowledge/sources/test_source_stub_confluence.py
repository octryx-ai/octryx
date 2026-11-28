"""The Confluence stub (``tests/fixtures/source_stubs``) fits the governed connector exactly: its fixtures
produce, through the real platform code, the expectations the stub declares (no network)."""

from __future__ import annotations

import base64
import dataclasses
from urllib.parse import parse_qs, urlsplit

import pytest

from app.models import BuiltInToolConfig, Project, User
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.parser_port import ParserIdentity
from app.services.knowledge.ledger.queries import list_sources
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.confluence import ConfluenceConnector
from app.services.knowledge.sources.sync.confluence_updates import confluence_page_updates
from app.services.knowledge.sources.sync.connections import SourceConnection
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from tests import source_stub_support as stubs
from tests.egress_support import loopback_stub_exemption_fixture  # noqa: F401  (fixture)
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

# Connector targets pass the outbound URL policy (see tests/egress_support.py).
pytestmark = pytest.mark.usefixtures("loopback_stub_exemption_fixture")

fx = stubs.confluence_fixtures
stub = stubs.confluence_stub
acceptance_http = stubs.acceptance_http
STUB_URL = f"http://{fx.STUB_HOST}:{fx.STUB_PORT}"
AUTH = "Basic " + base64.b64encode(f"{fx.STUB_USERNAME}:{fx.STUB_TOKEN}".encode()).decode()
OWNER_EMAIL = "owner@acceptance.octryx.test"
# Workspace id -> its owner's user id (the actor of configuration and sync audit rows).
OWNER_ID: dict[str, str] = {}


class StubParser:
    identity = ParserIdentity(name="docling-serve", version="1.35.0+p1", sandbox="no_network_uds")


def _transport():
    return stubs.transport(stub, STUB_URL)


def test_the_stub_is_read_only_credential_checked_and_paged() -> None:
    assert stub.handle("GET", "/healthz", None) == (200, {"status": "ok"})
    assert stub.handle("POST", "/rest/api/content", AUTH)[0] == 405
    assert stub.handle("GET", "/rest/api/content?spaceKey=ACLSTUB", None)[0] == 401
    assert stub.handle("GET", "/rest/api/content?spaceKey=ACLSTUB", "Basic d3Jvbmc6d3Jvbmc=")[0] == 401
    status, first = stub.handle("GET", "/rest/api/content?spaceKey=ACLSTUB&type=page&start=0&limit=4", AUTH)
    assert status == 200 and [page["id"] for page in first["results"]] == ["1001", "1002", "1003", "1004"]
    next_query = parse_qs(urlsplit(first["_links"]["next"]).query)
    assert next_query["start"] == ["4"]
    _, rest = stub.handle("GET", "/rest/api/content?spaceKey=ACLSTUB&type=page&start=4&limit=4", AUTH)
    assert [page["id"] for page in rest["results"]] == ["1005", "1006"] and "next" not in rest["_links"]
    assert stub.handle("GET", "/rest/api/content?spaceKey=OTHER&type=page", AUTH)[1]["results"] == []
    assert stub.handle("GET", "/rest/api/content/9999?expand=body.view", AUTH)[0] == 404
    assert stub.handle("GET", "/rest/api/user?username=nobody", AUTH)[0] == 404
    assert stub.handle("GET", "/rest/api/group/acl-stub-broken/member", AUTH)[0] == 500
    assert stub.handle("GET", "/rest/api/space/ACLSTUB", AUTH)[1]["key"] == "ACLSTUB"


async def test_the_real_connector_reads_every_fixture_facet_and_expands_it_to_the_fixture_addresses() -> None:
    connection = SourceConnection(
        kind="confluence", base_url=STUB_URL, principal=fx.STUB_USERNAME, secret=fx.STUB_TOKEN
    )
    wiki = ConfluenceConnector(connection, spaces=(fx.SPACE_KEY,), transport=_transport())

    page = await wiki.list_items(None, limit=50)
    facets = {item.external_id: item.acl for item in page.items}

    assert page.next_token is None and list(facets) == list(fx.PAGES)
    assert facets["1001"].audience == "scope"
    assert (facets["1002"].restriction, facets["1002"].principals) == ("page_restriction", ("user:username=alice",))
    # 1003 has no restriction of its own: it inherits its parent's.
    assert (facets["1003"].restriction, facets["1003"].principals) == ("ancestor_restriction", ("user:username=alice",))
    assert facets["1004"].principals == ("group:acl-stub-readers",)
    assert page.items[0].source_url == f"{STUB_URL}/pages/viewpage.action?pageId=1001"
    assert fx.page_id_of(page.items[0].source_url) == "1001"

    alice = await wiki.expand_acl(facets["1002"])
    readers = await wiki.expand_acl(facets["1004"])
    hidden = await wiki.expand_acl(facets["1005"])
    assert (alice.member_emails, alice.unmapped) == ((fx.USERS["alice"][2],), 0)
    assert readers.member_emails == (fx.USERS["bob"][2], fx.USERS["carol"][2])
    # An account Confluence reports without an address maps to nobody.
    assert (hidden.member_emails, hidden.unmapped) == ((), 1)
    with pytest.raises(ConnectorError) as unresolved:
        await wiki.expand_acl(facets["1006"])
    assert unresolved.value.reason == "acl_unresolved"

    content = await wiki.fetch(page.items[0])
    assert content.media_type == "text/html" and fx.SEARCH_TERM.encode() in content.data


async def _reader(db, workspace_id: str, *, role: str, username: str, email: str):
    user_id = await seed_member(db, workspace_id=workspace_id, role=role, username=username)
    user = await db.get(User, user_id)
    user.email = email
    await db.flush()
    if role == "owner":
        OWNER_ID[workspace_id] = user_id
    return await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)


async def _outcomes(db, *, runtime, owner, row) -> dict[str, tuple[str, str | None]]:
    run = await run_connector(
        db, runtime=runtime, authorized=owner, row=row, actor_id=OWNER_ID[owner.project_id], transport=_transport()
    )
    assert run.state == "completed"
    restricted_titles = [o for o in run.outcomes if o["external_id"] in fx.RESTRICTED_PAGES and o["title"]]
    assert restricted_titles == []  # the run report every member reads never names a restricted page
    return {o["external_id"]: (o["outcome"], o["reason"]) for o in run.outcomes}


async def _listed(db, readers: dict) -> dict[str, frozenset[str]]:
    by_title = {page["title"]: page_id for page_id, page in fx.PAGES.items()}
    return {
        name: frozenset(by_title[source.display_title] for source in await list_sources(db, authorized))
        for name, authorized in readers.items()
    }


async def test_a_sync_against_the_stub_yields_exactly_the_outcomes_and_visibility_the_check_asserts(db) -> None:
    workspace_id = await seed_workspace(db)
    readers = {"owner": await _reader(db, workspace_id, role="owner", username="acl-owner", email=OWNER_EMAIL)}
    for name, (username, email) in fx.PLATFORM_USERS.items():
        readers[name] = await _reader(db, workspace_id, role="member", username=username, email=email)
    tool = {
        "confluence_auth_mode": "basic",
        "confluence_url": STUB_URL,
        "confluence_username": fx.STUB_USERNAME,
        "confluence_password": fx.STUB_TOKEN,
        "confluence_allowed_spaces": [{"space_key": fx.SPACE_KEY, "enabled": True}],
    }
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=workspace_id, config=tool, is_active=True))
    await db.flush()
    runtime, _, evidence_index = build_runtime()
    runtime = dataclasses.replace(runtime, parser=StubParser())
    config = validate_config(connector_key="acl-stub", kind="confluence", spaces=[fx.SPACE_KEY], max_items_per_run=50)
    row = await configure_connector(db, authorized=readers["owner"], config=config, actor_id=OWNER_ID[workspace_id])

    assert await _outcomes(db, runtime=runtime, owner=readers["owner"], row=row) == fx.SYNC_WITHOUT_ENFORCEMENT
    assert await _listed(db, readers) == fx.VISIBLE_WITHOUT_ENFORCEMENT

    project = await db.get(Project, workspace_id)
    project.config = {**(project.config or {}), "knowledge_source_acl": {"enforce": True}}
    await db.flush()

    assert await _outcomes(db, runtime=runtime, owner=readers["owner"], row=row) == fx.SYNC_WITH_ENFORCEMENT
    assert await _listed(db, readers) == fx.VISIBLE_WITH_ENFORCEMENT
    # The Confluence changes feed passes the same ACL: each reader is told only of their pages.
    for name, authorized in readers.items():
        feed = await confluence_page_updates(db, authorized)
        assert feed["state"] == "ok"
        assert {page["id"] for page in feed["new_pages"]} == fx.VISIBLE_WITH_ENFORCEMENT[name], name


@pytest.mark.parametrize(
    "base_url",
    ["https://localhost:8090", "http://10.0.0.5:8090", "http://octryx.example.com", "ftp://127.0.0.1"],
)
def test_the_check_refuses_any_stack_that_is_not_plain_http_on_loopback(base_url: str) -> None:
    with pytest.raises(SystemExit):
        acceptance_http.require_loopback(base_url)
    assert acceptance_http.require_loopback("http://localhost:8090/") == "http://localhost:8090"
    assert acceptance_http.require_loopback("http://127.0.0.1:8090") == "http://127.0.0.1:8090"
