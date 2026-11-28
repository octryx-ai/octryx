"""Upstream renewal: per-path change detection, moved folders, 3-way update drafts, pin/follow, scheduled checks,
worked on a real style-guide skill whose folder moved and a marketplace entry that did not change."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Notification, Skill, SkillVersion
from app.services.skill_catalog.upstream import run_scheduled_checks
from tests.policy_engine_support import bearer, make_user
from tests.skill_catalog.fake_git import HASHICORP, MARKET, MARKET_LATER, NEW, OFFICIAL, OLD, STYLE_NEW
from tests.skill_catalog.support import BASE, category

pytestmark = pytest.mark.usefixtures("chat_skills")

OLD_PATH = "terraform/code-generation/skills/terraform-style-guide"
NEW_PATH = "plugins/terraform/skills/terraform-style-guide"
CHECKLIST_LINE = "- [ ] Plan output reviewed before apply\n"
SECURITY_LINE = "- Enable deletion protection on stateful resources\n"


async def _publish(client, author, reviewer, skill_id, version):
    submitted = await client.post(f"{BASE}/skills/{skill_id}/versions/{version}/submit", headers=bearer(author))
    assert submitted.status_code == 200, submitted.text
    approval_id = submitted.json()["governance_approval_id"]
    assert (await client.post(f"/api/v1/approvals/{approval_id}/approve", json={"reason": "ok"},
                              headers=bearer(reviewer))).status_code == 200
    published = await client.post(f"{BASE}/skills/{skill_id}/versions/{version}/publish",
                                  json={"governance_approval_id": approval_id}, headers=bearer(author))
    assert published.status_code == 200, published.text


async def _customized_style_guide(client, db, author, reviewer, *, tracking="pinned") -> str:
    terraform = (await category(db, "iac.terraform")).id
    imported = await client.post(f"{BASE}/import/git", headers=bearer(author), json={
        "url": HASHICORP, "ref": "main", "commit": OLD, "trust": "official",
        "items": [{"path": OLD_PATH, "category_id": terraform, "tracking_mode": tracking}]})
    assert imported.status_code == 201, imported.text
    skill_id = imported.json()["imported"][0]["skill_id"]
    await _publish(client, author, reviewer, skill_id, 1)
    draft = await client.post(f"{BASE}/skills/{skill_id}/edit", headers=bearer(author))
    text = (await client.get(f"{BASE}/skills/{skill_id}/versions/2/files", params={"path": "SKILL.md"},
                             headers=bearer(author))).json()["content"]
    text = text.replace("- [ ] Variables have type and description\n",
                        "- [ ] Variables have type and description\n" + CHECKLIST_LINE)
    text = text.replace("- Use least-privilege IAM policies\n", "- Use least-privilege IAM policies\n" + SECURITY_LINE)
    saved = await client.put(f"{BASE}/skills/{skill_id}/versions/2", json={"skill_md": text},
                             headers={**bearer(author), "If-Match": draft.json()["digest"]})
    assert saved.status_code == 200, saved.text
    await _publish(client, author, reviewer, skill_id, 2)
    return skill_id


@pytest.mark.asyncio
async def test_the_style_guide_update_detects_the_move_merges_one_line_and_relocates_the_other(client, db, fake_git):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    skill_id = await _customized_style_guide(client, db, author, reviewer)

    status = (await client.post(f"{BASE}/skills/{skill_id}/upstream/check", headers=bearer(author))).json()
    assert status["update_available"] is True and status["latest_commit"] == NEW
    assert status["path_moved"] == {"from": OLD_PATH, "to": NEW_PATH} and status["current_commit"] == OLD
    listed = (await client.get(f"{BASE}/skills", params={"state": "update"}, headers=bearer(author))).json()
    assert [row["id"] for row in listed["items"]] == [skill_id] and listed["counts"]["updates"] == 1

    updated = await client.post(f"{BASE}/skills/{skill_id}/upstream/update", headers=bearer(author))
    assert updated.status_code == 201, updated.text
    draft = updated.json()
    report = draft["merge_report"]
    assert draft["version"] == 3 and draft["base_version"] == 2 and draft["upstream"]["path"] == NEW_PATH
    assert report["path_moved"] == {"from": OLD_PATH, "to": NEW_PATH} and report["theirs_commit"] == NEW
    statuses = {item["path"]: item["status"] for item in report["files"]}
    assert statuses == {"LICENSE": "unchanged", "SECURITY.md": "added_upstream", "SKILL.md": "conflict"}
    assert len(report["conflicts"]) == 1
    conflict = report["conflicts"][0]
    assert SECURITY_LINE in conflict["ours"] and conflict["relocation"]["path"] == "SECURITY.md"
    skill_md = (await client.get(f"{BASE}/skills/{skill_id}/versions/3/files", params={"path": "SKILL.md"},
                                 headers=bearer(author))).json()["content"]
    assert CHECKLIST_LINE in skill_md and ">= 1.14" in skill_md and "lifecycle-status: active" in skill_md
    assert "Refer to SECURITY.md" in skill_md and SECURITY_LINE not in skill_md

    blocked = await client.post(f"{BASE}/skills/{skill_id}/versions/3/submit", headers=bearer(author))
    assert blocked.json()["detail"] == {"code": "skill_draft_has_conflicts", "conflicts": [conflict["id"]]}
    again = await client.post(f"{BASE}/skills/{skill_id}/upstream/update", headers=bearer(author))
    assert again.json()["detail"]["code"] == "skill_draft_exists"

    resolved = await client.put(f"{BASE}/skills/{skill_id}/versions/3",
                                json={"resolutions": {conflict["id"]: {"choice": "relocate"}}},
                                headers={**bearer(author), "If-Match": draft["digest"]})
    assert resolved.status_code == 200, resolved.text
    security = (await client.get(f"{BASE}/skills/{skill_id}/versions/3/files", params={"path": "SECURITY.md"},
                                 headers=bearer(author))).json()["content"]
    assert security.endswith("- Use least-privilege IAM policies\n" + SECURITY_LINE)
    await _publish(client, author, reviewer, skill_id, 3)
    skill = await db.get(Skill, skill_id)
    await db.refresh(skill)
    assert skill.upstream_path == NEW_PATH and skill.pinned_commit == NEW
    status = (await client.post(f"{BASE}/skills/{skill_id}/upstream/check", headers=bearer(author))).json()
    assert status["update_available"] is False and status["path_moved"] is None
    up_to_date = await client.post(f"{BASE}/skills/{skill_id}/upstream/update", headers=bearer(author))
    assert up_to_date.json()["detail"]["code"] == "skill_up_to_date"


@pytest.mark.asyncio
async def test_other_resolutions_take_upstream_keep_mine_or_manual_text(client, db, fake_git):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    skill_id = await _customized_style_guide(client, db, author, reviewer)
    draft = (await client.post(f"{BASE}/skills/{skill_id}/upstream/update", headers=bearer(author))).json()
    conflict_id = draft["merge_report"]["conflicts"][0]["id"]
    etag = draft["digest"]
    for resolution, expected in [({"choice": "relocate"}, "Refer to SECURITY.md"), ({"choice": "mine"}, SECURITY_LINE),
                                 ({"choice": "manual", "text": "Use the SECURITY.md checklist and protect state.\n"},
                                  "protect state"),
                                 ({"choice": "upstream"}, "Refer to SECURITY.md")]:
        saved = await client.put(f"{BASE}/skills/{skill_id}/versions/3", json={"resolutions": {conflict_id: resolution}},
                                 headers={**bearer(author), "If-Match": etag})
        assert saved.status_code == 200, saved.text
        etag = saved.json()["digest"]
        text = (await client.get(f"{BASE}/skills/{skill_id}/versions/3/files", params={"path": "SKILL.md"},
                                 headers=bearer(author))).json()["content"]
        assert expected in text, resolution
        security = (await client.get(f"{BASE}/skills/{skill_id}/versions/3/files", params={"path": "SECURITY.md"},
                                     headers=bearer(author))).json()["content"]
        assert (SECURITY_LINE in security) == (resolution["choice"] == "relocate"), resolution
    bad = await client.put(f"{BASE}/skills/{skill_id}/versions/3", json={"resolutions": {conflict_id: {"choice": "x"}}},
                           headers={**bearer(author), "If-Match": etag})
    assert bad.json()["detail"]["code"] == "skill_resolution_invalid"
    unknown = await client.put(f"{BASE}/skills/{skill_id}/versions/3", json={"resolutions": {"c-x": {"choice": "mine"}}},
                               headers={**bearer(author), "If-Match": etag})
    assert unknown.json()["detail"]["code"] == "skill_conflict_unknown"


@pytest.mark.asyncio
async def test_the_official_marketplace_entry_is_up_to_date_although_the_repository_moved_on(client, db, fake_git):
    author = await make_user(db, admin=True)
    terraform = (await category(db, "iac.terraform")).id
    imported = await client.post(f"{BASE}/import/git", headers=bearer(author), json={
        "url": OFFICIAL, "ref": MARKET, "marketplace_plugin": "terraform", "commit": MARKET, "trust": "official",
        "items": [{"kind": "mcp_server", "path": "external_plugins/terraform", "name": "terraform",
                   "category_id": terraform}]})
    assert imported.status_code == 201, imported.text
    skill_id = imported.json()["imported"][0]["skill_id"]
    status = (await client.post(f"{BASE}/skills/{skill_id}/upstream/check", headers=bearer(author))).json()
    assert status["latest_commit"] == MARKET_LATER and status["compare_ref"] == "HEAD"
    assert status["update_available"] is False
    update = await client.post(f"{BASE}/skills/{skill_id}/upstream/update", headers=bearer(author))
    assert update.json()["detail"]["code"] == "skill_draft_exists"
    follow = await client.put(f"{BASE}/skills/{skill_id}/tracking", json={"tracking_mode": "follow"},
                              headers=bearer(author))
    assert follow.json()["detail"]["code"] == "skill_follow_requires_branch"


@pytest.mark.asyncio
async def test_a_vanished_path_without_a_unique_match_needs_the_admin_to_pick_it(client, db, fake_git):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    skill_id = await _customized_style_guide(client, db, author, reviewer)
    newest = "aaaa0000" + "0" * 32
    files = dict(fake_git.repos[HASHICORP][NEW])
    files.pop(f"{NEW_PATH}/SKILL.md")
    files.pop(f"{NEW_PATH}/SECURITY.md")
    files["a/terraform-style-guide/SKILL.md"] = (STYLE_NEW, "100644")
    files["b/terraform-style-guide/SKILL.md"] = (STYLE_NEW, "100644")
    fake_git.repos[HASHICORP][newest] = files
    fake_git.refs[HASHICORP]["main"] = newest
    missing = await client.post(f"{BASE}/skills/{skill_id}/upstream/check", headers=bearer(author))
    assert missing.status_code == 409 and missing.json()["detail"]["code"] == "skill_upstream_path_missing"
    assert missing.json()["detail"]["candidates"] == ["a/terraform-style-guide", "b/terraform-style-guide"]
    skill = await db.get(Skill, skill_id)
    await db.refresh(skill)
    assert skill.upstream_status["error"] == "skill_upstream_path_missing"
    picked = await client.post(f"{BASE}/skills/{skill_id}/upstream/check", json={"path": "b/terraform-style-guide"},
                               headers=bearer(author))
    assert picked.json()["path"] == "b/terraform-style-guide" and picked.json()["update_available"] is True
    files["a/terraform-style-guide/SKILL.md"] = (STYLE_NEW.replace("name: terraform-style-guide", "name: other"),
                                                 "100644")
    single = await client.post(f"{BASE}/skills/{skill_id}/upstream/check", headers=bearer(author))
    assert single.json()["path_moved"]["to"] == "b/terraform-style-guide"  # the frontmatter name decides


@pytest.mark.asyncio
async def test_follow_lets_the_scheduled_check_create_the_draft_and_notify_the_owner(client, db, fake_git):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    terraform = (await category(db, "iac.terraform")).id
    imported = await client.post(f"{BASE}/import/git", headers=bearer(author), json={
        "url": HASHICORP, "ref": "main", "commit": NEW,
        "items": [{"path": NEW_PATH, "category_id": terraform, "tracking_mode": "follow"}]})
    skill_id = imported.json()["imported"][0]["skill_id"]
    await _publish(client, author, reviewer, skill_id, 1)
    readme_only = "bbbb0000" + "0" * 32
    files = dict(fake_git.repos[HASHICORP][NEW])
    files["README.md"] = ("# Only the README changed\n", "100644")
    fake_git.repos[HASHICORP][readme_only] = files
    fake_git.refs[HASHICORP]["main"] = readme_only
    first = await run_scheduled_checks(db, force=True)
    assert first["updates"] == 0 and first["drafts"] == 0  # repository commits that skip the skill change nothing

    changed = "cccc0000" + "0" * 32
    files = dict(files)
    files[f"{NEW_PATH}/SKILL.md"] = (STYLE_NEW.replace(">= 1.14", ">= 1.15"), "100644")
    fake_git.repos[HASHICORP][changed] = files
    fake_git.refs[HASHICORP]["main"] = changed
    second = await run_scheduled_checks(db, force=True)
    assert second["updates"] == 1 and second["drafts"] == 1 and second["errors"] == 0
    draft = (await db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill_id,
                                                         SkillVersion.state == "draft"))).scalar_one()
    assert draft.created_by is None and draft.upstream_commit == changed and draft.merge_report["conflicts"] == []
    notice = (await db.execute(select(Notification).where(Notification.user_id == author))).scalars().all()
    assert any("terraform-style-guide" in item.title for item in notice)
    third = await run_scheduled_checks(db, force=True)
    assert third["drafts"] == 0
    assert (await run_scheduled_checks(db))["sources"] == 0


@pytest.mark.asyncio
async def test_tracking_can_switch_between_pinned_and_follow_on_a_branch(client, db, fake_git):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    skill_id = await _customized_style_guide(client, db, author, reviewer, tracking="follow")
    pinned = await client.put(f"{BASE}/skills/{skill_id}/tracking", json={"tracking_mode": "pinned"},
                              headers=bearer(author))
    assert pinned.json() == {"skill_id": skill_id, "tracking_mode": "pinned", "pinned_commit": OLD}
    follow = await client.put(f"{BASE}/skills/{skill_id}/tracking", json={"tracking_mode": "follow"},
                              headers=bearer(author))
    assert follow.json()["pinned_commit"] is None
    bad = await client.put(f"{BASE}/skills/{skill_id}/tracking", json={"tracking_mode": "x"}, headers=bearer(author))
    assert bad.json()["detail"]["code"] == "skill_tracking_mode_invalid"
    plain = (await db.execute(select(Skill).where(Skill.name == "cluster-health"))).scalar_one()
    untracked = await client.post(f"{BASE}/skills/{plain.id}/upstream/check", headers=bearer(author))
    assert untracked.json()["detail"]["code"] == "skill_not_tracked"


@pytest.mark.asyncio
async def test_a_pinned_skill_is_only_reported_by_the_scheduled_check(client, db, fake_git):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    skill_id = await _customized_style_guide(client, db, author, reviewer, tracking="pinned")
    summary = await run_scheduled_checks(db, force=True)
    assert summary["updates"] == 1 and summary["drafts"] == 0
    skill = await db.get(Skill, skill_id)
    await db.refresh(skill)
    assert skill.upstream_status["update_available"] is True
