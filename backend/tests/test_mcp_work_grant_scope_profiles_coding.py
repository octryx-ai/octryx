"""Repository profiles, the grant audit and coding start honour the grant's project binding."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, WorkItemChangeUnit, WorkItemWorkflowDefinition, WorkRepositoryProfile
from app.models.runtime.code_intelligence import CodeRepository
from app.services import mcp_secure_work_tools, mcp_work_targets
from tests.mcp_native_support import mcp_call, native_token
from tests.mcp_work_grant_scope_support import WORK_SCOPES, _error_text, _item, _snapshot, spies, world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _profiles(db, world) -> dict[str, str]:  # noqa: F811
    def _repo(project_id):
        return CodeRepository(project_id=project_id, name=f"repo-{uuid.uuid4().hex[:6]}", repo_root="/tmp/repo")

    repos = {"a": _repo(world.a), "b": _repo(world.b), "global": _repo(None)}
    db.add_all(repos.values())
    await db.flush()

    def _profile(project_id, repository=None):
        return WorkRepositoryProfile(
            project_id=project_id,
            code_repository_id=repository.id if repository else None,
            name=f"profile-{uuid.uuid4().hex[:6]}",
            created_by=world.admin.id,
        )

    profiles = {
        "own": _profile(world.a),
        "own_repo": _profile(world.a, repos["a"]),
        "global": _profile(None),
        "global_own_repo": _profile(None, repos["a"]),
        "global_global_repo": _profile(None, repos["global"]),
        "foreign": _profile(world.b),
        "global_foreign_repo": _profile(None, repos["b"]),
        "own_foreign_repo": _profile(world.a, repos["b"]),
    }
    db.add_all(profiles.values())
    await db.commit()
    return {name: row.id for name, row in profiles.items()}


# --- Coding start: indirect targets (root start-secondary review) ---------------------------------


async def _only_active_workflow(db, keep: str | None) -> None:
    """Deactivate every workflow but ``keep`` (``None``: no active workflow at all)."""
    for row in (await db.execute(select(WorkItemWorkflowDefinition))).scalars():
        row.is_active = row.id == keep
    await db.commit()


def _coding_start_recorder(monkeypatch) -> list[dict]:
    started: list[dict] = []

    async def _start(_db, *, work_item_id, payload, **_kwargs):
        started.append({"work_item_id": work_item_id, "change_unit_ids": list(payload.get("change_unit_ids") or [])})
        return {"status": "started"}

    monkeypatch.setattr(mcp_secure_work_tools, "start_work_item_coding_agent_execution", _start)
    return started


async def _unit(db, world, profile_id: str | None, name: str) -> str:  # noqa: F811
    unit = WorkItemChangeUnit(
        work_item_id=world.items["a"].id,
        repository_profile_id=profile_id,
        repository_name=name,
        branch_name=f"feature/{name}",
        created_by=world.member.id,
    )
    db.add(unit)
    await db.commit()
    return unit.id


async def test_foreign_repository_profiles_never_replace_existing_units(world, spies):  # noqa: F811
    db, member = world.db, world.member
    item_a = world.items["a"]
    profiles = await _profiles(db, world)
    db.add(
        WorkItemChangeUnit(
            work_item_id=item_a.id, repository_name="existing", branch_name="feature/existing", created_by=member.id
        )
    )
    await db.commit()
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    before = await _snapshot(db)
    for units in (
        [{"repository_profile_id": profiles["foreign"]}],
        [{"repository_profile_id": profiles["global_foreign_repo"]}],
        [{"repository_profile_id": profiles["own_foreign_repo"]}],
        [{"repository_profile_id": profiles["own"]}, {"repository_profile_id": profiles["foreign"]}],
        [{"repository_profile_id": str(uuid.uuid4())}],
    ):
        text = _error_text(await mcp_call(token, "change_units_plan", {"work_item": item_a.id, "units": units}))
        # Foreign, foreign-wrapping and unknown profiles all read like a missing one.
        assert "404: Repository profile not found" in text, units
    assert spies == []
    assert await _snapshot(db) == before
    names = (
        (
            await db.execute(
                select(WorkItemChangeUnit.repository_name).where(WorkItemChangeUnit.work_item_id == item_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert names == ["existing"]


async def test_own_and_global_repository_profiles_stay_usable(world):  # noqa: F811
    db, member = world.db, world.member
    item_a = world.items["a"]
    profiles = await _profiles(db, world)
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    for name in ("own", "own_repo", "global", "global_own_repo", "global_global_repo"):
        result = await mcp_call(
            token, "change_units_plan", {"work_item": item_a.id, "units": [{"repository_profile_id": profiles[name]}]}
        )
        assert not result.get("isError"), (name, result)
        assert [unit["repository_profile_id"] for unit in result["units"]] == [profiles[name]]


async def test_audit_keeps_unrestricted_empty_bound_and_unresolved_grants_apart(world):  # noqa: F811
    db, member = world.db, world.member
    missing = {"work_item": "OCX-GRANT-MISSING"}
    cases = (
        ("unrestricted", None, None),
        ("empty", [], None),
        ("bound", [world.b, world.a], ",".join(sorted([world.a, world.b]))),
        ("unresolved", world.a, None),  # malformed binding: refused before a scope exists
    )
    for mode, project_ids, audit_project in cases:
        token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=project_ids)
        assert (await mcp_call(token, "work_item_find", missing)).get("isError")
        row = (
            await db.execute(
                select(AuditLog.details)
                .where(AuditLog.resource_type == "mcp_knowledge")
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
        assert row["grant_scope"]["binding_mode"] == mode, row
        assert row["api_key_project_id"] == audit_project
        assert "token" not in str(row["grant_scope"]).lower()
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    await mcp_call(token, "work_item_find", missing)
    bound_scope = (
        await db.execute(
            select(AuditLog.details)
            .where(AuditLog.resource_type == "mcp_knowledge")
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one()["grant_scope"]
    assert bound_scope == {
        "binding_mode": "bound",
        "binding_count": 1,
        "binding_project_ids": [world.a],
        "item_scope": {"count": 1},
    }


async def test_coding_start_refuses_a_foreign_default_lifecycle_workflow(world, spies, monkeypatch):  # noqa: F811
    db, member = world.db, world.member
    await _only_active_workflow(db, world.workflows["b"])
    # The resolver never picks another Workspace's workflow; a foreign result is still refused (defense in depth).
    assert await mcp_work_targets.default_workflow_for_item(db, world.items["a"]) is None

    async def _foreign_default(_db, _item):  # noqa: F811
        return await _db.get(WorkItemWorkflowDefinition, world.workflows["b"])

    monkeypatch.setattr(mcp_work_targets, "default_workflow_for_item", _foreign_default)
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    before = await _snapshot(db)
    text = _error_text(await mcp_call(token, "coding_agent_start", {"work_item": world.items["a"].id}))
    assert "Default lifecycle workflow is not available" in text
    assert spies == []
    assert await _snapshot(db) == before


async def test_coding_start_keeps_no_default_skip_and_own_or_global_defaults(world, monkeypatch):  # noqa: F811
    db, member = world.db, world.member
    started = _coding_start_recorder(monkeypatch)
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    for keep in (None, world.workflows["a"], world.workflows["global"]):
        await _only_active_workflow(db, keep)
        result = await mcp_call(token, "coding_agent_start", {"work_item": world.items["a"].id})
        assert not result.get("isError"), (keep, result)
    assert [row["work_item_id"] for row in started] == [world.items["a"].id] * 3


async def test_coding_start_refuses_stored_foreign_profiles_on_the_selected_units(world, spies):  # noqa: F811
    db, member = world.db, world.member
    profiles = await _profiles(db, world)
    own_unit = await _unit(db, world, profiles["own_repo"], "own")
    foreign_units = [
        await _unit(db, world, profiles[name], name) for name in ("foreign", "global_foreign_repo", "own_foreign_repo")
    ]
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    before = await _snapshot(db)
    selections = [[unit_id] for unit_id in foreign_units] + [[own_unit, foreign_units[0]], []]
    for change_unit_ids in selections:  # ``[]``: the native default selects every active unit
        arguments = {"work_item": world.items["a"].id, "change_unit_ids": change_unit_ids}
        text = _error_text(await mcp_call(token, "coding_agent_start", arguments))
        assert "repository profile is not available" in text, change_unit_ids
    assert spies == []
    assert await _snapshot(db) == before


async def test_coding_start_follows_the_native_unit_selection(world, monkeypatch):  # noqa: F811
    db, member = world.db, world.member
    profiles = await _profiles(db, world)
    usable = [await _unit(db, world, profiles[name], name) for name in ("own", "global_global_repo", "global_own_repo")]
    usable.append(await _unit(db, world, None, "no-profile"))
    foreign_unit = await _unit(db, world, profiles["foreign"], "foreign")
    started = _coding_start_recorder(monkeypatch)
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    # Selecting only usable units starts although a foreign unit exists on the item.
    result = await mcp_call(token, "coding_agent_start", {"work_item": world.items["a"].id, "change_unit_ids": usable})
    assert not result.get("isError"), result
    assert started == [{"work_item_id": world.items["a"].id, "change_unit_ids": usable}]
    # A foreign unit id of another item is not selected by the native selector, so it cannot block.
    item_b_unit = WorkItemChangeUnit(
        work_item_id=world.items["b"].id,
        repository_profile_id=profiles["foreign"],
        repository_name="b-unit",
        branch_name="feature/b",
        created_by=member.id,
    )
    db.add(item_b_unit)
    await db.commit()
    result = await mcp_call(
        token, "coding_agent_start", {"work_item": world.items["a"].id, "change_unit_ids": [usable[0], item_b_unit.id]}
    )
    assert not result.get("isError"), result
    assert foreign_unit not in started[-1]["change_unit_ids"]


async def test_blank_project_id_is_not_the_global_marker(world, spies):  # noqa: F811
    db, member = world.db, world.member
    blank_workflow = WorkItemWorkflowDefinition(name="blank-owner", project_id="", created_by=world.admin.id)
    blank_profile = WorkRepositoryProfile(name="blank-owner", project_id="", created_by=world.admin.id)
    db.add_all([blank_workflow, blank_profile])
    await db.commit()
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    item_a = world.items["a"].id
    generate = {"work_item": item_a, "payload": {"workflow_id": blank_workflow.id}}
    assert "404: Workflow definition not found" in _error_text(await mcp_call(token, "change_plan_generate", generate))
    units = {"work_item": item_a, "units": [{"repository_profile_id": blank_profile.id}]}
    assert "404: Repository profile not found" in _error_text(await mcp_call(token, "change_units_plan", units))
    assert spies == []
