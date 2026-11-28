"""Policy UX: the request's user and session reach every enforcement point."""

from __future__ import annotations

import uuid

import pytest

from app.models import Project
from app.services.agent_gateway.seat_policy import workspace_seat_decision
from app.services.classification_tool_policy import REASON_CEDAR_POLICY_DENIED, classification_tool_decision
from app.services.model_gateway.data_policy.classification import WorkspaceDataClassification
from app.services.model_gateway.litellm.project_admission import build_project_model_admission
from app.services.policy_engine.points import remote_query
from app.services.policy_engine.principals import clear_principal_cache
from app.services.policy_engine.request_principal import (
    current_principal,
    load_seat_principal,
    policy_principal_scope,
    principal_memo_key,
)
from app.services.policy_engine.runtime import MODE_OFF, PolicyRuntime, set_policy_runtime
from tests.policy_engine_support import BASE, bearer, grant_role, make_user, use_custom_policies

ROLE_POLICY = ('@id("ops-no-{action}")\nforbid (principal in Role::"{role}", action == Action::"{action}", resource);\n')
SEAT_SESSION_POLICY = ('@id("no-seat-sessions")\nforbid (principal, action == Action::"use_seat", resource)\n'
                       'when { principal is AgentSession && principal.profile == "seat" };\n')


async def _workspace(db, **config) -> str:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True,
                      config={"data_policy": {"classification": "internal"},
                              "model_policy": {"allowed_aliases": ["octryx-sonnet"]}, **config})
    db.add(project)
    await db.commit()
    return project.id


async def _member(db, role: str) -> str:
    user = await make_user(db, admin=False)
    await grant_role(db, user, role)
    return user


@pytest.mark.asyncio
async def test_the_scope_binds_the_principal_and_restores_the_previous_one(client, db):
    member, other = await _member(db, "ops"), await make_user(db, admin=False)
    assert current_principal() is None
    async with policy_principal_scope(member) as outer:
        assert current_principal() is outer and outer[0].label() == f"User::{member}"
        assert {"type": "Role", "id": "ops"} in outer[1][0]["parents"]
        first_key = principal_memo_key()
        async with policy_principal_scope(other):
            assert current_principal()[0].id == other and principal_memo_key() != first_key
        assert current_principal() is outer
    assert current_principal() is None
    async with policy_principal_scope(None) as nobody:
        assert nobody is None and principal_memo_key() is None
    set_policy_runtime(PolicyRuntime(mode=MODE_OFF))
    async with policy_principal_scope(member) as off:
        assert off is None, "the engine is off: nothing to load"




@pytest.mark.asyncio
async def test_model_admission_decides_for_the_principal_it_was_built_for(client, db):
    member, other = await _member(db, "ops"), await make_user(db, admin=False)
    workspace = await _workspace(db)
    use_custom_policies(ROLE_POLICY.format(role="ops", action="call_model"), mode="enforce")
    classification = WorkspaceDataClassification("internal", "project_config", "")

    def admission():
        return build_project_model_admission(project_id=workspace, project_config={"model_policy": {
            "allowed_aliases": ["octryx-sonnet"]}}, source="test", data_classification=classification)

    async with policy_principal_scope(member):
        mine = admission()
    async with policy_principal_scope(other):
        theirs = admission()
    unbound = admission()
    assert mine.decide("octryx-sonnet").reason == "cedar_policy_denied"
    assert mine.decide("octryx-sonnet").reason == "cedar_policy_denied", "a later re-check keeps the principal"
    assert theirs.decide("octryx-sonnet").allowed is True
    assert unbound.decide("octryx-sonnet").allowed is True, "outside a request: User unknown"


@pytest.mark.asyncio
async def test_tool_admission_listing_and_calls_decide_per_principal(client, db):
    member, other = await _member(db, "ops"), await make_user(db, admin=False)
    use_custom_policies(ROLE_POLICY.format(role="ops", action="call_tool"), mode="enforce")
    config = {"classification_tool_policy": {"level": "internal", "workspace_id": "ws", "connectors": {}}}
    async with policy_principal_scope(member):
        listed = classification_tool_decision("web_search", config)
        called = classification_tool_decision("web_search", config, {"query": "x"})
    async with policy_principal_scope(other):
        other_listed = classification_tool_decision("web_search", config)
    assert listed.reason == REASON_CEDAR_POLICY_DENIED and listed.policy_ids == ("ops-no-call_tool",)
    assert called.reason == REASON_CEDAR_POLICY_DENIED
    assert other_listed.allowed is True, "the memoised listing decision is per principal"
    assert classification_tool_decision("web_search", config).allowed is True
    await grant_role(db, other, "ops")
    clear_principal_cache()
    async with policy_principal_scope(other):
        assert classification_tool_decision("web_search", config).allowed is False, "new roles, new memo entry"


@pytest.mark.asyncio
async def test_the_seat_check_decides_for_the_user_and_the_seat_session(client, db):
    member, other = await _member(db, "ops"), await make_user(db, admin=False)
    workspace = await _workspace(db, agent_gateway_policy={"seat_mode": "allowed"})
    use_custom_policies(ROLE_POLICY.format(role="ops", action="use_seat"), mode="enforce")
    mine = await load_seat_principal(member, session_id="launch:abc", client="claude_code")
    assert mine[0].label() == "AgentSession::launch:abc"
    assert mine[1][1]["attrs"] == {"profile": "seat", "client": "claude_code", "sensitive": []}
    assert (await workspace_seat_decision(db, workspace, principal=mine)).reason == "cedar_policy_denied"
    theirs = await load_seat_principal(other, session_id="launch:def", client="claude_code")
    assert (await workspace_seat_decision(db, workspace, principal=theirs)).allowed is True
    assert (await workspace_seat_decision(db, workspace)).allowed is True, "the Workspace view has no user"
    use_custom_policies(SEAT_SESSION_POLICY, mode="enforce")
    assert (await workspace_seat_decision(db, workspace, principal=theirs)).reason == "cedar_policy_denied"


@pytest.mark.asyncio
async def test_remote_models_use_the_bound_principal(client, db):
    member = await _member(db, "ops")
    classification = WorkspaceDataClassification("internal", "project_config", "")
    async with policy_principal_scope(member):
        bound = remote_query(project_id="ws", classification=classification, data_policy_class="internal",
                             model_kind="reranker", rules=None)
    unbound = remote_query(project_id="ws", classification=classification, data_policy_class="internal",
                           model_kind="reranker", rules=None)
    assert bound.principal.label() == f"User::{member}"
    assert unbound.principal.label() == "User::unknown"


@pytest.mark.asyncio
async def test_the_bench_asks_for_the_user_at_every_point(client, db):
    admin = await make_user(db, admin=True)
    member = await _member(db, "ops")
    workspace = await _workspace(db)
    use_custom_policies(ROLE_POLICY.format(role="ops", action="call_tool"), mode="shadow")
    body = {"workspace_id": workspace, "user_id": member, "action": "call_tool", "resource": {"tool": "web_search"},
            "policies": ROLE_POLICY.format(role="ops", action="call_tool")}
    answer = (await client.post(f"{BASE}/test-bench", json=body, headers=bearer(admin))).json()
    assert answer["decision"] == "deny" and answer["principal"] == f"User::{member}" and answer["notes"] == []
    nobody = (await client.post(f"{BASE}/test-bench", json={**body, "user_id": None}, headers=bearer(admin))).json()
    assert nobody["decision"] == "allow" and nobody["principal"] == "User::unknown"
