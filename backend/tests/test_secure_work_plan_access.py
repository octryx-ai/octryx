"""Contract: Change Plans are read and decided only inside the owning Work Item's workspace.

- HTTP plan routes keep the platform operator role check and add workspace scope;
- an admin is cross-workspace; a member or group member of the item's project is allowed;
  anyone else gets 403; an item without a project is admin-only; unknown ids are 404;
- the MCP plan mutations (generate, decide, redeclare) also require the platform work-operator role,
  checked before any lookup, because the ``work:manage`` OAuth scope is self-consented;
- the MCP plan navigation reads (find, handover context) and the mutations answer an out-of-scope
  id, key or plan id exactly like a missing one (404), so a foreign item is never disclosed;
- a denial leaves no plan, decision or audit row behind and never reaches the plan service.
"""

from __future__ import annotations

import uuid

import pytest

from app.api.routes import secure_work_planning as secure_work_routes
from app.models import User, WorkChangePlan, WorkItem
from app.services.auth.tokens import create_access_token
from app.services.secure_work.access import work_scope_project_ids
from tests.secure_work_plan_access_support import _side_effects, world  # noqa: F401

pytestmark = pytest.mark.asyncio


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _plan_requests(item: WorkItem, plan: WorkChangePlan) -> list[tuple[str, str, dict | None]]:
    base = "/api/v1/secure-work"
    return [
        ("GET", f"{base}/work-items/{item.id}/change-plans", None),
        ("POST", f"{base}/work-items/{item.id}/change-plans/generate", {}),
        ("POST", f"{base}/work-items/{item.id}/work-plans/generate", {}),
        ("GET", f"{base}/change-plans/{plan.id}/decisions", None),
        ("POST", f"{base}/change-plans/{plan.id}/decision", {"action": "reject", "reason": "denied probe"}),
        ("POST", f"{base}/work-items/{item.id}/redeclare", {"reason": "denied probe"}),
    ]


async def _send(client, method: str, url: str, body: dict | None, headers: dict[str, str]):
    if method == "GET":
        return await client.get(url, headers=headers)
    return await client.post(url, headers=headers, json=body)


async def test_work_scope_project_ids_follows_admin_membership_and_groups(db, world):  # noqa: F811
    assert await work_scope_project_ids(db, world["admin"]) is None
    assert await work_scope_project_ids(db, world["member"]) == {world["own_project"].id}
    assert await work_scope_project_ids(db, world["group_member"]) == {world["own_project"].id}
    assert await work_scope_project_ids(db, world["outsider"]) == set()


async def test_http_plan_routes_deny_outside_scope_before_any_side_effect(client, db, world, monkeypatch):  # noqa: F811
    calls: list[str] = []

    async def _provider_probe(*_args, **_kwargs):
        calls.append("generate_llm_work_plan")
        raise AssertionError("the LLM plan service must not run for a denied request")

    monkeypatch.setattr(secure_work_routes, "generate_llm_work_plan", _provider_probe)
    for label, user in (("outsider", world["outsider"]), ("member", world["member"])):
        for scope in ("foreign", "null") if label == "member" else ("own", "foreign", "null"):
            item, plan = world[scope]
            before = await _side_effects(db, item)
            # Another Workspace's item answers like a missing one (404); an item without a Workspace is admin-only.
            expected = 403 if scope == "null" else 404
            for method, url, body in _plan_requests(item, plan):
                response = await _send(client, method, url, body, _auth(user))
                assert response.status_code == expected, (label, scope, url, response.text)
            assert await _side_effects(db, item) == before
    assert calls == []


async def test_http_plan_routes_allow_member_group_and_admin(client, db, world, monkeypatch):  # noqa: F811
    async def _llm_plan(_db, *, work_item_id, **_kwargs):
        return {"id": "llm-plan", "work_item_id": work_item_id}

    monkeypatch.setattr(secure_work_routes, "generate_llm_work_plan", _llm_plan)
    item, plan = world["own"]
    base = "/api/v1/secure-work"
    for user in (world["member"], world["group_member"]):
        listed = await client.get(f"{base}/work-items/{item.id}/change-plans", headers=_auth(user))
        assert listed.status_code == 200 and [row["id"] for row in listed.json()["items"]] == [plan.id]
        decisions = await client.get(f"{base}/change-plans/{plan.id}/decisions", headers=_auth(user))
        assert decisions.status_code == 200 and decisions.json() == {"items": []}
    llm = await client.post(f"{base}/work-items/{item.id}/work-plans/generate", headers=_auth(world["member"]), json={})
    assert llm.status_code == 200 and llm.json()["work_item_id"] == item.id

    decided = await client.post(
        f"{base}/change-plans/{plan.id}/decision",
        headers=_auth(world["group_member"]),
        json={"action": "request_clarification", "reason": "Name the rollback owner."},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["plan"]["status"] == "needs_clarification"

    admin = _auth(world["admin"])
    for scope in ("foreign", "null"):
        other_item, other_plan = world[scope]
        listed = await client.get(f"{base}/work-items/{other_item.id}/change-plans", headers=admin)
        assert listed.status_code == 200 and [row["id"] for row in listed.json()["items"]] == [other_plan.id]
    redeclared = await client.post(
        f"{base}/work-items/{world['null'][0].id}/redeclare", headers=admin, json={"reason": "Declined PR."}
    )
    assert redeclared.status_code == 200 and redeclared.json()["superseded_plans"] == 1


async def test_http_plan_routes_keep_role_check_and_report_missing_ids(client, world):  # noqa: F811
    item, plan = world["own"]
    # A plain member of the item's Workspace reads its plans (a team leader shows the team its work);
    # every write still needs the Work role.
    for method, url, body in _plan_requests(item, plan):
        response = await _send(client, method, url, body, _auth(world["plain_member"]))
        if method == "GET":
            assert response.status_code == 200, (url, response.text)
            continue
        assert response.status_code == 403, (url, response.text)
        assert "operation role" in response.json()["detail"]

    base = "/api/v1/secure-work"
    member = _auth(world["member"])
    missing = str(uuid.uuid4())
    assert (await client.get(f"{base}/work-items/{missing}/change-plans", headers=member)).status_code == 404
    assert (await client.get(f"{base}/change-plans/{missing}/decisions", headers=member)).status_code == 404
    decision = await client.post(
        f"{base}/change-plans/{missing}/decision", headers=member, json={"action": "reject", "reason": "x"}
    )
    assert decision.status_code == 404
