"""Named connections in Source Sync: each Confluence space is read with its own account.

Against a fake Confluence and identity provider (``httpx.MockTransport``, no network), with two named
connections stored through the admin service (secrets in the secret store, fake values only):

- SALES is bound to ``client-a`` (OpenID Connect client credentials: its own client id at the token
  endpoint, then its own access token), INFRA to ``client-b`` (a personal access token). Every request
  of a space carries exactly its connection's credential, never the other's or the default's;
- the run report says per space which connection read it and what it listed and created; the log
  names space and connection, never a secret;
- a space no connection serves is refused as ``connection_not_configured_for_scope``; an unbound
  space the default allows still runs on the default connection;
- a Jira connector whose projects span two connections is refused (``scope_spans_connections``);
- a named connection without its secret fails closed (``own_connection_incomplete``), never borrowing one.
"""

from __future__ import annotations

import dataclasses
import logging
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.models import BuiltInToolConfig, ConnectorNamedConnection
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.admin.project.named_connection_service import save_named
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.parser_port import ParserIdentity
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.services.named_connections.store import list_named_connections
from app.services.oidc_token_cache import clear_token_cache
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

pytestmark = pytest.mark.usefixtures("public_source_dns")

WIKI = "https://wiki.example.test/wiki"
TOKEN_URL = "https://idp.example.test/oauth2/token"
FAKE_A = "fake-client-secret-a"
FAKE_B = "fake-pat-b"
FAKE_DEFAULT = "fake-default-password"
TOKEN_A = "fake-access-token-a"
PAGES = {"SALES": ("101", "SALES runbook"), "INFRA": ("202", "INFRA incident notes"), "ENG": ("303", "ENG guide")}


class StubParser:
    identity = ParserIdentity(name="docling-serve", version="1.35.0+p1", sandbox="no_network_uds")


