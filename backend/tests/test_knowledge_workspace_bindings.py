"""Workspace bindings: a Workspace reads a library Workspace without copying it.

Contract tests over two real ledgers and the fake Evidence index: a binding needs the authoring role on both
sides and a compatible data classification; search, read and the search tool span the reader and its
bound sources, bounded by the binding's products and never transitive; revocation and a raised
classification take effect on the next read; a bound read is admitted for the reader's data policy.
"""

from __future__ import annotations

import pytest

from app.models import Project
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.access.bindings import (
    BindingRefusedError,
    create_binding,
    resolve_scope,
    revoke_binding,
)
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.ledger.errors import EvidenceRecordNotFoundError, WorkspaceNotAccessibleError
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.scoped import STATE_OUTSIDE_BINDING, scoped_evidence, scoped_read
from app.services.knowledge.runtime import set_evidence_runtime
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace, tool_context

QUERY = "failover exercise"



async def _classify(db, workspace_id: str, classification: str) -> None:
    project = await db.get(Project, workspace_id)
    project.config = {**(project.config or {}), "data_policy": {"classification": classification}}
    await db.flush()


async def _world(db):
    """A project Workspace, a library Workspace, and an unrelated one; one admin in all three."""
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    project_id = await seed_workspace(db, name="Acme Orders")
    user_id = await seed_member(db, workspace_id=project_id, role="admin")
    library_id = await seed_workspace(db, name="Spring library")
    other_id = await seed_workspace(db, name="Other")
    from app.models.security.user import UserProject

    for workspace_id in (library_id, other_id):
        db.add(UserProject(user_id=user_id, project_id=workspace_id, role="admin"))
    await db.flush()
    user = await fetch_user(db, user_id)
    documents = {
        project_id: [("runbook", "Acme Orders runbook: the failover exercise happens weekly.\n", "acme-orders")],
        library_id: [
            ("boot4", "Spring Boot 4.0 migration: the failover exercise config moved.\n", "spring-boot"),
            ("shipping", "Shipping protocol note: the failover exercise is out of scope.\n", "shipping-protocol"),
        ],
        other_id: [("other", "Other team: the failover exercise is monthly.\n", "acme-orders")],
    }
    authorized = {}
    for workspace_id, items in documents.items():
        await _classify(db, workspace_id, "internal")
        authorized[workspace_id] = await authorize_workspace(db, current_user=user, workspace_id=workspace_id)
        for key, text, product in items:
            await ingest_text_source(
                db,
                runtime=runtime,
                authorized=authorized[workspace_id],
                source_key=key,
                display_title=key,
                declared_media_type="text/markdown",
                data=text.encode(),
                created_by=user_id,
                products=product,
            )
    projector = EvidenceProjector(runtime)
    while await projector.project_once(db, worker_id="test") is not None:
        pass
    return runtime, user, authorized, project_id, library_id, other_id


async def test_a_binding_needs_both_sides_and_a_compatible_classification(db):
    runtime, user, authorized, project_id, library_id, other_id = await _world(db)
    reader = authorized[project_id]
    with pytest.raises(BindingRefusedError) as refused:
        await create_binding(db, reader=reader, source_workspace_id=project_id, products=[], reason="", user=user)
    assert refused.value.reason == "self_binding"

    stranger_id = await seed_member(db, workspace_id=project_id, role="admin")
    stranger = await fetch_user(db, stranger_id)
    stranger_reader = await authorize_workspace(db, current_user=stranger, workspace_id=project_id)
    # No role in the library: indistinguishable from a library that does not exist.
    with pytest.raises(WorkspaceNotAccessibleError):
        await create_binding(
            db, reader=stranger_reader, source_workspace_id=library_id, products=[], reason="", user=stranger
        )

    await _classify(db, library_id, "confidential")
    with pytest.raises(BindingRefusedError) as refused:
        await create_binding(db, reader=reader, source_workspace_id=library_id, products=[], reason="", user=user)
    assert refused.value.reason == "classification_above_reader"


