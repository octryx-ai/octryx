"""Workspace backup history, platform-wide skills never overwritten silently, a restore that
keeps the target's active state, and one export path whose import jobs are scoped like its export jobs."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Skill, SkillVersion, User
from app.services.data_transfer import create_data_export_job, create_data_import_job
from tests.policy_engine_support import bearer, make_user


def _backup(name: str, skills: list[dict]) -> dict:
    return {
        "export_type": "admin_config_backup",
        "manifest": {"package_type": "admin_config_backup", "included_sections": ["project_config", "skills"]},
        "project": {"name": name, "description": "restored", "config": {}, "is_active": False},
        "tasks": [],
        "agents": [],
        "skills": skills,
    }


def _skill(name: str, content: str) -> dict:
    """A backup row: the portable catalog bundle of a published skill."""
    return {"format": "skill_bundle", "name": name, "category": "Utility",
            "files": {"SKILL.md": f"---\nname: {name}\ndescription: d\n---\n\n{content}\n"}, "extension": {}}


@pytest.mark.asyncio
async def test_a_restore_keeps_existing_platform_skills_unless_asked_and_keeps_the_target_active(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    existing = f"s10-existing-{uuid.uuid4().hex[:6]}"
    fresh = f"s10-new-{uuid.uuid4().hex[:6]}"
    original = Skill(id=str(uuid.uuid4()), name=existing, category="utility")
    db.add(original)
    target = Project(id=str(uuid.uuid4()), name=f"s10-target-{uuid.uuid4().hex[:6]}", is_active=True, config={})
    db.add(target)
    await db.commit()
    target_id = target.id
    payload = _backup("source", [_skill(existing, "from backup"), _skill(fresh, "new")])

    job = await create_data_import_job(
        db, current_user=admin, import_type="admin_config_backup", source_format="json", payload_json=payload,
        payload_text=None, target_project_id=target_id, overwrite_existing=True,
    )
    assert job["summary"]["skills_kept"] == [existing], "overwrite_existing alone never touches platform skills"
    assert job["summary"]["skills_created"] == [fresh]
    kept = (await db.execute(select(SkillVersion.id).where(SkillVersion.skill_id == original.id))).all()
    assert kept == [], "a kept skill gets no draft from the backup"
    restored = await db.get(Project, target_id)
    await db.refresh(restored)
    assert restored.is_active is True, "a restore never archives the target Workspace"

    again = await create_data_import_job(
        db, current_user=admin, import_type="admin_config_backup", source_format="json", payload_json=payload,
        payload_text=None, target_project_id=target_id, overwrite_skills=True,
    )
    # The draft restored before is replaced; a published skill still changes only through the catalog lifecycle.
    assert again["summary"]["skills_overwritten"] == [fresh]
    assert again["status"] == "completed_with_warnings" and again["errors"][0].startswith("skills row 1")


@pytest.mark.asyncio
async def test_history_lists_backups_and_restores_with_who_and_where_for_admins_only(client, db):
    admin_id = await make_user(db, admin=True)
    admin = await db.get(User, admin_id)
    project = Project(id=str(uuid.uuid4()), name=f"s10-hist-{uuid.uuid4().hex[:6]}", is_active=True, config={})
    db.add(project)
    await db.commit()
    project_id = project.id
    exported = await create_data_export_job(
        db, current_user=admin, export_type="admin_config_backup", scope_type="project", scope_id=project_id,
        format_name="json",
    )
    imported = await create_data_import_job(
        db, current_user=admin, import_type="admin_config_backup", source_format="json",
        payload_json=_backup("source", []), payload_text=None, target_project_id=project_id,
    )

    answer = await client.get("/api/v1/data/backups/history", headers=bearer(admin_id))
    assert answer.status_code == 200, answer.text
    rows = {row["id"]: row for row in answer.json()}
    backup, restore = rows[exported["id"]], rows[imported["id"]]
    assert (backup["kind"], backup["workspace"], backup["downloadable"]) == ("backup", project.name, True)
    assert restore["kind"] == "restore" and restore["workspace_id"] == project_id
    assert backup["by"] == restore["by"] == admin.username

    member = await make_user(db, admin=False)
    assert (await client.get("/api/v1/data/backups/history", headers=bearer(member))).status_code == 403
    listed = await client.get("/api/v1/data/imports", headers=bearer(member))
    assert listed.status_code == 200 and all(row["id"] != imported["id"] for row in listed.json())
    assert (await client.get(f"/api/v1/data/imports/{imported['id']}", headers=bearer(member))).status_code == 403
