"""Server side: the octryx-claude manifest, its blobs and usage from Claude Code."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import select

from app.models import Project, SkillUsageEvent, User
from app.models.security.oauth_provider import OAuthGrant
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.agent_gateway.identity import resolve_gateway_identity
from app.services.agent_gateway.sessions import get_or_create_gateway_session
from app.services.oauth_provider import mint_access_token
from app.services.skill_catalog.bundle import BundleFile
from app.services.skill_catalog.spec import DELIVERY_FRONTMATTER_KEYS, parse_skill_md
from tests.policy_engine_support import bearer
from tests.skill_catalog.fake_git import MARKET_LATER, OFFICIAL
from tests.skill_catalog.support import BASE, category, force_publish, published_skill

# Two published chat-only skills as a fixture.
pytestmark = pytest.mark.usefixtures("chat_skills")

GATEWAY = "/api/v1/agent-gateway"
STYLE = """---
name: style-guide
description: Write HCL in the house style.
allowed-tools: Bash(terraform apply *)
hooks:
  PreToolUse: []
model: some-model
metadata:
  lifecycle-status: active
---

# Style guide

Run `terraform fmt`.
"""


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _gateway(db, project_id: str) -> tuple[dict[str, str], str]:
    admin = await _admin(db)
    grant = OAuthGrant(user_id=admin.id, client_id=f"oec_gw_{uuid.uuid4().hex[:6]}", scopes=[SCOPE_MODEL_INVOKE])
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(user_id=admin.id, client_id=grant.client_id, grant_id=grant.id,
                                 scopes=[SCOPE_MODEL_INVOKE], resource=GATEWAY_AUDIENCE)
    headers = {"Authorization": f"Bearer {token}", "X-Octryx-Session": str(uuid.uuid4()),
               "X-Octryx-Workspace": project_id}
    identity = await resolve_gateway_identity(db, {key.lower(): value for key, value in headers.items()})
    session = await get_or_create_gateway_session(db, identity)
    await db.commit()
    return headers, session.id


async def _project_id(db) -> str:
    return (await db.execute(select(Project.id).where(Project.name == "acme-orders"))).scalar_one()


@pytest.mark.asyncio
async def test_the_manifest_delivers_allowlisted_frontmatter_and_withholds_scripts(client, db, auth_user):
    project_id = await _project_id(db)
    terraform = (await category(db, "iac.terraform")).id
    await published_skill(db, terraform, "style-guide", approver_id=auth_user.id, files=[
        BundleFile("SKILL.md", STYLE), BundleFile("references/naming.md", "# Naming\n"),
        BundleFile("scripts/fmt.sh", "#!/bin/sh\nterraform fmt\n", True), BundleFile("LICENSE", "MIT License\n")],
        extension={"safety_rules": ["Never run terraform apply"]}, licence_spdx="MIT")
    await db.commit()
    headers, _ = await _gateway(db, project_id)

    response = await client.get(f"{GATEWAY}/skills/manifest", headers=headers)
    assert response.status_code == 200, response.text
    manifest = response.json()
    names = {item["name"]: item for item in manifest["skills"]}
    assert "alert-diagnosis" not in names  # the fixture skills are chat-only
    style = names["style-guide"]
    assert [item["path"] for item in style["files"]] == ["LICENSE", "SKILL.md", "references/naming.md"]
    assert style["scripts_withheld"] == ["scripts/fmt.sh"] and manifest["plugin"] == "octryx"
    skill_md = next(item for item in style["files"] if item["path"] == "SKILL.md")

    blob = (await client.get(f"{GATEWAY}/skills/blobs/{skill_md['sha256']}", headers=headers)).json()
    assert hashlib.sha256(blob["content"].encode()).hexdigest() == skill_md["sha256"]
    parsed = parse_skill_md(blob["content"])
    assert set(parsed.frontmatter) <= set(DELIVERY_FRONTMATTER_KEYS)
    assert "allowed-tools" not in blob["content"] and "hooks" not in parsed.frontmatter
    metadata = parsed.frontmatter["metadata"]
    assert metadata["lifecycle-status"] == "active" and metadata["octryx-workspace"] == project_id
    assert metadata["octryx-category"] == "iac.terraform" and metadata["octryx-version"] == "1"
    assert parsed.body.rstrip().endswith("## Safety rules\n\n- Never run terraform apply")

    outside = await client.get(f"{GATEWAY}/skills/blobs/{'0' * 64}", headers=headers)
    assert outside.status_code == 404 and outside.headers["x-octryx-gateway-reason"] == \
        "skill_blob_not_in_manifest"
    assert (await client.get(f"{GATEWAY}/skills/blobs/not-a-sha", headers=headers)).status_code == 400
    anonymous = await client.get(f"{GATEWAY}/skills/manifest")
    assert anonymous.status_code in {401, 403} and anonymous.headers.get("x-octryx-gateway-state")


@pytest.mark.asyncio
async def test_an_allowed_mcp_entry_starts_by_digest_without_credential_passthrough(client, db, fake_git, auth_user):
    project_id = await _project_id(db)
    terraform = (await category(db, "iac.terraform")).id
    imported = await client.post(f"{BASE}/import/git", headers=bearer(auth_user.id), json={
        "url": OFFICIAL, "ref": "main", "marketplace_plugin": "terraform", "commit": MARKET_LATER,
        "items": [{"kind": "mcp_server", "path": "external_plugins/terraform", "name": "terraform",
                   "category_id": terraform}]})
    skill_id = imported.json()["imported"][0]["skill_id"]
    draft = (await client.get(f"{BASE}/skills/{skill_id}/versions/1", headers=bearer(auth_user.id))).json()
    digest = "sha256:" + "d" * 64
    await client.put(f"{BASE}/skills/{skill_id}/versions/1", headers={**bearer(auth_user.id), "If-Match": draft["digest"]},
                     json={"launch_spec": {**draft["launch_spec"], "image_digest": digest}})
    await force_publish(db, skill_id, approver_id=auth_user.id)
    headers, _ = await _gateway(db, project_id)
    denied = (await client.get(f"{GATEWAY}/skills/manifest", headers=headers)).json()
    assert denied["mcp_servers"] == [] and {"name": "terraform", "reason": "needs_mcp_policy"} in denied["withheld"]
    project = await db.get(Project, project_id)
    project.config = {**(project.config or {}), "mcp_policy": {"enabled_servers": ["terraform"]}}
    await db.commit()
    allowed = (await client.get(f"{GATEWAY}/skills/manifest", headers=headers)).json()
    server = allowed["mcp_servers"][0]
    assert server["server"]["args"] == ["run", "-i", "--rm", "-e", "TFE_TOKEN",
                                        f"hashicorp/terraform-mcp-server@{digest}"]
    assert server["server"]["env"] == {} and server["env_unset"] == ["TFE_TOKEN"]


@pytest.mark.asyncio
async def test_skill_calls_and_slash_commands_are_recorded_by_name_only(client, db, auth_user):
    project_id = await _project_id(db)
    terraform = (await category(db, "iac.terraform")).id
    skill, _ = await published_skill(db, terraform, "style-guide", approver_id=auth_user.id)
    skill_id = skill.id
    await db.commit()
    headers, session_id = await _gateway(db, project_id)
    for tool_input in ({"skill": "octryx:style-guide", "args": "secret prompt text"},
                       {"skill": "my-local-skill"}):
        response = await client.post(f"{GATEWAY}/sessions/tool-check", headers=headers, json={
            "hook_event_name": "PreToolUse", "session_id": "c", "cwd": "/w", "tool_name": "Skill",
            "tool_input": tool_input, "tool_use_id": f"toolu_{uuid.uuid4().hex[:8]}"})
        assert response.status_code == 200, response.text
    used = await client.post(f"{GATEWAY}/sessions/skill-used", headers=headers,
                             json={"command_name": "octryx:style-guide", "command_source": "plugin"})
    assert used.json() == {"state": "recorded", "managed": True}
    events = (await db.execute(select(SkillUsageEvent).where(SkillUsageEvent.session_id == session_id)
                               .order_by(SkillUsageEvent.created_at))).scalars().all()
    assert [(item.invocation, item.skill_id, item.skill_name) for item in events] == [
        ("model", skill_id, "style-guide"), ("model", None, "my-local-skill"), ("slash", skill_id, "style-guide")]
    assert all(item.surface == "octryx_claude" and item.project_id == project_id for item in events)
    assert events[1].event_metadata["unmanaged"] is True and events[0].bundle_digest.startswith("sha256:")
    assert not any("secret prompt" in str(item.event_metadata) + str(item.query_excerpt) for item in events)
    for name, tool_input in (("Read", {"file_path": "/w/a"}), ("Bash", {"command": "ls"})):
        other = await client.post(f"{GATEWAY}/sessions/tool-check", headers=headers, json={
            "hook_event_name": "PreToolUse", "session_id": "c", "cwd": "/w", "tool_name": name,
            "tool_input": tool_input, "tool_use_id": f"toolu_{name}"})
        assert other.status_code == 200
    count = (await db.execute(select(SkillUsageEvent).where(SkillUsageEvent.session_id == session_id))).scalars()
    assert len(list(count)) == 3  # only Skill calls are recorded