async def test_search_and_read_span_the_bound_library_within_its_products_and_never_transitively(db):
    runtime, user, authorized, project_id, library_id, other_id = await _world(db)
    await create_binding(
        db,
        reader=authorized[project_id],
        source_workspace_id=library_id,
        products=["spring-boot"],
        reason="",
        user=user,
    )
    # The library reads a third Workspace; the project must not see it through the library.
    await create_binding(
        db, reader=authorized[library_id], source_workspace_id=other_id, products=[], reason="", user=user
    )
    scope = await resolve_scope(db, authorized[project_id])
    assert [source.name for source in scope.sources] == ["Spring library"]

    result = await scoped_evidence(db, runtime=runtime, scope=scope, query_text=QUERY)
    found = {(hit.workspace_name, hit.hit.evidence.source_title) for hit in result.evidence}
    assert found == {("Acme Orders", "runbook"), ("Spring library", "boot4")}

    only_shipping = await scoped_evidence(db, runtime=runtime, scope=scope, query_text=QUERY, products=["shipping-protocol"])
    assert only_shipping.workspace_states[library_id] == {"state": STATE_OUTSIDE_BINDING}

    boot = next(hit for hit in result.evidence if hit.workspace_name == "Spring library")
    workspace_id, read = await scoped_read(db, scope=scope, evidence_key=boot.hit.evidence.evidence_key, window=0)
    assert workspace_id == library_id and "config moved" in read.text

    # The shipping document lives in the library too, but outside the binding's products.
    unbound = await scoped_evidence(
        db, runtime=runtime, scope=await resolve_scope(db, authorized[library_id]), query_text=QUERY
    )
    shipping_hit = next(hit for hit in unbound.evidence if hit.hit.evidence.source_title == "shipping")
    with pytest.raises(EvidenceRecordNotFoundError):
        await scoped_read(db, scope=scope, evidence_key=shipping_hit.hit.evidence.evidence_key, window=0)

    source = scope.sources[0].authorized
    assert source.admission_project_id == project_id and not source.may_author


async def test_the_search_tool_names_each_workspace_and_revocation_or_reclassification_takes_effect(db):
    runtime, user, authorized, project_id, library_id, other_id = await _world(db)
    binding = await create_binding(
        db, reader=authorized[project_id], source_workspace_id=library_id, products=[], reason="", user=user
    )
    context = tool_context(user_id=user.id, project_id=project_id, project_ids=[project_id], db=db)
    answer = await KnowledgeSearchTool().execute({"query": QUERY}, context)
    assert {item["workspace"] for item in answer["evidence"]} == {"Acme Orders", "Spring library"}
    assert "Spring library" in answer["bound_workspaces"]

    await _classify(db, library_id, "confidential")
    scope = await resolve_scope(db, authorized[project_id])
    assert scope.sources == () and scope.skipped == {library_id: "classification_above_reader"}

    await _classify(db, library_id, "internal")
    await revoke_binding(db, workspace=authorized[library_id], binding_id=binding.id, user=user)
    answer = await KnowledgeSearchTool().execute({"query": QUERY}, context)
    assert {item["workspace"] for item in answer["evidence"]} == {"Acme Orders"}


async def test_changes_come_from_the_first_workspace_in_scope_that_has_extracted_facts(db, monkeypatch):
    from app.services.knowledge.temporal import scoped_changes as module
    from app.services.knowledge.temporal.changes_facts import ChangesResult

    runtime, user, authorized, project_id, library_id, other_id = await _world(db)
    await create_binding(
        db,
        reader=authorized[project_id],
        source_workspace_id=library_id,
        products=["spring-boot"],
        reason="",
        user=user,
    )
    scope = await resolve_scope(db, authorized[project_id])
    asked: list[str] = []

    async def changes(db, *, runtime, authorized, product, **options):
        asked.append(authorized.project_id)
        state = "ok" if authorized.project_id == library_id else "no_sources"
        return ChangesResult(state, "spring-boot", None, "4.0", ("4.0",), (), 0)

    monkeypatch.setattr(module, "knowledge_changes", changes)
    workspace_id, result = await module.scoped_changes(
        db, runtime=runtime, scope=scope, product="spring-boot", to_version="4.0"
    )
    assert (workspace_id, result.state, asked) == (library_id, "ok", [project_id, library_id])

    asked.clear()
    workspace_id, result = await module.scoped_changes(
        db, runtime=runtime, scope=scope, product="acme-orders", to_version="5.2"
    )
    # Outside the binding's products the library is not asked; the reader's own state stands.
    assert (workspace_id, result.state, asked) == (project_id, "no_sources", [project_id])
