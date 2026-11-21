"""With enforcement off a restricted item stays withheld, a later ACL change updates visibility without a new revision, early spans converge before retrieval answers, and Confluence restrictions expand to member addresses while Jira levels do not."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select

from app.models.project.knowledge_evidence import KnowledgeSourceRevision
from app.models.project.knowledge_source_acl import KnowledgeSourceAcl
from app.services.knowledge.access.acl_keys import principal_key_for_email
from app.services.knowledge.sources.sync.confluence import ConfluenceConnector
from app.services.knowledge.sources.sync.connections import SourceConnection
from app.services.knowledge.sources.sync.contract import AclFacet, ConnectorError
from app.services.knowledge.sources.sync.jira import JiraConnector
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_source_acl_support import (  # noqa: F401
    JIRA,
    FakeSource,
    _markers,
    _restricted,
    _sync,
    _titles,
    _workspace,
)

# Connector targets pass the outbound URL policy (see tests/egress_support.py).
pytestmark = pytest.mark.usefixtures("public_source_dns")


WIKI = "https://wiki.example.test/wiki"


async def test_with_enforcement_off_a_restricted_item_is_still_withheld(db) -> None:
    world = await _workspace(db, enforce=False)
    source = FakeSource()
    source.put("1", "OPS-1: Forensics", "Forensics: a breach.", _restricted("level:Security"))
    source.members = {"level:Security": (world["emails"]["alice"],)}

    run = await _sync(db, world, source)

    assert run.report["skipped"] == 1 and run.report["created"] == 0
    assert run.outcomes == [{"external_id": "1", "title": None, "outcome": "skipped", "reason": "restricted_acl"}]
    revisions = select(func.count()).select_from(KnowledgeSourceRevision)
    assert (await db.execute(revisions)).scalar_one() == 0
    # Stored as restricted to nobody, so nothing of it can ever read as public.
    stored = await db.get(KnowledgeSourceAcl, (world["alice"].project_id, "jira.ops.1"))
    assert stored.restriction == "issue_security_level" and stored.principal_count == 0


async def test_an_acl_change_on_a_later_sync_updates_visibility_without_a_new_revision(db) -> None:
    world = await _workspace(db)
    alice, bob = world["alice"], world["bob"]
    source = FakeSource()
    source.put("1", "OPS-1: Forensics", "Forensics: the failover drill found a breach.", _restricted("level:Security"))
    source.put("2", "OPS-2: Runbook", "Runbook: the failover drill is public.")
    source.members = {
        "level:Security": (world["emails"]["alice"], world["emails"]["bob"]),
        "level:Leads": (world["emails"]["alice"],),
    }
    await _sync(db, world, source)
    assert await _titles(db, world, bob, "failover") == ["OPS-1: Forensics", "OPS-2: Runbook"]

    # Bob is revoked from the forensics restriction, and the runbook becomes restricted to leads.
    source.members["level:Security"] = (world["emails"]["alice"],)
    source.put("2", "OPS-2: Runbook", "Runbook: the failover drill is public.", _restricted("level:Leads"))
    run = await _sync(db, world, source)

    assert run.report["unchanged"] == 2 and run.report["created"] == run.report["updated"] == 0
    assert (await db.execute(select(func.count()).select_from(KnowledgeSourceRevision))).scalar_one() == 2
    alice_key = principal_key_for_email(world["emails"]["alice"])
    # The projection was redone with the new markers, not only the ledger re-check.
    assert _markers(world, alice) == {"Forensics": ["restricted", alice_key], "Runbook": ["restricted", alice_key]}
    assert await _titles(db, world, bob, "failover") == []
    assert await _titles(db, world, alice, "failover") == ["OPS-1: Forensics", "OPS-2: Runbook"]

    # Lifted again at the source: public for the whole Workspace once more.
    source.put("2", "OPS-2: Runbook", "Runbook: the failover drill is public.")
    await _sync(db, world, source)
    assert await _titles(db, world, bob, "failover") == ["OPS-2: Runbook"]


async def test_confluence_restrictions_expand_to_member_addresses_and_jira_levels_do_not(db) -> None:
    requests: list[str] = []
    members = [{"username": f"user{index}"} for index in range(3)]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        requests.append(request.url.path)
        if request.url.path == "/wiki/rest/api/user":
            name = request.url.params.get("username")
            if name == "ghost":
                return httpx.Response(404, json={})
            return httpx.Response(
                200, json={"username": name, "details": {"personal": {"email": f"{name}@Example.com"}}}
            )
        if request.url.raw_path.startswith(b"/wiki/rest/api/group/hr%20leads/member?"):
            return httpx.Response(200, json={"results": members, "_links": {}})
        return httpx.Response(500, json={})

    connection = SourceConnection(kind="confluence", base_url=WIKI, principal="sync", secret="pw")
    wiki = ConfluenceConnector(connection, spaces=("ENG",), transport=httpx.MockTransport(handler))
    facet = AclFacet.restricted("page_restriction", ("user:username=jdoe", "user:username=ghost", "group:hr leads"))

    expansion = await wiki.expand_acl(facet)

    assert expansion.member_emails == (
        "jdoe@example.com",
        "user0@example.com",
        "user1@example.com",
        "user2@example.com",
    )
    assert expansion.unmapped == 1  # the account Confluence no longer knows maps to nobody
    # Cached per run: expanding again costs no request.
    before = len(requests)
    assert await wiki.expand_acl(facet) == expansion and len(requests) == before
    with pytest.raises(ConnectorError) as unresolved:
        await wiki.expand_acl(AclFacet.restricted("page_restriction", ("group:missing",)))
    assert unresolved.value.reason == "acl_unresolved"
    jira = JiraConnector(
        SourceConnection(kind="jira", base_url=JIRA, principal="sync", secret="pw"), project_keys=("OPS",)
    )
    assert await jira.expand_acl(_restricted("level:Security")) is None
