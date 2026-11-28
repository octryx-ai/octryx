"""Real DB receiver proof and isolated child allocation; never executes a child before commit."""
from __future__ import annotations

import copy
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import (
    AgentDefinition,
    BuiltInToolConfig,
    CodeRepository,
    ConnectorNamedConnection,
    FlowDefinitionVersion,
    Message,
    Session,
    UserRole,
    WorkflowRun,
    WorkflowRunSession,
)
from app.models.project.knowledge_evidence import KnowledgeEvidenceSource, KnowledgeSourceHead, KnowledgeSourceRevision
from app.models.project.knowledge_source_acl import KnowledgeSourceAcl, KnowledgeSourceAclPrincipal
from app.models.runtime.workflow_handoff import WorkflowHandoff, WorkflowHandoffResponse
from app.services.knowledge.access.acl_keys import reader_principal_keys
from app.services.workflow_runs.handoff import service
from app.services.workflow_runs.handoff.allocation import PENDING_COMMIT, allocate_child
from app.services.workflow_runs.handoff.contract import canonical_hash
from app.services.workflow_runs.handoff.permissions import rights_evaluator
from app.services.workflow_runs.phase_outputs import HANDOFF_KEY
from app.services.workflow_runs.records import RUN_METADATA_KEY
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.team_handoff_support import action, counts, setup_case

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("scripted_pool")]


@pytest.fixture(autouse=True)
async def tables(db):
    connection = await db.connection()
    await connection.run_sync(lambda bind: [table.create(bind, checkfirst=True) for table in
        (WorkflowHandoff.__table__, WorkflowHandoffResponse.__table__)])


async def prepared(db):
    case = await setup_case(db)
    # The service-only fixture intentionally omits an executable graph; this factory uses a real valid child.
    version = await db.get(FlowDefinitionVersion, case.row.child_descriptor["version_id"])
    version.definition_json = {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "finish", "source_node_id": "start", "target_node_id": "done"}]}
    case.row.child_descriptor = {**case.row.child_descriptor, "checksum": canonical_hash(version.definition_json)}
    case.row.payload_hash = canonical_hash(service.binding_payload(case.row))
    case.repository = CodeRepository(project_id=case.parent.project_id, name="demo-team/test", provider="bitbucket",
        repo_root="/not-a-checkout", remote_url="https://bitbucket.org/demo-team/test.git",
        config_json={"operation_policy": {"read": True, "branch": False, "write": False, "pr": False}})
    case.connector = BuiltInToolConfig(project_id=case.parent.project_id, tool_name="bitbucket", is_active=True,
                                      config={})
    db.add_all([case.repository, case.connector])
    await db.flush()
    return case


async def proof(db, case, *, scope=None, actor=None, runtime=None):
    return await rights_evaluator(db=db, actor=actor or case.p, scope=scope or case.row.contract["scope"],
                                 envelopes=case.row.envelopes, runtime_target=runtime or {"kind": "server"})


