"""Staged identity resolution, communities (tier 3), versioned ontology,
and the governed generate function."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import KnowledgeMergeProposal, KnowledgeOntologyVersion
from app.services.knowledge_graph import (
    KnowledgeLLMUnavailableError,
    build_communities,
    build_generate_fn,
    decide_merge_proposal,
    get_neighbors,
    ingest_ticket_record,
    propose_identity_merges,
    resolve_active_ontology,
    search_communities,
    upsert_edge,
    upsert_node,
)

# The generate function takes a required Workspace scope; the stub runtimes
# below use a non-gateway driver, so admission passes them through unchanged.
_WORKSPACE_ID = "kg-wave2-workspace"


@pytest.mark.asyncio
async def test_fuzzy_duplicates_become_needs_review_proposals_not_merges(db):
    token = uuid.uuid4().hex[:8]
    # Two DISTINCT person nodes with the same display name, created directly
    # (simulating federation imports that bypass alias resolution). They must
    # become a needs_review proposal — never a silent merge.
    from app.models import KnowledgeGraphNode

    a = KnowledgeGraphNode(
        id=str(uuid.uuid4()), node_type="person", node_key=f"p1-{token}",
        display_name=f"John Smith {token}", description="from confluence",
    )
    b = KnowledgeGraphNode(
        id=str(uuid.uuid4()), node_type="person", node_key=f"p2-{token}",
        display_name=f"John Smith {token}", description="from servicenow",
    )
    db.add_all([a, b])
    await db.flush()

    proposals = await propose_identity_merges(db, node_types=["person"])
    ours = [p for p in proposals if {p.keep_node_id, p.merge_node_id} == {a.id, b.id}]
    assert ours, "expected a needs_review proposal for the duplicate pair"
    assert ours[0].status == "needs_review"


@pytest.mark.asyncio
async def test_merge_proposal_apply_repoints_edges_and_aliases(db):
    token = uuid.uuid4().hex[:8]
    keep = await upsert_node(
        db, project_id=None, node_type="service", node_key=f"svc-a-{token}",
        display_name=f"Orders {token}", description="orders service", embed=False,
    )
    merge = await upsert_node(
        db, project_id=None, node_type="service", node_key=f"svc-b-{token}",
        display_name=f"Orders Svc {token}", description="duplicate orders service", embed=False,
    )
    other = await upsert_node(
        db, project_id=None, node_type="component", node_key=f"comp-{token}",
        display_name=f"Checkout {token}", description="component", embed=False,
    )
    await upsert_edge(
        db, project_id=None, edge_type="depends_on",
        source_node_id=merge.id, target_node_id=other.id, description="dup edge", embed=False,
    )

    proposal = KnowledgeMergeProposal(
        id=str(uuid.uuid4()), keep_node_id=keep.id, merge_node_id=merge.id,
        reason="test", signal="display_name", confidence=0.7,
    )
    db.add(proposal)
    await db.flush()

    result = await decide_merge_proposal(db, proposal_id=proposal.id, approve=True)
    assert result["status"] == "merged" and result["applied"] is True

    neighbors = await get_neighbors(db, node_id=keep.id)
    assert any(n["edge_type"] == "depends_on" for n in neighbors)
    await db.refresh(merge)
    assert merge.status == "merged"
    assert merge.properties.get("merged_into") == keep.id


@pytest.mark.asyncio
async def test_rejected_proposal_does_not_merge(db):
    token = uuid.uuid4().hex[:8]
    a = await upsert_node(
        db, project_id=None, node_type="team", node_key=f"t1-{token}",
        display_name=f"Platform {token}", embed=False,
    )
    b = await upsert_node(
        db, project_id=None, node_type="team", node_key=f"t2-{token}",
        display_name=f"Platform Team {token}", embed=False,
    )
    proposal = KnowledgeMergeProposal(
        id=str(uuid.uuid4()), keep_node_id=a.id, merge_node_id=b.id,
        reason="test", signal="display_name", confidence=0.6,
    )
    db.add(proposal)
    await db.flush()
    result = await decide_merge_proposal(db, proposal_id=proposal.id, approve=False)
    assert result["status"] == "rejected" and result["applied"] is False
    await db.refresh(b)
    assert b.status == "active"


@pytest.mark.asyncio
async def test_communities_cluster_connected_entities(db):
    token = uuid.uuid4().hex[:8]
    await ingest_ticket_record(
        db,
        project_id=None,
        ticket={
            "key": f"OCX-C{token}",
            "title": f"orders cluster {token}",
            "assignee_name": f"Dev {token}",
            "components": [f"orders-{token}", f"billing-{token}"],
        },
    )
    result = await build_communities(db)
    assert result["communities"] >= 1

    found = await search_communities(db, query=f"orders cluster {token}")
    assert found, "expected the ticket cluster to be findable via its summary"
    assert found[0]["size"] >= 2
    assert found[0]["summary_source"] == "deterministic"


@pytest.mark.asyncio
async def test_communities_use_llm_report_when_generate_provided(db):
    token = uuid.uuid4().hex[:8]
    await ingest_ticket_record(
        db,
        project_id=None,
        ticket={"key": f"OCX-R{token}", "title": f"payments {token}", "components": [f"pay-{token}"]},
    )

    async def fake_generate(_prompt: str) -> str:
        return f'{{"title": "Payments domain {token}", "summary": "This cluster handles payments {token}."}}'

    result = await build_communities(db, generate=fake_generate)
    assert result["llm_reports"] >= 1
    found = await search_communities(db, query=f"Payments domain {token}")
    assert found and found[0]["summary_source"] == "llm"


@pytest.mark.asyncio
async def test_active_ontology_version_overrides_defaults(db):
    row = KnowledgeOntologyVersion(
        id=str(uuid.uuid4()),
        project_scope="",
        version=999,
        status="active",
        entity_types=["service", "person"],
        relation_types=["depends_on"],
    )
    db.add(row)
    await db.flush()
    try:
        ontology = await resolve_active_ontology(db)
        assert ontology["entity_types"] == ["service", "person"]
        assert ontology["relation_types"] == ["depends_on"]

        # Draft versions are ignored (review gate).
        row.status = "draft"
        await db.flush()
        ontology = await resolve_active_ontology(db)
        assert "ticket" in ontology["entity_types"]  # defaults again
    finally:
        await db.delete(row)
        await db.flush()


@pytest.mark.asyncio
async def test_generate_fn_resolves_governed_runtimes(db, monkeypatch):
    calls: dict[str, object] = {}

    async def fake_resolve(_db, **_kwargs):
        return [
            {"provider_name": "stub", "model": "stub-model", "driver": "stub", "use_case_tags": ["extract"]}
        ]

    class _FakeClient:
        async def chat(self, *, messages, model, temperature, max_tokens):
            calls["model"] = model
            return {"content": '{"ok": true}'}

        async def close(self):
            return None

    import app.services.control_plane_service as cps
    from app.agent import providers as agent_providers

    monkeypatch.setattr(cps, "resolve_control_plane_runtimes", fake_resolve)
    monkeypatch.setattr(agent_providers, "get_provider", lambda **_kwargs: _FakeClient())

    generate = await build_generate_fn(db, project_ids=_WORKSPACE_ID, role="extract")
    output = await generate("hello")
    assert output == '{"ok": true}'
    assert calls["model"] == "stub-model"


@pytest.mark.asyncio
async def test_generate_fn_fails_loudly_without_runtimes(db, monkeypatch):
    async def fake_resolve(_db, **_kwargs):
        return []

    import app.services.control_plane_service as cps

    monkeypatch.setattr(cps, "resolve_control_plane_runtimes", fake_resolve)
    with pytest.raises(KnowledgeLLMUnavailableError):
        await build_generate_fn(db, project_ids=_WORKSPACE_ID, role="extract")


@pytest.mark.asyncio
async def test_no_duplicate_proposals_for_same_pair(db):
    token = uuid.uuid4().hex[:8]
    from app.models import KnowledgeGraphNode

    db.add_all(
        [
            KnowledgeGraphNode(
                id=str(uuid.uuid4()), node_type="system", node_key=f"s1-{token}",
                display_name=f"Core {token}",
            ),
            KnowledgeGraphNode(
                id=str(uuid.uuid4()), node_type="system", node_key=f"s2-{token}",
                display_name=f"Core {token}",
            ),
        ]
    )
    await db.flush()
    first = await propose_identity_merges(db, node_types=["system"])
    second = await propose_identity_merges(db, node_types=["system"])
    first_pairs = {(p.keep_node_id, p.merge_node_id) for p in first}
    second_pairs = {(p.keep_node_id, p.merge_node_id) for p in second}
    assert not (first_pairs & second_pairs), "the same pair must not be re-proposed"
    proposals = (await db.execute(select(KnowledgeMergeProposal))).scalars().all()
    pair_list = [(p.keep_node_id, p.merge_node_id) for p in proposals]
    assert len(pair_list) == len(set(pair_list))
