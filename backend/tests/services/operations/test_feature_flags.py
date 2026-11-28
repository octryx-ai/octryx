import pytest
from sqlalchemy import select

from app.models import Project
from app.services.feature_flag import delete_feature_flag, evaluate_feature_flag, upsert_feature_flag


@pytest.mark.asyncio
async def test_feature_flag_evaluation_respects_project_role_and_rollout(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    await upsert_feature_flag(
        db,
        payload={
            "key": "beta-feature",
            "description": "beta",
            "enabled": True,
            "rollout_percentage": 100,
            "allowed_projects": [project.id],
            "allowed_roles": ["admin"],
        },
    )

    enabled = await evaluate_feature_flag(db, key="beta-feature", current_user=auth_user, project_id=project.id)
    wrong_project = await evaluate_feature_flag(db, key="beta-feature", current_user=auth_user, project_id="other-project")

    assert enabled["enabled"] is True
    assert enabled["reason"] == "enabled"
    assert wrong_project["enabled"] is False
    assert wrong_project["reason"] == "project_not_allowed"


@pytest.mark.asyncio
async def test_feature_flag_identifiers_are_canonicalized_at_the_service_boundary(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    await upsert_feature_flag(
        db,
        payload={
            "key": "  scoped-rollout  ",
            "description": "scoped rollout",
            "enabled": True,
            "rollout_percentage": 100,
            "allowed_projects": [project.id],
            "allowed_roles": ["admin"],
        },
    )

    enabled = await evaluate_feature_flag(
        db,
        key="  scoped-rollout  ",
        current_user=auth_user,
        project_id=f" {project.id} ",
    )
    delete_resp = await delete_feature_flag(db, key="  scoped-rollout  ")
    after_delete = await evaluate_feature_flag(db, key="scoped-rollout", current_user=auth_user, project_id=project.id)

    assert enabled["enabled"] is True
    assert enabled["reason"] == "enabled"
    assert delete_resp["status"] == "deleted"
    assert delete_resp["key"] == "scoped-rollout"
    assert after_delete["enabled"] is False
    assert after_delete["reason"] == "not_found"


@pytest.mark.asyncio
async def test_feature_flag_allowed_roles_are_canonicalized_to_lowercase(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    saved = await upsert_feature_flag(
        db,
        payload={
            "key": "mixed-role-flag",
            "description": "mixed role casing",
            "enabled": True,
            "rollout_percentage": 100,
            "allowed_projects": [project.id],
            "allowed_roles": [" Admin ", "admin", "ADMIN"],
        },
    )

    enabled = await evaluate_feature_flag(db, key="mixed-role-flag", current_user=auth_user, project_id=project.id)

    assert enabled["enabled"] is True
    assert enabled["reason"] == "enabled"
    assert saved["allowed_roles"] == ["admin"]
    assert set(enabled) == {"key", "enabled", "reason"}  # the evaluation never carries the flag's allowlists


@pytest.mark.asyncio
async def test_feature_flag_admin_and_public_api(client, auth_headers):
    create_resp = await client.post(
        "/admin/chat/api/panel/feature-flags",
        json={
            "key": "ui-beta",
            "description": "ui rollout",
            "enabled": True,
            "rollout_percentage": 100,
            "allowed_projects": [],
            "allowed_roles": ["admin"],
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 200, create_resp.text

    list_resp = await client.get("/admin/chat/api/panel/feature-flags", headers=auth_headers)
    assert list_resp.status_code == 200
    assert any(row["key"] == "ui-beta" for row in list_resp.json())

    public_resp = await client.get("/api/v1/feature-flags/ui-beta", headers=auth_headers)
    assert public_resp.status_code == 200
    assert public_resp.json()["enabled"] is True
    assert public_resp.json()["reason"] == "enabled"

    delete_resp = await client.delete("/admin/chat/api/panel/feature-flags/ui-beta", headers=auth_headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_feature_flag_service_rejects_invalid_payload_types(db):
    with pytest.raises(ValueError, match="enabled must be a boolean"):
        await upsert_feature_flag(
            db,
            payload={
                "key": "typed-enabled",
                "enabled": "false",
            },
        )

    with pytest.raises(ValueError, match="allowed_roles entries must be strings"):
        await upsert_feature_flag(
            db,
            payload={
                "key": "typed-roles",
                "allowed_roles": ["admin", 1],
            },
        )


@pytest.mark.asyncio
async def test_feature_flag_service_normalizes_deduplicated_lists(db):
    row = await upsert_feature_flag(
        db,
        payload={
            "key": "dedupe-flag",
            "enabled": False,
            "allowed_projects": [" acme-orders ", "acme-orders", ""],
            "allowed_roles": "admin, admin, viewer, ",
        },
    )

    assert row["allowed_projects"] == ["acme-orders"]
    assert row["allowed_roles"] == ["admin", "viewer"]


@pytest.mark.asyncio
async def test_a_foreign_workspace_answers_the_flag_evaluation_like_an_unknown_one(client, db):
    import uuid

    from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
    from tests.policy_engine_support import bearer

    mine, foreign = await seed_workspace(db), await seed_workspace(db)
    member = await seed_member(db, workspace_id=mine, role="member")
    await upsert_feature_flag(db, payload={"key": "scoped-beta", "enabled": True, "rollout_percentage": 100,
                                           "allowed_projects": [foreign, mine], "allowed_roles": []})
    await db.commit()

    answers = []
    for workspace_id in (foreign, str(uuid.uuid4())):
        response = await client.get("/api/v1/feature-flags/scoped-beta", params={"project_id": workspace_id},
                                     headers=bearer(member))
        body = response.json()
        body.pop("request_id", None)
        answers.append((response.status_code, body))
    assert answers[0] == answers[1]
    assert answers[0][0] == 404 and answers[0][1]["detail"]["code"] == "project_not_found"

    own = await client.get("/api/v1/feature-flags/scoped-beta", params={"project_id": mine}, headers=bearer(member))
    assert own.status_code == 200, own.text
    assert own.json() == {"key": "scoped-beta", "enabled": True, "reason": "enabled"}