async def test_ordinary_viewer_can_accept_without_grants_parent_session_or_context_copy(db, monkeypatch):
    case = await prepared(db)
    case.parent.context = {**case.parent.context, "local_path": "/sender/private", "credentials": "SECRET_CANARY",
                           "messages": [{"text": "TRANSCRIPT_CANARY"}], "jira_project_key": "SENDER_ONLY"}
    case.parent.branch = "sender-private-branch"
    parent_session = Session(user_id=case.sender.id, project_id=case.parent.project_id, origin="chat",
                             metadata_={"sender_only": "SESSION_CANARY"})
    db.add(parent_session)
    await db.flush()
    db.add_all([Message(session_id=parent_session.id, role="user", content="MESSAGE_CANARY"),
                WorkflowRunSession(run_id=case.parent.id, session_id=parent_session.id, role="main", active=True)])
    await db.flush()
    before = await counts(db)
    before_roles = (await db.execute(select(func.count()).select_from(UserRole))).scalar_one()
    from app.services.workflow_runs import engine, records
    from app.services.workflow_runs.platform import dispatch

    async def no_execution(*args, **kwargs):
        raise AssertionError("No execution or provider dispatch is allowed during atomic acceptance")

    monkeypatch.setattr(records, "start_run", no_execution)
    monkeypatch.setattr(engine, "_run_from", no_execution)
    monkeypatch.setattr(engine, "resolve_current_node", no_execution)
    monkeypatch.setattr(dispatch, "dispatch_tool", no_execution)
    binding = await service.accept_handoff(db, case.row.id, case.p, action(case.row),
                                           rights_evaluator=rights_evaluator, allocator=allocate_child)
    child = await db.get(WorkflowRun, binding["child_run_id"])
    session = await db.get(Session, binding["receiver_session_id"])
    links = (await db.execute(select(WorkflowRunSession).where(
        WorkflowRunSession.run_id == child.id, WorkflowRunSession.active.is_(True)))).scalars().all()
    assert await counts(db) == tuple(n + 1 for n in before)
    assert child.requested_by == session.user_id == case.p.id and session.parent_session_id is None
    assert (child.status, child.waiting_kind, child.current_node_id) == ("waiting", PENDING_COMMIT, None)
    assert child.branch is None and child.work_item_id is None
    assert len(links) == 1 and links[0].role == "main" and links[0].session_id == session.id
    assert child.context[HANDOFF_KEY] == {"definition_of_ready": case.row.envelopes["definition_of_ready"]["envelope"]["record"]}
    assert child.context["handoff_approved_envelopes"] == case.row.envelopes
    assert child.context["handoff_binding"]["owner_epoch"] == binding["owner_epoch"] == 1
    assert child.context["runtime_target"]["chosen_by"] == case.p.id
    assert "CANARY" not in str(child.context) and "sender-private" not in str(child.context)
    assert (await db.execute(select(func.count()).select_from(UserRole))).scalar_one() == before_roles
    assert session.id != parent_session.id
    assert session.metadata_[RUN_METADATA_KEY] == child.id
    assert parent_session.user_id == case.sender.id and parent_session.metadata_["sender_only"] == "SESSION_CANARY"
    assert not (await db.execute(select(Message).where(Message.session_id == session.id))).scalars().all()
    assert "CANARY" not in str(session.metadata_)


@pytest.mark.parametrize("cause", ["invalid_graph", "inactive_agent"])
async def test_published_child_graph_and_current_phase_agent_are_checked_before_allocation(db, cause):
    case = await prepared(db)
    version = await db.get(FlowDefinitionVersion, case.row.child_descriptor["version_id"])
    from app.services.workflow_runs.graph_validation import validate_phased_definition
    from tests.phased_workflow_fixtures import phased_definition

    if cause == "invalid_graph":
        version.definition_json = {"execution_kind": "phased"}
    else:
        version.definition_json = phased_definition()
        assert validate_phased_definition(version.definition_json)["valid"]
        engineer = (await db.execute(select(AgentDefinition).where(
            AgentDefinition.builtin_key == "engineer"))).scalar_one()
        engineer.is_active = False
    case.row.child_descriptor = {**case.row.child_descriptor, "checksum": canonical_hash(version.definition_json)}
    await db.flush()
    before = await counts(db)
    with pytest.raises(HTTPException) as refused:
        await allocate_child(db=db, parent=case.parent, handoff=case.row, actor=case.p,
                             runtime_proof=await proof(db, case))
    assert refused.value.detail["reason"] == "needs_configuration"
    assert ("graph" if cause == "invalid_graph" else "agent_inactive") in refused.value.detail["message"]
    assert await counts(db) == before


@pytest.mark.parametrize("cause", ["source", "repository", "connector", "work_item", "runtime", "service", "missing_repo"])
async def test_missing_or_denied_receiver_rights_have_zero_allocations(db, cause):
    case = await prepared(db)
    before = await counts(db)
    scope = copy.deepcopy(case.row.contract["scope"])
    runtime = {"kind": "server"}
    if cause == "repository":
        case.repository.config_json = {"operation_policy": {"read": False}}
    elif cause == "connector":
        case.connector.is_active = False
    elif cause == "missing_repo":
        case.repository.is_active = False
    elif cause == "service":
        scope["service_ids"] = [str(uuid4())]
    elif cause == "source":
        scope["source_ids"] = [str(uuid4())]
    elif cause == "work_item":
        scope["work_item_id"] = str(uuid4())
    else:
        runtime = {"kind": "device", "device_id": str(uuid4()), "folder": "/private"}
    await db.flush()
    with pytest.raises(HTTPException):
        await rights_evaluator(db=db, actor=case.p, scope=scope, envelopes=case.row.envelopes, runtime_target=runtime)
    assert await counts(db) == before


