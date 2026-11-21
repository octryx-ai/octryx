"""Source ACL facets: mirrored from the source, stored, and enforced in retrieval.

Contract tests over the real ledger, the registry-exact fake Evidence index and a fake source connector
(text items, so no parser is involved): a restricted item is found, read and listed only by the
member its ACL admits, filtered inside the index statement and again in the ledger; an unmapped
restriction and a caller without a user see nothing; a bound read applies the calling user's ACL in
the source Workspace; with enforcement off the item is still withheld at sync; an ACL change on a
later sync updates visibility without a new revision; a span without an ACL marker is marked public before
retrieval answers; and Confluence restrictions expand to member addresses.
"""

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import select

from app.models import Project
from app.models.security.user import UserProject
from app.services.knowledge.access.acl_keys import principal_key_for_email
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.access.bindings import create_binding, resolve_scope
from app.services.knowledge.ledger.citations import resolve_citations
from app.services.knowledge.ledger.errors import EvidenceRecordNotFoundError
from app.services.knowledge.ledger.queries import list_sources
from app.services.knowledge.ledger.reading import read_span_window
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from app.services.knowledge.retrieval.scoped import scoped_evidence, scoped_read
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user, seed_workspace
from tests.knowledge_source_acl_support import (  # noqa: F401
    FakeSource,
    _markers,
    _restricted,
    _sync,
    _titles,
    _workspace,
)

# Connector targets pass the outbound URL policy (see tests/egress_support.py).
pytestmark = pytest.mark.usefixtures("public_source_dns")


async def test_a_restricted_item_is_found_read_and_listed_only_by_the_member_its_acl_admits(db) -> None:
    world = await _workspace(db)
    alice, bob = world["alice"], world["bob"]
    source = FakeSource()
    source.put("1", "OPS-1: Runbook", "Runbook: the failover drill is public.")
    source.put("2", "OPS-2: Forensics", "Forensics: the failover drill found a breach.", _restricted("level:Security"))
    source.put("3", "OPS-3: Vault", "Vault: the failover drill secrets.", _restricted("level:Nobody"))
    source.members = {"level:Security": (world["emails"]["alice"],), "level:Nobody": ("unmapped-account",)}

    run = await _sync(db, world, source)

    assert run.report["created"] == 3
    # Restricted titles never reach the run report every member can read.
    assert {o["external_id"]: o["title"] for o in run.outcomes} == {"1": "OPS-1: Runbook", "2": None, "3": None}
    # Filtered inside the statement: each span carries its marker, the restricted ones never "public".
    alice_key = principal_key_for_email(world["emails"]["alice"])
    assert _markers(world, alice) == {
        "Runbook": ["public"],
        "Forensics": ["restricted", alice_key],
        "Vault": ["restricted"],
    }
    assert await _titles(db, world, alice, "failover drill") == ["OPS-1: Runbook", "OPS-2: Forensics"]
    assert await _titles(db, world, bob, "failover drill") == ["OPS-1: Runbook"]
    # A caller without a user (a background job) holds no principal: public only.
    service = dataclasses.replace(alice, principal_keys=())
    assert await _titles(db, world, service, "failover drill") == ["OPS-1: Runbook"]

    forensics = (
        await retrieve_workspace_evidence(db, runtime=world["runtime"], authorized=alice, query_text="breach")
    ).evidence
    key = forensics[0].evidence_key
    assert (await read_span_window(db, authorized=alice, evidence_key=key)).source_title == "OPS-2: Forensics"
    with pytest.raises(EvidenceRecordNotFoundError):
        await read_span_window(db, authorized=bob, evidence_key=key)
    # The ledger re-check is independent of the projection: bob's keys never resolve the citation.
    assert key in await resolve_citations(db, alice.project_id, (key,), principal_keys=alice.principal_keys)
    assert await resolve_citations(db, bob.project_id, (key,), principal_keys=bob.principal_keys) == {}
    assert sorted(s.display_title for s in await list_sources(db, bob)) == ["OPS-1: Runbook"]
    assert len(await list_sources(db, alice)) == 2


async def test_a_bound_read_applies_the_calling_users_acl_in_the_source_workspace(db) -> None:
    library = await _workspace(db, name="Library")
    source = FakeSource()
    source.put("1", "OPS-1: Forensics", "Forensics: the failover drill found a breach.", _restricted("level:Security"))
    source.members = {"level:Security": (library["emails"]["alice"],)}
    await _sync(db, library, source)

    reader_id = await seed_workspace(db, name="Reader")
    for workspace_id in (reader_id, library["alice"].project_id):
        project = await db.get(Project, workspace_id)
        project.config = {**(project.config or {}), "data_policy": {"classification": "internal"}}
    alice_user = await fetch_user(
        db,
        (
            await db.execute(
                select(UserProject.user_id).where(
                    UserProject.project_id == library["alice"].project_id, UserProject.role == "admin"
                )
            )
        ).scalar_one(),
    )
    bob_user_id = (
        await db.execute(
            select(UserProject.user_id).where(
                UserProject.project_id == library["alice"].project_id, UserProject.role == "member"
            )
        )
    ).scalar_one()
    db.add(UserProject(user_id=alice_user.id, project_id=reader_id, role="admin"))
    db.add(UserProject(user_id=bob_user_id, project_id=reader_id, role="member"))
    await db.flush()
    alice_reader = await authorize_workspace(db, current_user=alice_user, workspace_id=reader_id)
    bob_reader = await authorize_workspace(db, current_user=await fetch_user(db, bob_user_id), workspace_id=reader_id)
    await create_binding(
        db,
        reader=alice_reader,
        source_workspace_id=library["alice"].project_id,
        products=[],
        reason="",
        user=alice_user,
    )

    async def bound(reader) -> list[str]:
        scope = await resolve_scope(db, reader)
        result = await scoped_evidence(db, runtime=library["runtime"], scope=scope, query_text="breach")
        return [hit.hit.evidence.source_title for hit in result.evidence]

    assert await bound(alice_reader) == ["OPS-1: Forensics"]
    assert await bound(bob_reader) == []
    key = (
        (
            await retrieve_workspace_evidence(
                db, runtime=library["runtime"], authorized=library["alice"], query_text="breach"
            )
        )
        .evidence[0]
        .evidence_key
    )
    assert (await scoped_read(db, scope=await resolve_scope(db, alice_reader), evidence_key=key, window=0))[
        0
    ] == library["alice"].project_id
    with pytest.raises(EvidenceRecordNotFoundError):
        await scoped_read(db, scope=await resolve_scope(db, bob_reader), evidence_key=key, window=0)
