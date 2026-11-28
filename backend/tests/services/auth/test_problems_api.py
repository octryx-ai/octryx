"""Problems API (E5): response shape, scoping per role, filters, and acknowledge until it occurs again."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import ConnectorHealth, LLMProvider, Project, StoredSecret, User, UserProject
from app.time_utils import utc_now
from tests.policy_engine_support import bearer

ADMIN_ROUTE = "/api/v1/admin/problems"
PROBLEM_FIELDS = {"key", "kind", "severity", "title", "since", "last_seen", "count", "workspace", "object", "fix"}


def uid() -> str:
    return str(uuid.uuid4())


async def _user(db, label: str, memberships: dict[str, str]) -> User:
    user = User(id=uid(), username=f"{label}-{uid()[:8]}", email=f"{uid()}@example.test", password_hash="!")
    db.add(user)
    await db.flush()
    for project_id, role in memberships.items():
        db.add(UserProject(user_id=user.id, project_id=project_id, role=role))
    await db.flush()
    return user


async def _world(db) -> dict:
    now = utc_now()
    alpha = Project(id=uid(), name="Alpha Desk", is_active=True, config={})
    beta = Project(id=uid(), name="Beta Desk", is_active=True, config={})
    db.add_all([alpha, beta])
    await db.flush()
    db.add_all([
        ConnectorHealth(connector_name="jira", project_id=alpha.id, status="error", last_checked=now),
        ConnectorHealth(connector_name="jira", project_id=beta.id, status="error", last_checked=now),
    ])
    provider = LLMProvider(name="bedrock", driver="bedrock_api", display_name="Bedrock", is_active=True, is_global=True,
                           health_status="unavailable", last_health_check_at=now)
    secret = StoredSecret(id=uid(), name="Jira token", secret_type="api_key", project_id=alpha.id, tool_name="jira",
                          expires_at=now + timedelta(days=3))
    db.add_all([provider, secret])
    await db.flush()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    return {
        "alpha": alpha, "beta": beta, "provider": provider, "secret": secret, "admin": admin,
        "ws_admin": await _user(db, "wsadmin", {alpha.id: "admin"}),
        "member": await _user(db, "member", {alpha.id: "member"}),
        "outsider": await _user(db, "outsider", {}),
    }


def _ours(body: dict, world: dict) -> list[dict]:
    ids = {world["alpha"].id, world["beta"].id}
    return [item for item in body["problems"]
            if (item["workspace"] or {}).get("id") in ids or item["object"]["id"] == world["provider"].id]


@pytest.mark.asyncio
async def test_platform_admin_sees_everything_with_the_exact_shape(client, db):
    world = await _world(db)

    body = (await client.get(ADMIN_ROUTE, headers=bearer(world["admin"].id))).json()

    ours = _ours(body, world)
    assert {(item["kind"], (item["workspace"] or {}).get("name")) for item in ours} == {
        ("connection", "Alpha Desk"), ("connection", "Beta Desk"), ("connection", None), ("token", "Alpha Desk")}
    for item in ours:
        assert set(item) == PROBLEM_FIELDS and item["since"].endswith("+00:00") and item["fix"]["href"]
        assert set(item["object"]) == {"type", "id", "name"} and set(item["fix"]) == {"label", "href"}
    provider = next(item for item in ours if item["object"]["type"] == "provider")
    assert provider["workspace"] is None and provider["severity"] == "problem"
    assert set(body["counts"]) == {"problem", "attention", "by_kind"}
    assert body["counts"]["problem"] >= 3 and body["counts"]["by_kind"]["token"] >= 1
    assert ours[0]["severity"] == "problem"

    filtered = (await client.get(ADMIN_ROUTE, params={"workspace_id": world["alpha"].id},
                                 headers=bearer(world["admin"].id))).json()
    assert {item["workspace"]["id"] for item in filtered["problems"]} == {world["alpha"].id}
    assert filtered["counts"] == {"problem": 1, "attention": 1, "by_kind": {"connection": 1, "token": 1}}


@pytest.mark.asyncio
async def test_problems_of_an_archived_workspace_are_not_listed(client, db):
    world = await _world(db)
    world["beta"].is_active = False
    await db.flush()

    body = (await client.get(ADMIN_ROUTE, headers=bearer(world["admin"].id))).json()

    assert world["beta"].id not in {(item["workspace"] or {}).get("id") for item in body["problems"]}
    assert world["alpha"].id in {(item["workspace"] or {}).get("id") for item in body["problems"]}
    filtered = (await client.get(ADMIN_ROUTE, params={"workspace_id": world["beta"].id},
                                 headers=bearer(world["admin"].id))).json()
    assert filtered["problems"] == [] and filtered["counts"]["problem"] == 0


@pytest.mark.asyncio
async def test_kind_and_severity_filter_the_list_not_the_counts(client, db):
    world = await _world(db)
    params = {"workspace_id": world["alpha"].id, "kind": "token", "severity": "attention"}

    body = (await client.get(ADMIN_ROUTE, params=params, headers=bearer(world["admin"].id))).json()

    assert [item["kind"] for item in body["problems"]] == ["token"]
    assert body["counts"]["by_kind"] == {"connection": 1, "token": 1}
    refused = await client.get(ADMIN_ROUTE, params={"kind": "weather"}, headers=bearer(world["admin"].id))
    assert refused.status_code == 422 and refused.json()["detail"]["field"] == "kind"


@pytest.mark.asyncio
async def test_workspace_admin_sees_only_administered_workspaces(client, db):
    world = await _world(db)
    headers = bearer(world["ws_admin"].id)

    body = (await client.get(ADMIN_ROUTE, headers=headers)).json()

    assert {(item["workspace"] or {}).get("id") for item in body["problems"]} == {world["alpha"].id}
    other = await client.get(ADMIN_ROUTE, params={"workspace_id": world["beta"].id}, headers=headers)
    assert other.status_code == 200 and other.json()["problems"] == []


@pytest.mark.asyncio
async def test_members_read_their_workspace_and_outsiders_are_refused(client, db):
    world = await _world(db)
    alpha_route = f"/api/v1/workspaces/{world['alpha'].id}/problems"

    member = (await client.get(alpha_route, headers=bearer(world["member"].id))).json()
    assert {item["kind"] for item in member["problems"]} == {"connection", "token"}
    assert all(item["workspace"]["id"] == world["alpha"].id for item in member["problems"])
    only_tokens = (await client.get(alpha_route, params={"kind": "token"}, headers=bearer(world["member"].id))).json()
    assert [item["kind"] for item in only_tokens["problems"]] == ["token"]

    assert (await client.get(ADMIN_ROUTE, headers=bearer(world["member"].id))).status_code == 403
    beta = await client.get(f"/api/v1/workspaces/{world['beta'].id}/problems", headers=bearer(world["member"].id))
    assert beta.status_code == 404 and beta.json()["detail"]["code"] == "workspace_not_found"
    assert (await client.get(alpha_route, headers=bearer(world["outsider"].id))).status_code == 404
    assert (await client.get(ADMIN_ROUTE, headers=bearer(world["outsider"].id))).status_code == 403
    assert (await client.get(ADMIN_ROUTE)).status_code == 401


@pytest.mark.asyncio
async def test_acknowledge_hides_until_the_problem_occurs_again(client, db):
    world = await _world(db)
    headers = bearer(world["ws_admin"].id)
    key = f"token:{world['secret'].id}:expires_soon"

    def keys(body: dict) -> set[str]:
        return {item["key"] for item in body["problems"]}

    assert key in keys((await client.get(ADMIN_ROUTE, headers=headers)).json())
    acked = await client.post(f"{ADMIN_ROUTE}/{key}/acknowledge", headers=headers)
    assert acked.status_code == 200 and acked.json() == {"key": key, "acknowledged": True}

    hidden = (await client.get(ADMIN_ROUTE, headers=headers)).json()
    assert key not in keys(hidden) and "token" not in hidden["counts"]["by_kind"]
    assert key in keys((await client.get(ADMIN_ROUTE, headers=bearer(world["admin"].id))).json())

    world["secret"].expires_at = utc_now() + timedelta(days=5)
    await db.flush()
    assert key in keys((await client.get(ADMIN_ROUTE, headers=headers)).json())

    missing = await client.post(f"{ADMIN_ROUTE}/token:nope:expired/acknowledge", headers=headers)
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "problem_not_found"
    beta_key = f"connection:jira@{world['beta'].id}:check_failed"
    assert (await client.post(f"{ADMIN_ROUTE}/{beta_key}/acknowledge", headers=headers)).status_code == 404
    assert (await client.post(f"{ADMIN_ROUTE}/{key}/acknowledge", headers=bearer(world["member"].id))).status_code \
        == 403