async def test_source_acl_uses_actual_receiver_principal_and_rechecks_revocation(db):
    case = await prepared(db)
    source = KnowledgeEvidenceSource(project_id=case.parent.project_id, source_key="controlled-source",
                                     display_title="Controlled evidence")
    db.add(source)
    await db.flush()
    revision = KnowledgeSourceRevision(source_id=source.id, project_id=case.parent.project_id, revision_ordinal=1,
        content_sha256="a" * 64, byte_size=0, media_type="text/plain", object_bucket="fixture", object_key="empty",
        parser_name="fixture", parser_version="1", parser_sandbox="none")
    db.add(revision)
    await db.flush()
    db.add(KnowledgeSourceHead(source_id=source.id, project_id=case.parent.project_id,
                              wanted_revision_id=revision.id, current_revision_id=revision.id))
    acl = KnowledgeSourceAcl(project_id=case.parent.project_id, source_key=source.source_key, restriction="restricted")
    principal = KnowledgeSourceAclPrincipal(project_id=case.parent.project_id, source_key=source.source_key,
                                            principal_key=reader_principal_keys(case.p)[0])
    db.add_all([acl, principal])
    await db.flush()
    scope = copy.deepcopy(case.row.contract["scope"])
    scope["source_ids"] = [source.id]
    result = await proof(db, case, scope=scope)
    assert result["actor_id"] == case.p.id
    with pytest.raises(HTTPException) as refused:
        await proof(db, case, scope=scope, actor=case.q)
    assert refused.value.status_code == 403
    await db.delete(principal)
    await db.flush()
    with pytest.raises(HTTPException):
        await proof(db, case, scope=scope)


@pytest.mark.parametrize("head_state", ["withdrawn", "unprojected", "lagging"])
async def test_source_requires_a_current_matching_non_withdrawn_head(db, head_state):
    case = await prepared(db)
    source = KnowledgeEvidenceSource(project_id=case.parent.project_id, source_key="current-proof",
                                     display_title="Current source")
    db.add(source)
    await db.flush()
    revisions = [KnowledgeSourceRevision(source_id=source.id, project_id=case.parent.project_id,
        revision_ordinal=ordinal, content_sha256=str(ordinal) * 64, byte_size=0, media_type="text/plain",
        object_bucket="fixture", object_key=str(ordinal), parser_name="fixture", parser_version="1",
        parser_sandbox="none") for ordinal in (1, 2)]
    db.add_all(revisions)
    await db.flush()
    head = KnowledgeSourceHead(source_id=source.id, project_id=case.parent.project_id,
        wanted_revision_id=None if head_state == "withdrawn" else revisions[1].id,
        current_revision_id=None if head_state == "unprojected" else revisions[0].id)
    db.add(head)
    await db.flush()
    scope = copy.deepcopy(case.row.contract["scope"])
    scope["source_ids"] = [source.id]
    before = await counts(db)
    with pytest.raises(HTTPException) as refused:
        await proof(db, case, scope=scope)
    assert refused.value.detail["reason"] == "needs_configuration"
    assert await counts(db) == before


async def test_named_connection_visibility_is_workspace_specific_and_never_resolves_credentials(db, monkeypatch):
    case = await prepared(db)
    entry = BuiltInToolConfig(project_id=case.parent.project_id, tool_name="confluence", is_active=True, config={})
    connection = ConnectorNamedConnection(tool_name="confluence", project_id=case.parent.project_id,
        scope_key=case.parent.project_id, name="controlled-docs", config={"url": "https://c.example/wiki"},
        bound_scopes=["TEST"])
    db.add_all([entry, connection])
    await db.flush()
    scope = copy.deepcopy(case.row.contract["scope"])
    scope["connection_ids"] = [connection.id]
    from app.services.named_connections import resolver, store

    async def forbid_secrets(*args, **kwargs):
        raise AssertionError("Rights proof never resolves connector credentials")

    monkeypatch.setattr(store, "resolved_config", forbid_secrets)
    monkeypatch.setattr(resolver, "resolved_config", forbid_secrets)
    assert (await proof(db, case, scope=scope))["allowed"]
    entry.is_active = False
    await db.flush()
    with pytest.raises(HTTPException):
        await proof(db, case, scope=scope)


