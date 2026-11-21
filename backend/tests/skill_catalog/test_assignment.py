"""Per-Workspace assignment by skill and by whole category, surfaces, readiness."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project
from tests.policy_engine_support import bearer, make_user
from tests.skill_catalog.fake_git import MARKET_LATER, OFFICIAL
from tests.skill_catalog.support import BASE, category, force_publish, published_skill

# Two published chat-only skills as a fixture.
pytestmark = pytest.mark.usefixtures("chat_skills")


async def _project(db) -> Project:
    return (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()


async def _get(client, admin, project_id):
    response = await client.get(f"{BASE}/workspaces/{project_id}/skills", headers=bearer(admin))
    assert response.status_code == 200, response.text
    return response.json()


async def _put(client, admin, project_id, digest, **body):
    payload = {"mode": "selected_only", "skill_ids": [], "category_keys": [], "blocked_skill_ids": [],
               "surfaces": {"platform_chat": True, "octryx_claude": True}, **body}
    headers = {**bearer(admin), "If-Match": digest} if digest else bearer(admin)
    return await client.put(f"{BASE}/workspaces/{project_id}/skills", json=payload, headers=headers)


def _names(view, surface):
    return {row["name"]: row for row in view["effective"][surface]}


@pytest.mark.asyncio
async def test_a_whole_category_includes_its_children_and_skills_published_later(client, db):
    admin = await make_user(db, admin=True)
    project_id = (await _project(db)).id
    terraform, helm, packer = (await category(db, "iac.terraform")).id, (await category(db, "kubernetes.helm")).id, \
        (await category(db, "iac.packer")).id
    style, _ = await published_skill(db, terraform, "style-guide", approver_id=admin)
    chart, _ = await published_skill(db, helm, "chart-scaffold", approver_id=admin)
    style_id, chart_id = style.id, chart.id
    await db.commit()

    view = await _get(client, admin, project_id)
    assert view["policy"]["mode"] == "all_active"
    assert {"style-guide", "chart-scaffold", "alert-diagnosis"} <= set(_names(view, "platform_chat"))
    assert "alert-diagnosis" not in _names(view, "octryx_claude")  # the fixture skills are chat-only
    assert _names(view, "platform_chat")["style-guide"]["assigned_by"] == "all"

    saved = await _put(client, admin, project_id, view["digest"], category_keys=["iac"], skill_ids=[chart_id])
    assert saved.status_code == 200, saved.text
    after = saved.json()
    chat = _names(after, "platform_chat")
    assert set(chat) == {"style-guide", "chart-scaffold"}
    assert chat["style-guide"]["assigned_by"] == "category:iac" and chat["chart-scaffold"]["assigned_by"] == "skill"
    assert chat["style-guide"]["category_path"] == ["Infrastructure as code", "Terraform"]
    # A gzip-compressed answer carries the weak ETag W/"digest"; If-Match accepts both forms.
    assert saved.headers["ETag"].removeprefix("W/").strip('"') == after["digest"] != view["digest"]

    await published_skill(db, packer, "image-builder", approver_id=admin)
    await db.commit()
    later = await _get(client, admin, project_id)
    assert "image-builder" in _names(later, "octryx_claude")

    blocked = await _put(client, admin, project_id, later["digest"], category_keys=["iac"], skill_ids=[chart_id],
                         blocked_skill_ids=[style_id], surfaces={"platform_chat": True, "octryx_claude": False})
    view = blocked.json()
    assert "style-guide" not in _names(view, "platform_chat") and view["effective"]["octryx_claude"] == []
    assert {"name": "style-guide", "reason": "blocked_by_workspace"}.items() <= next(
        row for row in view["withheld"]["platform_chat"] if row["name"] == "style-guide").items()
    assert {row["reason"] for row in view["withheld"]["octryx_claude"]} == {"surface_off_for_workspace"}

    none = await _put(client, admin, project_id, view["digest"], mode="none", category_keys=["iac"],
                      skill_ids=[chart_id])
    assert none.json()["effective"]["platform_chat"] == []


@pytest.mark.asyncio
async def test_saves_need_if_match_and_known_skills_and_categories(client, db):
    admin = await make_user(db, admin=True)
    project_id = (await _project(db)).id
    view = await _get(client, admin, project_id)
    assert (await _put(client, admin, project_id, None)).status_code == 428
    stale = await _put(client, admin, project_id, "sha256:" + "0" * 64)
    assert stale.status_code == 409 and stale.json()["detail"]["digest"] == view["digest"]
    for body, code in [({"mode": "some"}, "skill_assignment_mode_invalid"),
                       ({"skill_ids": ["nope"]}, "skill_assignment_unknown_skill"),
                       ({"category_keys": ["nope"]}, "skill_assignment_unknown_category")]:
        response = await _put(client, admin, project_id, view["digest"], **body)
        assert response.status_code == 422 and response.json()["detail"]["code"] == code, body
    first = await _put(client, admin, project_id, view["digest"], category_keys=["iac"])
    assert first.status_code == 200
    second = await _put(client, admin, project_id, view["digest"], category_keys=["kubernetes"])
    assert second.json()["detail"]["code"] == "skill_assignment_conflict"
    member = await make_user(db, admin=False)
    assert (await client.get(f"{BASE}/workspaces/{project_id}/skills", headers=bearer(member))).status_code == 403
    legacy = await client.get(f"/admin/chat/api/panel/projects/{project_id}/skills", headers=bearer(admin))
    assert legacy.status_code == 200 and legacy.json()["policy"]["assignment_mode"] == "selected_only"


@pytest.mark.asyncio
async def test_readiness_names_the_refusing_rule_per_surface(client, db):
    admin = await make_user(db, admin=True)
    project = await _project(db)
    project_id = project.id
    config = dict(project.config or {})
    config["agent_gateway_policy"] = {"tool_rules": [
        {"id": "no-terraform-apply", "kind": "command_prefix_denied", "prefix": ["terraform", "apply"]}],
        "client_permissions": {"deny": ["Bash(rm *)"]}}
    config["mcp_policy"] = {"enabled_servers": []}
    project.config = config
    terraform = (await category(db, "iac.terraform")).id
    await published_skill(db, terraform, "plan-and-apply", approver_id=admin, extension={"tools": {
        "platform_chat": {"required": ["no_such_tool"]},
        "octryx_claude": {"required": ["Bash(terraform validate *)", "Bash(terraform apply *)", "Bash(rm *)"]}}})
    await db.commit()
    view = await _get(client, admin, project_id)
    chat = _names(view, "platform_chat")["plan-and-apply"]["readiness"]
    assert chat["state"] == "restricted" and chat["refusals"][0]["tool"] == "no_such_tool"
    claude = _names(view, "octryx_claude")["plan-and-apply"]["readiness"]
    assert claude["state"] == "restricted"
    assert [(item["tool"], item["rule"]) for item in claude["refusals"]] == [
        ("Bash(terraform apply *)", "no-terraform-apply"), ("Bash(rm *)", "Bash(rm *)")]
    assert _names(view, "platform_chat")["alert-diagnosis"]["readiness"]["state"] == "ready"


@pytest.mark.asyncio
async def test_an_mcp_server_entry_needs_the_workspace_mcp_policy(client, db, fake_git):
    admin = await make_user(db, admin=True)
    project = await _project(db)
    project_id = project.id
    terraform = (await category(db, "iac.terraform")).id
    files_skill = await client.post(f"{BASE}/import/git", headers=bearer(admin), json={
        "url": OFFICIAL, "ref": "main", "marketplace_plugin": "terraform", "commit": MARKET_LATER,
        "items": [{"kind": "mcp_server", "path": "external_plugins/terraform", "name": "terraform",
                   "category_id": terraform}]})
    await force_publish(db, files_skill.json()["imported"][0]["skill_id"], approver_id=admin)
    view = await _get(client, admin, project_id)
    assert "terraform" not in _names(view, "platform_chat")  # never on platform chat
    entry = _names(view, "octryx_claude")["terraform"]["readiness"]
    assert entry["state"] == "needs_mcp_policy" and entry["refusals"][0]["policy"] == "mcp_policy"
    project = await db.get(Project, project_id)
    project.config = {**(project.config or {}), "mcp_policy": {"enabled_servers": ["terraform"]}}
    await db.commit()
    assert _names(await _get(client, admin, project_id), "octryx_claude")["terraform"]["readiness"]["state"] == "ready"


@pytest.mark.asyncio
async def test_a_concurrent_save_between_check_and_claim_is_refused(client, db, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import update

    from app.models import WorkspacePolicy
    from app.services.skill_catalog import assignment

    admin = await make_user(db, admin=True)
    project_id = (await _project(db)).id
    view = await _get(client, admin, project_id)
    original = assignment.workspace_policy

    async def racing(session, workspace_id):
        found = await original(session, workspace_id)
        # Another admin's save lands right after the check: the row changes behind the loaded object.
        current = (await session.execute(select(WorkspacePolicy.updated_at).where(
            WorkspacePolicy.workspace_id == workspace_id))).scalar_one()
        await session.execute(update(WorkspacePolicy).where(WorkspacePolicy.workspace_id == workspace_id)
                              .values(updated_at=current + timedelta(seconds=1))
                              .execution_options(synchronize_session=False))
        return found

    monkeypatch.setattr(assignment, "workspace_policy", racing)
    response = await _put(client, admin, project_id, view["digest"], category_keys=["iac"])
    assert response.status_code == 409 and response.json()["detail"]["code"] == "skill_assignment_conflict"
