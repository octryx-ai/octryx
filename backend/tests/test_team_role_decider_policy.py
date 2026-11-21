"""Current membership and final locked decision policy, with no execution-identity changes."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update

from app.models import (
    FlowDefinition,
    FlowDefinitionVersion,
    IdentityGroup,
    ProjectGroup,
    Role,
    User,
    UserGroup,
    UserRole,
)
from app.models.runtime.secure_work import WorkItem
from app.models.runtime.workflow_run import WorkflowRun
from app.models.security.user import UserProject
from app.services.workflow_runs import decider
from app.services.workflow_runs.graph import PhasedNode
from app.services.workflow_runs.records import WorkflowRunError
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_outsider, seed_workspace
from tests.work_role_support import assign_seed_role, set_seed_role_active

pytestmark = pytest.mark.asyncio


async def setup_case(db, policy="role:product_manager"):
    project = await seed_workspace(db)
    admin_id = await seed_member(db, workspace_id=project, role="admin")
    requester_id = await seed_member(db, workspace_id=project, role="member")
    pm_id = await seed_member(db, workspace_id=project, role="member")
    admin, requester, pm = [await fetch_user(db, ident) for ident in (admin_id, requester_id, pm_id)]
    config = {"subject": "advance", **({"decider": policy} if policy is not None else {})}
    node = PhasedNode("confirm", "user_confirmation", "Confirm", config)
    flow = FlowDefinition(key=f"decider-{uuid.uuid4().hex}", name="Decider fixture", project_id=project,
                          status="published", created_by=admin.id)
    db.add(flow)
    await db.flush()
    version = FlowDefinitionVersion(flow_id=flow.id, status="published", created_by=admin.id,
        definition_json={"execution_kind": "phased", "nodes": [
            {"id": "start", "type": "start"}, {"id": node.id, "type": node.kind, "config": config},
            {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
            "edges": [{"id": "first", "source_node_id": "start", "target_node_id": node.id},
                {"id": "final", "source_node_id": node.id, "target_node_id": "done", "when": "confirmed"}]})
    db.add(version)
    await db.flush()
    flow.current_version_id = version.id
    run = WorkflowRun(workflow_kind="phased", workflow_key=flow.key, project_id=project, requested_by=requester.id,
        flow_definition_version_id=version.id, current_node_id=node.id, status="waiting",
        node_state={"entry": 4}, context={"execution_identity": requester.id, "runtime_target": "server"})
    db.add(run)
    await db.commit()
    return SimpleNamespace(project=project, admin=admin, requester=requester, pm=pm, run=run, node=node)


async def assign_pm(db, case):
    return await assign_seed_role(db, case.project, "product_manager", user_id=case.pm.id)


async def test_role_decider_is_not_requester_and_never_rebinds_execution_identity(db):
    case = await setup_case(db)
    await assign_pm(db, case)
    resolution = await decider.require_node_decider(db, case.run, case.pm)
    assert resolution.user_ids == (case.pm.id,)
    assert case.run.requested_by == case.requester.id
    assert case.run.context == {"execution_identity": case.requester.id, "runtime_target": "server"}
    with pytest.raises(WorkflowRunError) as refused:
        await decider.require_node_decider(db, case.run, case.requester)
    assert refused.value.code == "not_decider"


async def test_global_admin_without_authored_role_has_no_decision_bypass(db):
    case = await setup_case(db)
    await assign_pm(db, case)
    outsider = await fetch_user(db, await seed_outsider(db))
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=outsider.id, role_id=admin_role.id))
    await db.commit()
    assert not await decider.may_decide(db, case.run, case.node, outsider)
    with pytest.raises(WorkflowRunError) as refused:
        await decider.require_node_decider(db, case.run, outsider)
    assert refused.value.code == "not_decider"


async def test_a_missing_role_is_an_explicit_hold_not_requester_fallback(db):
    case = await setup_case(db)
    result = await decider.resolve_decider(db, case.run, case.node)
    assert not result.configured and result.reason == "role_unresolved"
    with pytest.raises(WorkflowRunError) as refused:
        await decider.require_node_decider(db, case.run, case.requester)
    assert refused.value.code == "decider_unresolved"


async def test_role_revocation_between_offer_and_decision_is_rechecked(db):
    case = await setup_case(db)
    role = await assign_pm(db, case)
    assert await decider.may_decide(db, case.run, case.node, case.pm)
    await set_seed_role_active(db, role, False)
    with pytest.raises(WorkflowRunError) as refused:
        await decider.require_node_decider(db, case.run, case.pm)
    assert refused.value.code == "decider_unresolved"


@pytest.mark.parametrize("change", ["membership", "inactive", "service"])
async def test_lost_membership_or_account_authority_revokes_an_existing_work_role(db, change):
    case = await setup_case(db)
    await assign_pm(db, case)
    if change == "membership":
        await db.execute(delete(UserProject).where(UserProject.user_id == case.pm.id,
                                                   UserProject.project_id == case.project))
    elif change == "inactive":
        await db.execute(update(User).where(User.id == case.pm.id).values(is_active=False))
    else:
        await db.execute(update(User).where(User.id == case.pm.id).values(account_type="service"))
    await db.commit()
    assert not await decider.may_decide(db, case.run, case.node, case.pm)


async def test_unauthored_and_authored_requester_both_need_current_membership(db):
    case = await setup_case(db, None)
    await db.execute(delete(UserProject).where(UserProject.user_id == case.requester.id))
    await db.commit()
    authored = PhasedNode("confirm", "user_confirmation", "Confirm", {"decider": "requester"})
    for node in (case.node, authored):
        result = await decider.resolve_decider(db, case.run, node)
        assert not result.configured and result.reason == "requester_unresolved"
        assert not result.allows(case.requester.id) and not result.allows(case.admin.id)


@pytest.mark.parametrize("policy", ["", "role:", "role:unknown", "user:someone", None, {"user": "pm"}])
async def test_authored_invalid_decider_never_defaults_open(db, policy):
    case = await setup_case(db)
    node = PhasedNode("confirm", "user_confirmation", "Confirm", {"decider": policy})
    result = await decider.resolve_decider(db, case.run, node)
    assert not result.configured and result.reason == "decider_unresolved"


async def test_handoff_hint_is_never_taken_as_authoritative_accepted_ownership(db):
    case = await setup_case(db, "handoff_owner")
    case.run.context = {"handoff_owner": case.pm.id, "handoff": {"owner_id": case.pm.id, "accepted": True}}
    result = await decider.resolve_decider(db, case.run, case.node)
    assert not result.configured and result.reason == "handoff_owner_unresolved"


async def test_item_owner_matches_assignee_and_holds_when_missing_or_foreign(db):
    case = await setup_case(db, "item_owner")
    item = WorkItem(project_id=case.project, source_type="jira", source_instance="fixture",
        source_key=f"CASE-{uuid.uuid4().hex}", title="Example", assignee=case.pm.email)
    db.add(item)
    await db.flush()
    case.run.work_item_id = item.id
    assert (await decider.resolve_decider(db, case.run, case.node)).allows(case.pm.id)
    item.assignee = None
    await db.flush()
    assert (await decider.resolve_decider(db, case.run, case.node)).reason == "item_owner_unresolved"
    item.assignee = case.pm.email
    item.project_id = await seed_workspace(db)
    await db.flush()
    assert (await decider.resolve_decider(db, case.run, case.node)).reason == "item_owner_unresolved"


async def test_current_group_work_role_rechecks_group_and_workspace_links(db):
    case = await setup_case(db)
    group = IdentityGroup(name=f"group-{uuid.uuid4().hex}", is_active=True)
    db.add(group)
    await db.flush()
    db.add_all([ProjectGroup(project_id=case.project, group_id=group.id),
                UserGroup(user_id=case.pm.id, group_id=group.id)])
    # The group is the person's only path into the Workspace.
    await db.execute(delete(UserProject).where(UserProject.user_id == case.pm.id,
                                               UserProject.project_id == case.project))
    await db.flush()
    await assign_seed_role(db, case.project, "product_manager", group_id=group.id)
    assert (await decider.resolve_decider(db, case.run, case.node)).allows(case.pm.id)
    group.is_active = False
    await db.flush()
    assert not (await decider.resolve_decider(db, case.run, case.node)).configured
    group.is_active = True
    await db.execute(delete(ProjectGroup).where(ProjectGroup.group_id == group.id))
    await db.flush()
    assert not (await decider.resolve_decider(db, case.run, case.node)).configured


async def test_deputy_is_routing_information_not_an_implicit_decision_grant(db):
    case = await setup_case(db, "requester")
    await assign_seed_role(db, case.project, "doc_owner", user_id=case.pm.id)
    node = PhasedNode("confirm", "user_confirmation", "Confirm", {"decider": "requester", "deputy": "role:doc_owner"})
    result = await decider.resolve_decider(db, case.run, node)
    assert result.deputy_user_ids == (case.pm.id,)
    assert result.allows(case.requester.id) and not result.allows(case.pm.id)


async def test_final_decider_uses_current_pinned_graph_not_a_spoofed_caller_node(db):
    case = await setup_case(db)
    await assign_pm(db, case)
    # The actual pinned graph still names product_manager, not the caller's requester assumption.
    with pytest.raises(WorkflowRunError) as refused:
        await decider.require_node_decider(db, case.run, case.requester, expected_node_id=case.node.id)
    assert refused.value.code == "not_decider"
    case.run.current_node_id = "done"
    await db.commit()
    with pytest.raises(WorkflowRunError) as stale:
        await decider.require_node_decider(db, case.run, case.pm, expected_node_id="confirm")
    assert stale.value.code == "decision_stale"
