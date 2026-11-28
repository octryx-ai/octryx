"""Contract: secure-work MCP tools honour the OAuth grant's project binding, refusing before any business
service runs, with the denial audited."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import AuditLog, WorkChangePlan, WorkItem
from app.models.security.oauth_provider import OAuthGrant
from app.services import mcp_secure_work_tools
from app.services.mcp_knowledge_protocol import KnowledgeMcpTokenVerifier
from app.services.mcp_work_access import INVALID_GRANT_DETAIL, resolve_work_grant_binding
from app.services.oauth_provider import mint_access_token
from tests.mcp_native_support import mcp_call, native_token
from tests.support.mcp_work_grant_scope_support import WORK_SCOPES, _error_text, _snapshot, spies, world  # noqa: F401

pytestmark = pytest.mark.asyncio


def _calls_on(
    item: WorkItem, plan: WorkChangePlan | None, session_ref: str, workflow_id: str
) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    for ref in (item.id, item.source_key):
        calls += [
            ("work_item_find", {"work_item": ref}),
            ("work_item_context", {"work_item": ref}),
            ("work_item_note", {"work_item": ref, "note": "probe"}),
            ("work_item_link_session", {"work_item": ref, "client_session_id": session_ref}),
            ("coding_observability", {"work_item": ref}),
            ("change_units_plan", {"work_item": ref, "units": []}),
            ("change_plan_generate", {"work_item": ref}),
            ("work_item_redeclare", {"work_item": ref, "reason": "probe"}),
            ("coding_agent_start", {"work_item": ref}),
            ("work_item_transition", {"work_item": ref, "to_state": "development", "workflow_id": workflow_id}),
        ]
    if plan is not None:
        calls.append(("change_plan_decide", {"change_plan_id": plan.id, "action": "reject", "reason": "probe"}))
    return calls


async def test_raw_grant_binding_is_validated_without_the_lossy_shared_collapse(db, world):  # noqa: F811
    user = world.member

    async def binding(project_ids, **overrides):
        grant = OAuthGrant(user_id=user.id, client_id="oec_binding_test", scopes=WORK_SCOPES, project_ids=project_ids)
        for key, value in overrides.items():
            setattr(grant, key, value)
        db.add(grant)
        await db.flush()
        return await resolve_work_grant_binding(db, grant_id=grant.id, user_id=user.id)

    assert await binding(None) is None
    assert await binding([]) == frozenset()
    assert await binding([world.a, f" {world.b} "]) == {world.a, world.b}
    for malformed in (world.a, {"id": world.a}, 7, [1], [""], ["   "], [None], [world.a, None]):
        with pytest.raises(HTTPException) as exc:
            await binding(malformed)
        assert (exc.value.status_code, exc.value.detail) == (401, INVALID_GRANT_DETAIL), malformed
    from app.time_utils import utc_now

    with pytest.raises(HTTPException) as exc:
        await binding([world.a], revoked_at=utc_now())
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        await binding([world.a], user_id=world.plain.id)
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        await resolve_work_grant_binding(db, grant_id=str(uuid.uuid4()), user_id=user.id)
    assert exc.value.status_code == 401


async def test_bound_grant_denies_other_workspace_before_any_service(world, spies):  # noqa: F811
    db, member = world.db, world.member
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    item_b, plan_b = world.items["b"], world.plans["b"]
    before = await _snapshot(db)
    audits_before = (
        await db.execute(select(func.count(AuditLog.id)).where(AuditLog.resource_type == "mcp_knowledge"))
    ).scalar_one()

    calls = _calls_on(item_b, plan_b, world.sessions["own_b"].metadata_["client_session_id"], world.workflows["b"])
    calls += [
        ("work_item_list", {"project_id": world.b}),
        ("work_item_create", {"project_id": world.b, "title": "probe"}),
    ]
    for tool, arguments in calls:
        text = _error_text(await mcp_call(token, tool, arguments))
        assert any(marker in text for marker in ("not found", "not allowed")), (tool, text)

    assert spies == []
    assert await _snapshot(db) == before
    denials = (
        (
            await db.execute(
                select(AuditLog.details).where(AuditLog.resource_type == "mcp_knowledge").order_by(AuditLog.created_at)
            )
        )
        .scalars()
        .all()[audits_before:]
    )
    assert len(denials) == len(calls)
    assert {row["status"] for row in denials} == {"error"} and {row["api_key_project_id"] for row in denials} == {
        world.a
    }


async def test_bound_grant_allows_its_workspace(world, monkeypatch):  # noqa: F811
    db, member = world.db, world.member
    item_a, plan_a = world.items["a"], world.plans["a"]
    entered: list[tuple[str, str]] = []

    def _fake(name: str, result):
        async def _service(_db, **kwargs):
            entered.append((name, kwargs.get("work_item_id") or kwargs.get("item").id))
            return result

        return _service

    monkeypatch.setattr(mcp_secure_work_tools, "plan_work_item_change_units", _fake("units", {"items": []}))
    monkeypatch.setattr(
        mcp_secure_work_tools,
        "generate_change_plan",
        _fake("generate", {"id": "p", "version": 2, "status": "ready_for_review"}),
    )
    monkeypatch.setattr(
        mcp_secure_work_tools, "start_work_item_coding_agent_execution", _fake("coding", {"status": "started"})
    )
    monkeypatch.setattr(
        mcp_secure_work_tools,
        "transition_work_item",
        _fake("transition", {"work_state": "development", "preview": {"jira_sync_preview": {}}}),
    )
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])

    found = await mcp_call(token, "work_item_find", {"work_item": item_a.source_key})
    assert found["id"] == item_a.id
    context = await mcp_call(token, "work_item_context", {"work_item": item_a.id})
    assert context["latest_plan"]["id"] == plan_a.id
    assert (await mcp_call(token, "work_item_note", {"work_item": item_a.id, "note": "progress"}))["notes"] == 1
    linked = await mcp_call(
        token,
        "work_item_link_session",
        {"work_item": item_a.id, "client_session_id": world.sessions["own_a"].metadata_["client_session_id"]},
    )
    assert linked["platform_session_found"] is True
    for tool in ("change_units_plan", "change_plan_generate", "coding_agent_start", "work_item_transition"):
        arguments = {
            "work_item": item_a.source_key,
            "to_state": "development",
            "workflow_id": world.workflows["a"],
            "units": [],
        }
        result = await mcp_call(token, tool, arguments)
        assert not result.get("isError"), (tool, result)
    assert {name for name, _ in entered} == {"units", "generate", "coding", "transition"}
    assert {item_id for _, item_id in entered} == {item_a.id}
    decided = await mcp_call(
        token, "change_plan_decide", {"change_plan_id": plan_a.id, "action": "request_clarification", "reason": "x"}
    )
    assert decided["status"] == "needs_clarification"

    listed = await mcp_call(token, "work_item_list", {"limit": 100})
    keys = {row["source_key"] for row in listed["items"]}
    assert item_a.source_key in keys and world.items["b"].source_key not in keys
    created = await mcp_call(token, "work_item_create", {"project_id": world.a, "title": "Bound create"})
    assert created["project_id"] == world.a

    # Same key in A and B: the bound grant resolves the A item, never B.
    same = await mcp_call(token, "work_item_find", {"work_item": world.items["same_a"].source_key})
    assert same["id"] == world.items["same_a"].id
    # Same key twice inside the scope: explicit conflict, no arbitrary pick and no 500.
    assert "ambiguous" in _error_text(
        await mcp_call(token, "work_item_find", {"work_item": world.items["dup_a1"].source_key})
    )


async def test_admin_crosses_workspaces_only_inside_a_bound_grant(world, spies):  # noqa: F811
    db, admin = world.db, world.admin
    bound = await native_token(db, user_id=admin.id, scopes=WORK_SCOPES, project_ids=[world.a])
    assert (await mcp_call(bound, "work_item_find", {"work_item": world.items["a"].id}))["id"] == world.items["a"].id
    for name in ("b", "null"):
        assert "not found" in _error_text(await mcp_call(bound, "work_item_find", {"work_item": world.items[name].id}))
    # List/create stay membership-only: the admin is no member of A.
    assert (await mcp_call(bound, "work_item_list", {}))["items"] == []
    assert "not allowed" in _error_text(
        await mcp_call(bound, "work_item_create", {"project_id": world.a, "title": "x"})
    )

    unrestricted = await native_token(db, user_id=admin.id, scopes=WORK_SCOPES, project_ids=None)
    for name in ("b", "null"):
        found = await mcp_call(unrestricted, "work_item_find", {"work_item": world.items[name].id})
        assert found["id"] == world.items[name].id
    assert spies == []


async def test_empty_and_malformed_bindings_fail_closed_for_work_only(world, spies):  # noqa: F811
    db, member = world.db, world.member
    empty = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[])
    assert "not found" in _error_text(await mcp_call(empty, "work_item_find", {"work_item": world.items["a"].id}))
    assert (await mcp_call(empty, "work_item_list", {}))["items"] == []
    assert "not allowed" in _error_text(
        await mcp_call(empty, "work_item_create", {"project_id": world.a, "title": "x"})
    )

    malformed = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=world.a)
    assert INVALID_GRANT_DETAIL in _error_text(
        await mcp_call(malformed, "work_item_find", {"work_item": world.items["a"].id})
    )
    # Shared OAuth consumers keep their existing semantics (follow-up, not accepted): the knowledge
    # project list still treats the malformed binding as unrestricted.
    neighbor = await mcp_call(malformed, "knowledge_projects", {})
    assert not neighbor.get("isError") and {world.a, world.b} <= {p["id"] for p in neighbor["projects"]}
    assert spies == []


async def test_revoked_and_expired_grants_never_reach_the_dispatcher(world):  # noqa: F811
    db, member = world.db, world.member
    verifier = KnowledgeMcpTokenVerifier()
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    assert await verifier.verify_token(token) is not None
    grant = (await db.execute(select(OAuthGrant).order_by(OAuthGrant.created_at.desc()).limit(1))).scalar_one()
    expired, _ = mint_access_token(
        user_id=member.id,
        client_id="oec_parity_test",
        grant_id=grant.id,
        scopes=WORK_SCOPES,
        resource=None,
        expires_minutes=-5,
    )
    assert await verifier.verify_token(expired) is None
    from app.time_utils import utc_now

    grant.revoked_at = utc_now()
    await db.commit()
    assert await verifier.verify_token(token) is None


async def test_operator_role_parity_for_units_coding_and_transition(world, spies):  # noqa: F811
    db, plain = world.db, world.plain
    token = await native_token(db, user_id=plain.id, scopes=WORK_SCOPES, project_ids=None)
    item_a = world.items["a"]
    before = await _snapshot(db)
    for tool in ("change_units_plan", "coding_agent_start", "work_item_transition"):
        arguments = {
            "work_item": item_a.id,
            "to_state": "development",
            "workflow_id": world.workflows["a"],
            "units": [],
        }
        assert "operation role" in _error_text(await mcp_call(token, tool, arguments)), tool
    assert spies == []
    assert await _snapshot(db) == before


async def test_membership_reads_stay_open_to_non_operator_members(world, monkeypatch):  # noqa: F811
    db, plain = world.db, world.plain
    token = await native_token(db, user_id=plain.id, scopes=WORK_SCOPES, project_ids=None)
    item_a = world.items["a"]
    assert (await mcp_call(token, "work_item_find", {"work_item": item_a.id}))["id"] == item_a.id
    assert (await mcp_call(token, "work_item_note", {"work_item": item_a.id, "note": "handover"}))["notes"] == 1
