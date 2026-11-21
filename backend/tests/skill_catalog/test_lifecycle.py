"""Versioning and four-eyes publish (the policy-set lifecycle pattern)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Approval, AuditLog, Skill, SkillVersion
from tests.policy_engine_support import bearer, make_user
from tests.skill_catalog.fake_git import MARKET_LATER, OFFICIAL
from tests.skill_catalog.support import BASE, category

# Two published chat-only skills as a fixture.
pytestmark = pytest.mark.usefixtures("chat_skills")

BODY = "\n# Release notes\n\n1. Collect the merged changes.\n2. Group them by area.\n"


async def _create(client, admin, category_id, name="release-notes", **extra):
    payload = {"name": name, "category_id": category_id, "body": BODY,
               "frontmatter": {"description": "Write release notes from merged changes."}, **extra}
    response = await client.post(f"{BASE}/skills", json=payload, headers=bearer(admin))
    assert response.status_code == 201, response.text
    return response


async def _save(client, admin, skill_id, version, etag, **payload):
    headers = {**bearer(admin), "If-Match": etag} if etag else bearer(admin)
    return await client.put(f"{BASE}/skills/{skill_id}/versions/{version}", json=payload, headers=headers)


async def _approve(client, reviewer, approval_id):
    response = await client.post(f"/api/v1/approvals/{approval_id}/approve", json={"reason": "reviewed"},
                                 headers=bearer(reviewer))
    assert response.status_code == 200, response.text


async def _publish(client, admin, skill_id, version, approval_id):
    return await client.post(f"{BASE}/skills/{skill_id}/versions/{version}/publish",
                             json={"governance_approval_id": approval_id}, headers=bearer(admin))


async def _submit(client, admin, skill_id, version):
    response = await client.post(f"{BASE}/skills/{skill_id}/versions/{version}/submit", headers=bearer(admin))
    return response


@pytest.mark.asyncio
async def test_lifecycle_endpoints_are_platform_admin_only(client, db):
    member = await make_user(db, admin=False)
    for method, path in [("get", "/skills"), ("post", "/skills"), ("get", "/skills/x"), ("post", "/skills/x/edit"),
                         ("put", "/skills/x/versions/1"), ("post", "/skills/x/versions/1/submit"),
                         ("post", "/skills/x/versions/1/publish"), ("post", "/skills/x/versions/1/retire")]:
        kwargs = {"json": {}} if method in {"post", "put"} else {}
        response = await getattr(client, method)(f"{BASE}{path}", headers=bearer(member), **kwargs)
        assert response.status_code == 403, path


@pytest.mark.asyncio
async def test_drafts_save_under_if_match_and_publish_needs_a_second_admin(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    docs = (await category(db, "engineering.documentation")).id
    created = await _create(client, author, docs, tags=["Docs"])
    body = created.json()
    # A gzip-compressed answer carries the weak ETag W/"digest"; If-Match accepts both forms.
    skill_id, etag = body["skill_id"], created.headers["ETag"].removeprefix("W/").strip('"')
    assert body["state"] == "draft" and body["licence_spdx"] == "Internal" and etag == body["digest"]

    assert (await _save(client, author, skill_id, 1, None, body="x")).status_code == 428
    stale = await _save(client, author, skill_id, 1, "sha256:" + "0" * 64, body="x")
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "skill_draft_conflict"
    saved = await _save(client, author, skill_id, 1, etag, body=BODY + "3. Link the tickets.\n",
                        extension={"safety_rules": ["Never publish secrets"]}, files={"references/style.md": "# S\n"})
    assert saved.status_code == 200, saved.text
    new_etag = saved.json()["digest"]
    assert new_etag != etag and {item["path"] for item in saved.json()["files"]} == {"SKILL.md", "references/style.md"}
    assert saved.json()["extension"]["safety_rules"] == ["Never publish secrets"]
    second = await _save(client, author, skill_id, 1, etag, body="lost update")
    assert second.json()["detail"]["code"] == "skill_draft_conflict"
    invalid = await _save(client, author, skill_id, 1, new_etag, frontmatter={"name": "other", "description": "d"})
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "skill_spec_invalid"
    no_reason = await _save(client, author, skill_id, 1, new_etag, scripts_allowed=True)
    assert no_reason.json()["detail"]["code"] == "skill_scripts_reason_required"

    submitted = await _submit(client, author, skill_id, 1)
    approval_id = submitted.json()["governance_approval_id"]
    frozen = await _save(client, author, skill_id, 1, new_etag, body="x")
    assert frozen.json()["detail"]["code"] == "skill_version_not_draft"
    early = await _publish(client, author, skill_id, 1, approval_id)
    assert early.json()["detail"]["code"] == "skill_approval_not_approved"
    # Four-eyes holds at the decision itself, not only at publish.
    own = await client.post(f"/api/v1/approvals/{approval_id}/approve", json={"reason": "mine"}, headers=bearer(author))
    assert own.status_code == 409 and own.json()["detail"]["code"] == "self_approval_not_allowed"
    still = await _publish(client, author, skill_id, 1, approval_id)
    assert still.json()["detail"]["code"] == "skill_approval_not_approved"

    # A fresh round with a second admin.
    await client.post(f"{BASE}/skills/{skill_id}/versions/1/retire", headers=bearer(author))
    rollback = await client.post(f"{BASE}/skills/{skill_id}/versions/1/rollback", headers=bearer(author))
    assert rollback.status_code == 201 and rollback.json()["version"] == 2
    approval_id = (await _submit(client, author, skill_id, 2)).json()["governance_approval_id"]
    await _approve(client, reviewer, approval_id)
    published = await _publish(client, author, skill_id, 2, approval_id)
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "published" and published.json()["approval_gate"]["approved_by"] == reviewer
    skill = await db.get(Skill, skill_id)
    await db.refresh(skill)
    assert skill.published_version_id == published.json()["id"] and skill.available_platform_chat
    published_row = await db.get(SkillVersion, published.json()["id"])
    assert published_row.extension["safety_rules"] == ["Never publish secrets"]
    actions = set((await db.execute(select(AuditLog.action).where(AuditLog.action.like("skill_catalog.%")))).scalars())
    assert {"skill_catalog.draft_saved", "skill_catalog.submitted", "skill_catalog.published",
            "skill_catalog.retired"} <= actions

    detail = (await client.get(f"{BASE}/skills/{skill_id}", headers=bearer(author))).json()
    assert detail["published"]["version"] == 2 and detail["open"] is None and detail["tags"] == ["docs"]
    assert [row["state"] for row in detail["versions"]] == ["published", "retired"]
    assert detail["versions"][0]["reviewer_name"] and detail["category"]["path"] == ["Engineering", "Documentation"]


@pytest.mark.asyncio
async def test_edit_continues_the_open_draft_and_publishing_retires_the_previous_version(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    skill = (await db.execute(select(Skill).where(Skill.name == "cluster-health"))).scalar_one()
    skill_id = skill.id
    started = await client.post(f"{BASE}/skills/{skill_id}/edit", headers=bearer(author))
    assert started.json()["created"] is True and started.json()["version"] == 2 and started.json()["base_version"] == 1
    again = await client.post(f"{BASE}/skills/{skill_id}/edit", headers=bearer(author))
    assert again.json()["created"] is False and again.json()["version"] == 2
    etag = again.headers["ETag"].removeprefix("W/").strip('"')
    saved = await _save(client, author, skill_id, 2, etag, body="\n# Cluster health\n\nCheck nodes, then pods.\n")
    diff = (await client.get(f"{BASE}/skills/{skill_id}/versions/2/diff", headers=bearer(author))).json()
    assert diff["against"] == 1 and diff["files"][0]["status"] == "changed" and diff["files"][0]["added"] >= 1
    approval_id = (await _submit(client, author, skill_id, 2)).json()["governance_approval_id"]
    in_review = await client.post(f"{BASE}/skills/{skill_id}/edit", headers=bearer(author))
    assert in_review.json()["detail"]["code"] == "skill_version_in_review"
    await _approve(client, reviewer, approval_id)
    assert (await _publish(client, reviewer, skill_id, 2, approval_id)).status_code == 200
    states = {row.version: row.state for row in (await db.execute(
        select(SkillVersion).where(SkillVersion.skill_id == skill_id))).scalars()}
    assert states == {1: "retired", 2: "published"}
    listed = (await client.get(f"{BASE}/skills", params={"state": "published", "q": "cluster"},
                               headers=bearer(author))).json()
    assert [row["name"] for row in listed["items"]] == ["cluster-health"]
    assert listed["items"][0]["published"]["version"] == 2 and saved.status_code == 200
    file = await client.get(f"{BASE}/skills/{skill_id}/versions/2/files", params={"path": "SKILL.md"},
                            headers=bearer(author))
    assert "Check nodes, then pods." in file.json()["content"] and file.json()["kind"] == "instructions"


@pytest.mark.asyncio
async def test_publish_refuses_a_licence_outside_the_allowlist_and_a_mismatched_approval(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    docs = (await category(db, "engineering.documentation")).id
    first = (await _create(client, author, docs, name="first-skill")).json()["skill_id"]
    second = await _create(client, author, docs, name="second-skill", licence_spdx="GPL-3.0")
    second_id = second.json()["skill_id"]
    first_approval = (await _submit(client, author, first, 1)).json()["governance_approval_id"]
    second_approval = (await _submit(client, author, second_id, 1)).json()["governance_approval_id"]
    counts = (await client.get(f"{BASE}/skills", headers=bearer(author))).json()["counts"]
    assert counts["in_review"] == 2
    await _approve(client, reviewer, first_approval)
    await _approve(client, reviewer, second_approval)
    mismatched = await _publish(client, author, second_id, 1, first_approval)
    assert mismatched.json()["detail"]["code"] == "skill_approval_mismatched"
    licence = await _publish(client, author, second_id, 1, second_approval)
    assert licence.json()["detail"]["code"] == "skill_licence_not_allowed"
    assert licence.json()["detail"]["licence"] == "GPL-3.0"
    await client.put(f"{BASE}/settings", json={"licence_allowlist": ["MIT", "GPL-3.0"]}, headers=bearer(author))
    assert (await _publish(client, author, second_id, 1, second_approval)).status_code == 200
    counts = (await client.get(f"{BASE}/skills", headers=bearer(author))).json()["counts"]
    assert counts["in_review"] == 1 and counts["published"] >= 3


@pytest.mark.asyncio
async def test_the_single_admin_declaration_allows_self_approval_only_on_a_local_stack(client, db, monkeypatch):
    author = await make_user(db, admin=True)
    docs = (await category(db, "engineering.documentation")).id
    skill_id = (await _create(client, author, docs, name="solo-skill")).json()["skill_id"]
    approval_id = (await _submit(client, author, skill_id, 1)).json()["governance_approval_id"]
    monkeypatch.setattr(get_settings(), "four_eyes_dev_self_approval", True)
    monkeypatch.setattr(get_settings(), "runtime_profile", "production")
    refused = await client.post(f"/api/v1/approvals/{approval_id}/approve", json={"reason": "solo"},
                                headers=bearer(author))
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "self_approval_not_allowed"
    monkeypatch.setattr(get_settings(), "runtime_profile", "local")
    monkeypatch.setattr(get_settings(), "cors_allowed_origins", "http://localhost:3000")
    await _approve(client, author, approval_id)
    published = await _publish(client, author, skill_id, 1, approval_id)
    assert published.status_code == 200 and published.json()["approval_gate"]["single_admin_self_approval"] is True


@pytest.mark.asyncio
async def test_retiring_the_published_version_removes_the_skill_and_rollback_restores_a_draft(client, db):
    author = await make_user(db, admin=True)
    skill = (await db.execute(select(Skill).where(Skill.name == "alert-diagnosis"))).scalar_one()
    skill_id = skill.id
    retired = await client.post(f"{BASE}/skills/{skill_id}/versions/1/retire", headers=bearer(author))
    assert retired.status_code == 200
    await db.refresh(skill)
    assert skill.published_version_id is None and not skill.available_platform_chat
    again = await client.post(f"{BASE}/skills/{skill_id}/versions/1/retire", headers=bearer(author))
    assert again.json()["detail"]["code"] == "skill_version_retired"
    nothing = await client.post(f"{BASE}/skills/{skill_id}/edit", headers=bearer(author))
    assert nothing.json()["detail"]["code"] == "skill_nothing_to_edit"
    restored = await client.post(f"{BASE}/skills/{skill_id}/versions/1/rollback", headers=bearer(author))
    assert restored.status_code == 201 and restored.json()["state"] == "draft"
    blocked = await client.post(f"{BASE}/skills/{skill_id}/versions/1/rollback", headers=bearer(author))
    assert blocked.json()["detail"]["code"] == "skill_draft_exists"
    listed = (await client.get(f"{BASE}/skills", params={"state": "draft"}, headers=bearer(author))).json()
    assert "alert-diagnosis" in [row["name"] for row in listed["items"]]


@pytest.mark.asyncio
async def test_an_approval_decided_by_a_non_admin_never_publishes(client, db):
    author, member = await make_user(db, admin=True), await make_user(db, admin=False)
    docs = (await category(db, "engineering.documentation")).id
    skill_id = (await _create(client, author, docs, name="member-approved")).json()["skill_id"]
    approval_id = (await _submit(client, author, skill_id, 1)).json()["governance_approval_id"]
    approval = await db.get(Approval, approval_id)
    approval.status, approval.approved_by = "approved", member
    await db.commit()
    refused = await _publish(client, author, skill_id, 1, approval_id)
    assert refused.json()["detail"]["code"] == "skill_approver_not_platform_admin"
    missing = await _publish(client, author, skill_id, 1, None)
    assert missing.json()["detail"]["code"] == "skill_approval_required"


@pytest.mark.asyncio
async def test_an_mcp_server_entry_publishes_only_with_a_recorded_image_digest(client, db, fake_git):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    terraform = (await category(db, "iac.terraform")).id
    imported = await client.post(f"{BASE}/import/git", headers=bearer(author), json={
        "url": OFFICIAL, "ref": "main", "marketplace_plugin": "terraform", "commit": MARKET_LATER,
        "items": [{"kind": "mcp_server", "path": "external_plugins/terraform", "name": "terraform",
                   "category_id": terraform, "tracking_mode": "follow"}]})
    skill_id = imported.json()["imported"][0]["skill_id"]
    approval_id = (await _submit(client, author, skill_id, 1)).json()["governance_approval_id"]
    await _approve(client, reviewer, approval_id)
    refused = await _publish(client, author, skill_id, 1, approval_id)
    assert refused.json()["detail"]["code"] == "skill_mcp_image_digest_missing"
    await client.post(f"{BASE}/skills/{skill_id}/versions/1/retire", headers=bearer(author))
    draft = await client.post(f"{BASE}/skills/{skill_id}/versions/1/rollback", headers=bearer(author))
    spec = {**draft.json()["launch_spec"], "image_digest": "sha256:" + "c" * 64}
    saved = await _save(client, author, skill_id, 2, draft.json()["digest"], launch_spec=spec,
                        acknowledged_findings=["mcp_credential_passthrough:TFE_TOKEN"])
    assert saved.json()["launch_spec"]["image_digest"] == "sha256:" + "c" * 64
    approval_id = (await _submit(client, author, skill_id, 2)).json()["governance_approval_id"]
    await _approve(client, reviewer, approval_id)
    assert (await _publish(client, author, skill_id, 2, approval_id)).status_code == 200


@pytest.mark.asyncio
async def test_a_rejected_review_never_publishes(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    docs = (await category(db, "engineering.documentation")).id
    skill_id = (await _create(client, author, docs, name="rejected-skill")).json()["skill_id"]
    approval_id = (await _submit(client, author, skill_id, 1)).json()["governance_approval_id"]
    rejected = await client.post(f"/api/v1/approvals/{approval_id}/reject", json={"reason": "no"},
                                 headers=bearer(reviewer))
    assert rejected.status_code == 200, rejected.text
    refused = await _publish(client, author, skill_id, 1, approval_id)
    assert refused.json()["detail"] == {"code": "skill_approval_not_approved", "approval_status": "rejected"}


@pytest.mark.asyncio
async def test_draft_editors_and_the_script_allower_cannot_approve_the_version(client, db):
    author, editor, allower, reviewer = [await make_user(db, admin=True) for _ in range(4)]
    docs = (await category(db, "engineering.documentation")).id
    created = await _create(client, author, docs, name="many-hands")
    skill_id, etag = created.json()["skill_id"], created.headers["ETag"].removeprefix("W/").strip('"')
    saved = await _save(client, editor, skill_id, 1, etag, body=BODY + "3. Edited by a second admin.\n")
    assert saved.status_code == 200, saved.text
    approval_id = (await _submit(client, author, skill_id, 1)).json()["governance_approval_id"]
    row = (await db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill_id))).scalar_one()
    row.scripts_allowed_by = allower
    approval = await db.get(Approval, approval_id)
    approval.status = "approved"
    for actor in (editor, allower):
        approval.approved_by = actor
        await db.commit()
        refused = await _publish(client, author, skill_id, 1, approval_id)
        assert refused.json()["detail"]["code"] == "skill_self_approval", actor
    approval.approved_by = reviewer
    await db.commit()
    published = await _publish(client, author, skill_id, 1, approval_id)
    assert published.status_code == 200, published.text


@pytest.mark.asyncio
async def test_the_approval_rule_lets_a_single_admin_publish_in_one_step(client, db, monkeypatch):
    from app.services.governance import four_eyes

    monkeypatch.setattr(four_eyes, "dev_self_approval_permitted", lambda settings=None: False)
    author = await make_user(db, admin=True)
    docs = (await category(db, "engineering.documentation")).id
    skill_id = (await _create(client, author, docs, name="one-step-skill")).json()["skill_id"]
    assert (await _submit(client, author, skill_id, 1)).status_code == 200
    url = f"{BASE}/skills/{skill_id}/versions/1/publish"
    refused = await client.post(url, json={"self_approve": True}, headers=bearer(author))
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "skill_self_approval"

    rule = await client.put("/api/v1/admin/governance/approval-rule", json={"rule": "single_admin"},
                            headers=bearer(author))
    assert rule.status_code == 200
    published = await client.post(url, json={"self_approve": True}, headers=bearer(author))
    assert published.status_code == 200, published.text
    assert published.json()["approval_gate"]["approval_mode"] == "self"
    audited = (await db.execute(select(AuditLog).where(
        AuditLog.action == "governance.four_eyes.self_approval"))).scalars().all()
    assert [row.resource_type for row in audited] == ["skill_version"]
