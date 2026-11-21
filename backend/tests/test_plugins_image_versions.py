"""A new image upgrades, rolls back and switches off a plugin in every Workspace where it is on, and takes over a plugin installed by upload before."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, FlowDefinition, Project, User, UserProject
from app.services.plugins.package import files_from_folder
from tests.plugins_support import SHIPPED, _delivered, _in_image, _switch, _workspace_admin, uid
from tests.policy_engine_support import bearer


def _next_version(files: dict[str, bytes]) -> dict[str, bytes]:
    """1.2.0: release-notes says one more thing, release-readiness is no longer part of the plugin."""
    files = {path: data for path, data in files.items() if not path.startswith("skills/release-readiness/")}
    files["octryx-plugin.yaml"] = files["octryx-plugin.yaml"].replace(b"version: 1.1.0", b"version: 1.2.0").replace(
        b"skills: [skills/release-notes, skills/release-readiness]", b"skills: [skills/release-notes]")
    files["skills/release-notes/SKILL.md"] += b"\nAlways name the fix version in the title.\n"
    return files


async def _published(db, name: str) -> tuple[str, int | None]:
    from app.models import Skill
    from app.services.skill_catalog.lifecycle import published_version

    skill = (await db.execute(select(Skill).where(Skill.name == name))).scalar_one()
    version = await published_version(db, skill)
    return skill.id, version.version if version is not None else None


@pytest.mark.asyncio
async def test_a_new_image_upgrades_rolls_back_and_switches_off_every_workspace_where_the_plugin_is_on(
        client, db, tmp_path):
    """Image version = plugin version, a rollback is an image rollback; every Workspace where it is on moves along."""
    from app.models.runtime.plugin_install import PluginInstall
    from app.services.plugins.image import SERVICE_USERNAME, sync_image_plugins

    user, ours, other = await _workspace_admin(db)
    user_id, ours_id, other_id = user.id, ours.id, other.id
    admin_id = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    db.add(UserProject(user_id=user_id, project_id=other_id, role="admin", granted_by=user_id))
    third = Project(id=uid(), name=f"ws-{uid()[:6]}", is_active=True, config={})
    db.add(third)
    await db.commit()
    third_id = third.id
    folder = tmp_path / "plugins"
    shipped = files_from_folder(SHIPPED)
    (folder / "broken").mkdir(parents=True)
    (folder / "broken" / "octryx-plugin.yaml").write_text("id: Not A Plugin\n")

    from sqlalchemy.ext.asyncio import async_sessionmaker

    absent = await sync_image_plugins(async_sessionmaker(db.bind, expire_on_commit=False), tmp_path / "absent")
    assert absent.as_dict()["folder_exists"] is False  # absent ≠ empty: nothing changes
    first = await _in_image(db, folder, {"release-notes": shipped})
    assert first["release-notes"]["outcome"] == "available" and first["broken"]["outcome"] == "failed"
    part = (await db.execute(select(PluginInstall))).scalar_one()
    service = await db.get(User, part.installed_by)
    assert (part.scope, part.version, part.source_json["kind"]) == ("platform", "1.1.0", "image")
    assert (service.username, service.is_active) == (SERVICE_USERNAME, False)  # the image, not a person; no sign-in

    for workspace_id in (ours_id, other_id):
        assert (await _switch(client, user_id, "octryx.release-notes", workspace_id)).status_code == 200
    await _switch(client, user_id, "octryx.release-notes", other_id, on=False)  # an admin switched it off there
    notes_id, notes_version = await _published(db, "release-notes")
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == "release-notes",
                                                          FlowDefinition.project_id == ours_id))).scalar_one()
    flow_id, flow_version = flow.id, flow.current_version_id

    assert (await _in_image(db, folder, {}))["release-notes"]["outcome"] == "unchanged"

    upgraded = (await _in_image(db, folder, {"release-notes": _next_version(shipped)}))["release-notes"]
    assert (upgraded["outcome"], upgraded["from_version"], upgraded["version"], upgraded["workspaces"]) == (
        "upgraded", "1.1.0", "1.2.0", 2)
    rows = {row.scope_key: row for row in (await db.execute(select(PluginInstall))).scalars().all()}
    assert {row.version for row in rows.values()} == {"1.2.0"}
    assert (rows[ours_id].status, rows[other_id].status) == ("active", "disabled")  # off stays off
    assert await _published(db, "release-notes") == (notes_id, notes_version + 1)  # same skill, one new version
    assert (await _published(db, "release-readiness"))[1] is None  # dropped: retired, kept
    assert await _delivered(db, ours_id) == {"release-notes": ""}
    assert set((await _delivered(db, third_id)).values()) == {"plugin_not_installed_here"}
    assert (await db.get(FlowDefinition, flow_id)).current_version_id == flow_version  # unchanged: no new version
    assert [i["key"] for i in rows[ours_id].contributions_json if i["kind"] == "skill"] == ["release-notes"]

    rolled = (await _in_image(db, folder, {"release-notes": shipped}))["release-notes"]  # image rollback
    assert (rolled["outcome"], rolled["from_version"], rolled["version"]) == ("upgraded", "1.2.0", "1.1.0")
    assert await _delivered(db, ours_id) == {"release-notes": "", "release-readiness": ""}
    assert (await _published(db, "release-notes"))[0] == notes_id

    import shutil

    shutil.rmtree(folder / "release-notes")
    assert (await _in_image(db, folder, {}))["release-notes"]["outcome"] == "disabled"
    assert set((await _delivered(db, ours_id)).values()) == {"plugin_not_installed_here"}
    assert (await db.get(FlowDefinition, flow_id)).is_active is False
    listed = (await client.get("/api/v1/plugins/available", params={"workspace_id": ours_id},
                               headers=bearer(user_id))).json()["plugins"]
    assert [p["in_image"] for p in listed] == [False]

    assert (await _in_image(db, folder, {"release-notes": shipped}))["release-notes"]["outcome"] == "enabled"
    rows = {row.scope_key: row for row in (await db.execute(select(PluginInstall))).scalars().all()}
    assert (rows["platform"].status, rows[ours_id].status, rows[other_id].status) == ("active", "active",
                                                                                      "disabled")
    listed = (await client.get("/api/v1/plugins/available", headers=bearer(admin_id))).json()["plugins"]
    assert [p["active_workspaces"] for p in listed] == [1]  # live: on in ours, off in other
    actions = (await db.execute(select(AuditLog.action).where(AuditLog.action.like("plugins.%")))).scalars().all()
    assert actions.count("plugins.upgraded") == 6 and "plugins.disabled" in actions
