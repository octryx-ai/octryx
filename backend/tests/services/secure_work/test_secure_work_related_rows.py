"""The one scoped loader of Secure Work related rows and the handlers that consume related rows through it."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    Project,
    UserProject,
    WorkChangePlan,
    WorkCicdProviderConfig,
    WorkCodingPipelineConfig,
    WorkItem,
    WorkItemChangeUnit,
    WorkItemWorkflowDefinition,
    WorkRepositoryProfile,
)
from app.services.secure_work.related_rows import (
    CHANGE_PLAN,
    CICD_PROVIDER,
    PIPELINE_CONFIG,
    PIPELINE_TRACE,
    REPOSITORY_PROFILE,
    WORKFLOW,
    load_optional_related,
    load_related,
)
from tests.api.test_secure_work_workspace_scope import API, _admin, _member_of_own, api  # noqa: F401 - the fixture
from tests.support.workspace_resource_rows import seed_resource
from tests.workspace_id_route_inventory import changed, snapshot

MARKER = "related-foreign"
FAMILIES = [REPOSITORY_PROFILE, WORKFLOW, PIPELINE_CONFIG, CICD_PROVIDER, PIPELINE_TRACE, CHANGE_PLAN]
WORKSPACE_FAMILIES = {WorkRepositoryProfile, WorkItemWorkflowDefinition, WorkCodingPipelineConfig,
                      WorkCicdProviderConfig}


async def _foreign_workspace(db) -> str:
    return (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one().id


async def _refusal(call) -> tuple[int, object]:
    with pytest.raises(HTTPException) as refused:
        await call
    return refused.value.status_code, refused.value.detail


@pytest.mark.parametrize("family", FAMILIES, ids=[family.model.__name__ for family in FAMILIES])
async def test_foreign_and_missing_rows_answer_alike_and_the_own_row_loads(db, family):
    foreign_ws = await _foreign_workspace(db)
    admin = await _admin(db)
    foreign = await seed_resource(db, family.model, workspace_id=foreign_ws, user_id=admin.id, marker=MARKER)
    await db.commit()
    viewer, own_ws = await _member_of_own(db)
    own = await seed_resource(db, family.model, workspace_id=own_ws, user_id=viewer.id, marker="own")
    await db.commit()

    answers = [await _refusal(load_related(db, viewer, family, row_id)) for row_id in (foreign, str(uuid.uuid4()))]
    assert answers[0] == answers[1] == (404, family.missing)
    assert MARKER not in str(answers[0])
    assert (await load_related(db, viewer, family, own)).id == own
    assert (await load_related(db, viewer, family, own, for_workspace=own_ws)).id == own
    assert await load_optional_related(db, viewer, family, None) is None
    assert (await load_related(db, admin, family, foreign)).id == foreign


@pytest.mark.parametrize("family", FAMILIES, ids=[family.model.__name__ for family in FAMILIES])
async def test_an_authorized_row_of_another_workspace_is_the_mismatch_answer(db, family):
    viewer, own_ws = await _member_of_own(db)
    second = Project(name=f"second-{uuid.uuid4().hex[:6]}", config={})
    db.add(second)
    await db.commit()
    db.add(UserProject(user_id=viewer.id, project_id=second.id, role="admin"))
    await db.commit()
    other = await seed_resource(db, family.model, workspace_id=second.id, user_id=viewer.id, marker="second")
    await db.commit()

    assert (await load_related(db, viewer, family, other)).id == other, "visible without a target Workspace"
    answer = await _refusal(load_related(db, viewer, family, other, for_workspace=own_ws))
    assert answer == (family.mismatch_status, family.mismatch_detail)
    assert answer[0] != 404


@pytest.mark.parametrize("family", [family for family in FAMILIES if family.model in WORKSPACE_FAMILIES],
                         ids=lambda family: family.model.__name__)
async def test_a_global_row_loads_for_every_workspace(db, family):
    viewer, own_ws = await _member_of_own(db)
    row_id = await seed_resource(db, family.model, workspace_id=own_ws, user_id=viewer.id, marker="global")
    row = await db.get(family.model, row_id)
    row.project_id = None
    await db.commit()

    assert (await load_related(db, viewer, family, row_id, for_workspace=own_ws)).id == row_id
    assert (await load_related(db, viewer, family, row_id, for_workspace=None)).id == row_id


@pytest.mark.parametrize("family", [family for family in FAMILIES if family.model not in WORKSPACE_FAMILIES],
                         ids=lambda family: family.model.__name__)
async def test_a_row_of_an_item_without_a_workspace_is_admin_only(db, family):
    admin = await _admin(db)
    viewer, own_ws = await _member_of_own(db)
    row_id = await seed_resource(db, family.model, workspace_id=own_ws, user_id=admin.id, marker=MARKER)
    item = await db.get(WorkItem, (await db.get(family.model, row_id)).work_item_id)
    item.project_id = None
    await db.commit()

    assert await _refusal(load_related(db, viewer, family, row_id)) == (404, family.missing)
    assert (await load_related(db, admin, family, row_id, for_workspace=own_ws)).id == row_id


async def _foreign_row(db, model) -> str:
    admin = await _admin(db)
    row_id = await seed_resource(db, model, workspace_id=await _foreign_workspace(db), user_id=admin.id,
                                 marker=MARKER)
    await db.commit()
    return row_id


async def _same_answers(client, db, method: str, path: str, bodies: list[dict]) -> None:
    before = await snapshot(db)
    answers = [await client.request(method, f"{API}{path}", json=body) for body in bodies]
    assert changed(before, await snapshot(db)) == [], path
    assert answers[0].status_code == answers[1].status_code == 404, answers[0].text
    assert answers[0].json() == answers[1].json()
    assert MARKER not in answers[0].text


async def test_handlers_answer_foreign_related_rows_like_missing_ones(api, db):  # noqa: F811
    client, state = api
    profile = await _foreign_row(db, WorkRepositoryProfile)
    workflow = await _foreign_row(db, WorkItemWorkflowDefinition)
    plan = await _foreign_row(db, WorkChangePlan)
    operator, own_ws = await _member_of_own(db)
    item_id = str(uuid.uuid4())
    db.add(WorkItem(id=item_id, project_id=own_ws, source_type="jira", source_instance="t", source_key="OWN-R1",
                    title="own", work_state="intake", sync_state="imported"))
    await db.flush()
    db.add(WorkItemChangeUnit(work_item_id=item_id, repository_name="kept", branch_name="b", dependency_order="0",
                              created_by=operator.id, status="planned"))
    await db.commit()
    await db.refresh(operator)
    state["user"] = operator
    missing = str(uuid.uuid4())

    await _same_answers(client, db, "POST", f"/work-items/{item_id}/change-units/plan", [
        {"units": [{"repository_name": "r", "repository_profile_id": value}]} for value in (profile, missing)])
    await _same_answers(client, db, "POST", f"/work-items/{item_id}/change-plans/generate",
                        [{"workflow_id": value} for value in (workflow, missing)])
    await _same_answers(client, db, "POST", "/coding-pipelines/checks/preview",
                        [{"change_plan_id": value} for value in (plan, missing)])
    units = (await db.execute(select(WorkItemChangeUnit).where(WorkItemChangeUnit.work_item_id == item_id)))
    assert [unit.repository_name for unit in units.scalars()] == ["kept"]


async def test_the_pipeline_check_plan_binds_the_named_workspace(api, db):  # noqa: F811
    client, state = api
    viewer, own_ws = await _member_of_own(db)
    state["user"] = viewer
    plan_id = await seed_resource(db, WorkChangePlan, workspace_id=own_ws, user_id=viewer.id, marker="own")
    second = Project(name=f"second-{uuid.uuid4().hex[:6]}", config={})
    db.add(second)
    await db.commit()
    db.add(UserProject(user_id=viewer.id, project_id=second.id, role="admin"))
    await db.commit()

    own = await client.post(f"{API}/coding-pipelines/checks/preview", json={"change_plan_id": plan_id})
    assert own.status_code == 200, own.text
    bound = await client.post(f"{API}/coding-pipelines/checks/preview",
                              json={"change_plan_id": plan_id, "project_id": second.id})
    assert bound.status_code == 422 and "Workspace" in bound.json()["detail"]