class FakeConfluence:
    """Answers listings per space and page bodies; records (space, Authorization) for every request."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []
        self.token_clients: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "idp.example.test":
            form = parse_qs(request.content.decode())
            self.token_clients.append(form["client_id"][0])
            assert form["client_id"] == ["client-a"] and form["client_secret"] == [FAKE_A]
            return httpx.Response(200, json={"access_token": TOKEN_A, "token_type": "Bearer", "expires_in": 300})
        auth = request.headers.get("Authorization", "")
        path = request.url.path.removeprefix("/wiki/rest/api/content")
        if path == "":
            space = parse_qs(urlsplit(str(request.url)).query)["spaceKey"][0]
            self.seen.append((space, auth))
            page_id, title = PAGES[space]
            listing = [{"id": page_id, "title": title, "version": {"number": 1}, "ancestors": [],
                        "restrictions": {"read": {"restrictions": {"user": {"results": []},
                                                                   "group": {"results": []}}}}}]
            return httpx.Response(200, json={"results": listing, "_links": {}})
        page_id = path.strip("/")
        space = next(key for key, (pid, _) in PAGES.items() if pid == page_id)
        self.seen.append((space, auth))
        return httpx.Response(200, json={"id": page_id, "body": {"view": {"value": f"<p>{PAGES[space][1]}</p>"}}})


async def _setup(db, *, default_spaces=("ENG",)):
    clear_token_cache()
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=workspace_id, is_active=True, config={
        "confluence_url": WIKI, "confluence_auth_mode": "basic", "confluence_username": "default-user",
        "confluence_password": FAKE_DEFAULT,
        "confluence_allowed_spaces": [{"space_key": key, "enabled": True} for key in default_spaces],
    }))
    await db.flush()
    await save_named(db, connector="confluence", project_id=workspace_id, actor_id=user_id, payload={
        "name": "client-a", "bound_scopes": ["SALES"], "confluence_url": WIKI,
        "confluence_auth_mode": "oidc_client_credentials", "confluence_oidc_token_url": TOKEN_URL,
        "confluence_oidc_client_id": "client-a", "confluence_oidc_client_secret": FAKE_A,
    })
    await save_named(db, connector="confluence", project_id=workspace_id, actor_id=user_id, payload={
        "name": "client-b", "bound_scopes": ["INFRA"], "confluence_url": WIKI,
        "confluence_auth_mode": "bearer_pat", "confluence_token": FAKE_B,
    })
    runtime, _, evidence_index = build_runtime()
    return authorized, user_id, dataclasses.replace(runtime, parser=StubParser())


async def _configure(db, authorized, user_id, spaces):
    config = validate_config(connector_key="wiki", kind="confluence", products=["acme-orders"], spaces=list(spaces))
    return await configure_connector(db, authorized=authorized, config=config, actor_id=user_id)


async def _run(db, authorized, user_id, runtime, row, fake):
    row = await db.get(KnowledgeSourceConnector, row.id)
    return await run_connector(
        db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id,
        transport=httpx.MockTransport(fake.handler),
    )


async def test_each_space_is_read_with_its_own_connection_and_reported_per_space(db, caplog) -> None:
    authorized, user_id, runtime = await _setup(db)
    row = await _configure(db, authorized, user_id, ["SALES", "INFRA", "ENG"])
    fake = FakeConfluence()

    with caplog.at_level(logging.INFO):
        run = await _run(db, authorized, user_id, runtime, row, fake)

    assert run.state == "completed" and run.report["created"] == 3
    by_space: dict[str, set[str]] = {}
    for space, auth in fake.seen:
        by_space.setdefault(space, set()).add(auth)
    assert by_space["SALES"] == {f"Bearer {TOKEN_A}"}
    assert by_space["INFRA"] == {f"Bearer {FAKE_B}"}
    assert len(by_space["ENG"]) == 1 and next(iter(by_space["ENG"])).startswith("Basic ")
    assert fake.token_clients == ["client-a"]
    scopes = run.report["scopes"]
    ids = {c.name: c.id for c in await list_named_connections(db, "confluence", authorized.project_id)}
    assert scopes["SALES"] == {"connection": "client-a", "connection_id": ids["client-a"], "listed": 1, "created": 1, "updated": 0, "unchanged": 0,
                            "retired": 0, "skipped": 0, "failed": 0, "deferred": 0}
    assert scopes["INFRA"]["connection"] == "client-b" and scopes["INFRA"]["created"] == 1
    assert scopes["INFRA"]["connection_id"] == ids["client-b"] and scopes["ENG"]["connection_id"] == "default"
    assert scopes["ENG"]["connection"] == "default" and scopes["ENG"]["listed"] == 1
    assert f"space=SALES connection=client-a id={ids['client-a']}" in caplog.text and "space=INFRA connection=client-b" in caplog.text
    for secret in (FAKE_A, FAKE_B, FAKE_DEFAULT, TOKEN_A):
        assert secret not in caplog.text and secret not in str(run.report)


async def test_a_space_no_connection_serves_is_refused(db) -> None:
    authorized, user_id, runtime = await _setup(db)
    row = await _configure(db, authorized, user_id, ["SALES"])
    row.scope = {"spaces": ["SALES", "OTHER"]}
    await db.commit()

    run = await _run(db, authorized, user_id, runtime, row, FakeConfluence())

    assert run.state == "needs_configuration" and run.reason == "connection_not_configured_for_scope"
    with pytest.raises(ConnectorError) as refused:
        await _configure(db, authorized, user_id, ["INFRA", "OTHER"])
    assert refused.value.reason == "connection_not_configured_for_scope"


async def test_one_named_connection_reads_alone_without_any_default_space(db) -> None:
    authorized, user_id, runtime = await _setup(db, default_spaces=())
    row = await _configure(db, authorized, user_id, ["INFRA"])
    fake = FakeConfluence()

    run = await _run(db, authorized, user_id, runtime, row, fake)

    assert run.state == "completed" and run.report["created"] == 1
    assert {auth for _, auth in fake.seen} == {f"Bearer {FAKE_B}"}


async def test_a_named_connection_without_its_secret_fails_closed(db) -> None:
    authorized, user_id, runtime = await _setup(db)
    row = await _configure(db, authorized, user_id, ["INFRA"])
    named = (await db.execute(
        ConnectorNamedConnection.__table__.select().where(ConnectorNamedConnection.name == "client-b")
    )).first()
    stored = await db.get(ConnectorNamedConnection, named.id)
    stored.config = {key: value for key, value in stored.config.items() if not key.endswith("_secret_ref")}
    await db.commit()

    run = await _run(db, authorized, user_id, runtime, row, FakeConfluence())

    assert run.state == "needs_configuration" and run.reason == "own_connection_incomplete"


async def test_a_jira_connector_spanning_two_connections_is_refused(db) -> None:
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    db.add(BuiltInToolConfig(tool_name="jira", project_id=workspace_id, is_active=True, config={
        "jira_url": "https://jira.example.test", "jira_auth_mode": "bearer_pat", "jira_token": FAKE_DEFAULT,
    }))
    await db.flush()
    await save_named(db, connector="jira", project_id=workspace_id, actor_id=user_id, payload={
        "name": "ops", "bound_scopes": ["OPS"], "jira_url": "https://jira.example.test",
        "jira_auth_mode": "bearer_pat", "jira_token": FAKE_B,
    })
    config = validate_config(connector_key="jira", kind="jira", products=["acme-orders"], project_keys=["OPS", "RIVER"])
    with pytest.raises(ConnectorError) as refused:
        await configure_connector(db, authorized=authorized, config=config, actor_id=user_id)
    assert refused.value.reason == "scope_spans_connections"
    single = validate_config(connector_key="jira", kind="jira", products=["acme-orders"], project_keys=["OPS"])
    assert (await configure_connector(db, authorized=authorized, config=single, actor_id=user_id)).scope == {
        **single.scope
    }


def _unit_connector(name: str) -> object:
    class Unit:
        def __init__(self) -> None:
            self.expanded: list[str] = []

        async def list_items(self, token, *, limit):
            from app.services.knowledge.sources.sync.contract import AclFacet, ListingPage, SourceItem

            item = SourceItem(f"{name}-1", "t", f"{WIKI}/x", "1", AclFacet.restricted("page_restriction", ("user:u",)))
            return ListingPage(items=(item,), next_token=None)

        async def expand_acl(self, acl):
            self.expanded.append(name)
            return None

        async def fetch(self, item):
            return name

    return Unit()


async def test_a_restricted_item_is_expanded_and_fetched_by_the_unit_that_listed_it() -> None:
    from app.services.knowledge.sources.sync.acl_sync import _expansion
    from app.services.knowledge.sources.sync.confluence_multi import MultiConnectionConfluenceConnector
    from app.services.knowledge.sources.sync.connections import SourceConnection
    from app.services.knowledge.sources.sync.contract import AclFacet, SourceItem

    connection = SourceConnection(kind="confluence", base_url=WIKI, principal="", secret="fake", scheme="bearer")
    multi = MultiConnectionConfluenceConnector(
        (("SALES", ("client-a", "id-a"), connection, None), ("INFRA", ("client-b", "id-b"), connection, None))
    )
    units = [_unit_connector("a"), _unit_connector("b")]
    multi._units = tuple((space, name, unit) for (space, name, _), unit in zip(multi._units, units, strict=True))

    first = await multi.list_items(None, limit=10)
    second = await multi.list_items(first.next_token, limit=10)

    assert first.next_token == "1:0" and second.next_token is None
    assert await _expansion(multi, second.items[0]) == "restricted_acl"
    assert units[1].expanded == ["b"] and units[0].expanded == []
    assert await multi.fetch(first.items[0]) == "a" and multi.scope_of("b-1") == "INFRA"
    unlisted = SourceItem("never-listed", "t", f"{WIKI}/y", "1", AclFacet.scope())
    with pytest.raises(ConnectorError) as refused:
        await multi.fetch(unlisted)
    assert refused.value.reason == "source_contract_violation"
