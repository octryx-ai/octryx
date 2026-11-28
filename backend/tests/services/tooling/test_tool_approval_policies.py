"""Which tool calls need approval — platform default + per Workspace (inherit / add)."""

from __future__ import annotations

import uuid

import pytest

from app.models import Project
from app.services.tool_approval.policy import effective_policy, set_platform_default
from app.services.tool_approval.rules import tool_approval_requirement
from tests.policy_engine_support import bearer, make_user

ROUTE = "/api/v1/admin/tool-approvals"


@pytest.fixture(autouse=True)
def _default():
    set_platform_default({})
    yield
    set_platform_default({})


async def _workspace(db, **config) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True, config=config)
    db.add(project)
    await db.commit()
    return project


@pytest.mark.asyncio
async def test_the_platform_default_applies_to_every_workspace_and_a_workspace_can_only_add(client, db):
    admin = await make_user(db, admin=True)
    inheriting = await _workspace(db)
    adding = await _workspace(db)

    saved = await client.put(f"{ROUTE}/default", headers=bearer(admin),
                             json={"require_for_risks": ["admin"], "require_for_tools": ["send_email"], "exempt_tools": []})
    assert saved.status_code == 200, saved.text
    assert saved.json()["default"]["require_for_risks"] == ["admin"]
    assert tool_approval_requirement("send_email", inheriting.config).required is True
    assert tool_approval_requirement("search_knowledge", inheriting.config).required is False

    added = await client.put(f"{ROUTE}/workspaces/{adding.id}", headers=bearer(admin),
                             json={"mode": "add", "require_for_tools": ["create_jira_issue"], "exempt_tools": []})
    assert added.status_code == 200, added.text
    await db.refresh(adding)
    assert adding.config["approval_policy"] == {"mode": "add", "require_for_risks": [],
                                                "require_for_tools": ["create_jira_issue"], "exempt_tools": []}
    effective = effective_policy(adding.config)
    assert effective["require_for_tools"] == ["send_email", "create_jira_issue"], "the default stays"
    assert tool_approval_requirement("create_jira_issue", adding.config).required is True
    assert tool_approval_requirement("create_jira_issue", inheriting.config).required is False

    row = next(item for item in added.json()["workspaces"] if item["id"] == adding.id)
    assert row["mode"] == "add" and row["own"]["require_for_tools"] == ["create_jira_issue"]
    back = await client.put(f"{ROUTE}/workspaces/{adding.id}", headers=bearer(admin), json={"mode": "inherit"})
    assert back.status_code == 200
    await db.refresh(adding)
    assert adding.config["approval_policy"] == {"mode": "inherit"}


@pytest.mark.asyncio
async def test_a_workspace_policy_adds_to_the_platform_default(db):
    set_platform_default({"require_for_risks": ["admin"], "require_for_tools": [], "exempt_tools": []})
    added = {"approval_policy": {"mode": "add", "require_for_tools": ["merge_pull_request"]}}
    assert effective_policy(added) == {"require_for_risks": ["admin"], "require_for_tools": ["merge_pull_request"]}
    assert effective_policy({}) == {"require_for_risks": ["admin"]}


@pytest.mark.asyncio
async def test_invalid_policies_are_refused_and_the_page_is_for_admins(client, db):
    admin = await make_user(db, admin=True)
    member = await make_user(db, admin=False)
    project = await _workspace(db)
    for body, code in [({"require_for_risks": ["huge"]}, "tool_approval_risk_unknown"),
                       ({"require_for_tools": ["bad name!"]}, "tool_approval_tool_invalid")]:
        refused = await client.put(f"{ROUTE}/default", json=body, headers=bearer(admin))
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == code
    for body in ({"mode": "replace"}, {"require_for_tools": ["create_jira_issue"]}):
        mode = await client.put(f"{ROUTE}/workspaces/{project.id}", json=body, headers=bearer(admin))
        assert mode.status_code == 422 and mode.json()["detail"]["code"] == "tool_approval_mode_invalid"
    assert (await client.get(ROUTE, headers=bearer(member))).status_code == 403
    listing = (await client.get(ROUTE, headers=bearer(admin))).json()
    assert listing["risks"] == ["read", "write", "admin", "unknown"]
    assert any(tool["name"] == "web_search" for tool in listing["tools"])
    assert "servers" in listing["mcp"]