async def test_foreign_connection_and_untyped_source_urls_hold_without_metadata_copy(db):
    case = await prepared(db)
    foreign = await seed_workspace(db)
    connection = ConnectorNamedConnection(tool_name="confluence", project_id=foreign, scope_key=foreign,
        name="foreign", config={}, bound_scopes=["OTHER"])
    db.add(connection)
    await db.flush()
    scope = copy.deepcopy(case.row.contract["scope"])
    scope["connection_ids"] = [connection.id]
    with pytest.raises(HTTPException):
        await proof(db, case, scope=scope)
    envelopes = copy.deepcopy(case.row.envelopes)
    envelopes["definition_of_ready"]["envelope"]["record"]["sources"] = ["https://foreign.example/protected"]
    with pytest.raises(HTTPException) as refused:
        await rights_evaluator(db=db, actor=case.p, scope=case.row.contract["scope"], envelopes=envelopes,
                              runtime_target={"kind": "server"})
    assert refused.value.detail["reason"] == "needs_configuration"


async def test_allocator_rechecks_actual_version_checksum_and_proof_before_creating_any_row(db):
    case = await prepared(db)
    before = await counts(db)
    current = await proof(db, case)
    case.row.child_descriptor = {**case.row.child_descriptor, "checksum": "sha256:" + "0" * 64}
    with pytest.raises(HTTPException):
        await allocate_child(db=db, parent=case.parent, handoff=case.row, actor=case.p, runtime_proof=current)
    assert await counts(db) == before
    from app.models import FlowDefinitionVersion
    version = await db.get(FlowDefinitionVersion, case.row.child_descriptor["version_id"])
    case.row.child_descriptor = {**case.row.child_descriptor, "checksum": canonical_hash(version.definition_json)}
    with pytest.raises(HTTPException):
        await allocate_child(db=db, parent=case.parent, handoff=case.row, actor=case.p,
                             runtime_proof={**current, "actor_id": case.sender.id})
    assert await counts(db) == before


async def test_actual_foreign_work_item_is_denied_even_with_existing_workspace_membership(db):
    from app.models.runtime.secure_work import WorkItem

    case = await prepared(db)
    foreign = await seed_workspace(db)
    item = WorkItem(project_id=foreign, source_type="jira", source_instance="fixture", source_key="FOREIGN-1",
                    title="Outside approved workspace")
    db.add(item)
    await db.flush()
    scope = copy.deepcopy(case.row.contract["scope"])
    scope["work_item_id"] = item.id
    with pytest.raises(HTTPException) as refused:
        await proof(db, case, scope=scope)
    assert refused.value.status_code == 404  # another Workspace's item answers like a missing one


async def test_allocator_never_trusts_old_proof_when_repository_permission_is_revoked(db):
    case = await prepared(db)
    allowed = await proof(db, case)
    before = await counts(db)
    case.repository.config_json = {"operation_policy": {"read": False}}
    await db.flush()
    with pytest.raises(HTTPException) as refused:
        await allocate_child(db=db, parent=case.parent, handoff=case.row, actor=case.p, runtime_proof=allowed)
    assert refused.value.status_code == 403
    assert await counts(db) == before


@pytest.mark.parametrize("field,value", [("source_ids", ["outside"]), ("connection_id", "outside"),
                                          ("work_item_id", "outside")])
async def test_approved_envelope_references_must_fit_exact_authorised_scope(db, field, value):
    case = await prepared(db)
    envelopes = copy.deepcopy(case.row.envelopes)
    envelopes["definition_of_ready"]["envelope"]["record"][field] = value
    with pytest.raises(HTTPException) as refused:
        await rights_evaluator(db=db, actor=case.p, scope=case.row.contract["scope"], envelopes=envelopes,
                              runtime_target={"kind": "server"})
    assert refused.value.detail["reason"] == "needs_configuration"


async def test_normalized_device_defaults_are_preserved_without_actor_substitution(db, monkeypatch):
    from app.services.workflow_runs.handoff import permissions

    case = await prepared(db)
    selected = {"kind": "device", "device_id": str(uuid4()), "folder": "/receiver/project"}
    checked = []

    async def normalized(db, *, user, project_id, raw):
        checked.append((user.id, project_id, copy.deepcopy(raw)))
        return {**raw, "profile": "governed", "model": "", "device_name": "Receiver device"}

    monkeypatch.setattr(permissions, "validate_target", normalized)
    result = await proof(db, case, runtime=selected)
    assert checked == [(case.p.id, case.parent.project_id, selected)]
    assert result["actor_id"] == case.p.id
    assert result["runtime_target"]["profile"] == "governed"
    assert "device_name" in result["runtime_target"]
