"""Secure-work family rows across two Workspaces, served by the real routers; the operator is a member of A only.
``world`` is the fixture; a test module imports it by name."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.policy.coding_governance import router as coding_governance_router
from app.api.routes.secure_work.secure_work import router as secure_work_router
from app.api.routes.secure_work.secure_work_workflows import router as workflows_router
from app.db import get_db
from app.models import (
    Project,
    User,
    UserProject,
    WorkCicdBuild,
    WorkCicdPipelineTrace,
    WorkCicdProviderConfig,
    WorkCodingPipelineConfig,
    WorkCodingPolicy,
    WorkItem,
    WorkItemChangeUnit,
    WorkRepositoryProfile,
    WorkTechnologyBaseline,
)
from app.services.auth import get_current_user
from tests.jira_task_list_support import _operator

FAMILIES = {
    "coding-pipelines": WorkCodingPipelineConfig,
    "coding-policies": WorkCodingPolicy,
    "cicd-providers": WorkCicdProviderConfig,
    "technology-baselines": WorkTechnologyBaseline,
    "repository-profiles": WorkRepositoryProfile,
}


def _row(model, name: str, project_id: str | None, admin_id: str, **extra):
    fields = {"name": name, "project_id": project_id, "created_by": admin_id, **extra}
    if model is WorkCicdProviderConfig:
        fields.setdefault("base_url", "https://ci.example.test")
        fields.setdefault("credential_ref", "secret-cred-ref")
    return model(**fields)


@pytest.fixture
async def world(db):
    app = FastAPI()
    for router in (workflows_router, secure_work_router, coding_governance_router):
        app.include_router(router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    a, b = Project(name=f"a-{uuid.uuid4().hex[:6]}", config={}), Project(name=f"b-{uuid.uuid4().hex[:6]}", config={})
    db.add_all([a, b])
    await db.flush()
    operator = await _operator(db)
    db.add(UserProject(user_id=operator.id, project_id=a.id, role="admin"))
    item_a = WorkItem(project_id=a.id, source_type="jira", source_instance=f"t-{uuid.uuid4().hex[:6]}",
                      source_key="AAA-1", title="AAA-1", work_state="intake", sync_state="imported")
    item_b = WorkItem(project_id=b.id, source_type="jira", source_instance=f"t-{uuid.uuid4().hex[:6]}",
                      source_key="BBB-1", title="BBB-1", work_state="intake", sync_state="imported")
    db.add_all([item_a, item_b])
    rows = {}
    for slug, model in FAMILIES.items():
        rows[slug] = {
            "a": _row(model, f"own-{slug}", a.id, admin.id),
            "b": _row(model, f"secret-{slug}", b.id, admin.id),
            "global": _row(model, f"global-{slug}", None, admin.id),
        }
        db.add_all(rows[slug].values())
    await db.flush()
    build_b = WorkCicdBuild(work_item_id=item_b.id, provider_config_id=rows["cicd-providers"]["b"].id,
                            job_name="b", build_number="1", created_by=admin.id)
    trace_b = WorkCicdPipelineTrace(work_item_id=item_b.id, provider_config_id=rows["cicd-providers"]["b"].id,
                                    job_name="b", created_by=admin.id)
    unit_b = WorkItemChangeUnit(work_item_id=item_b.id, repository_name="secret", branch_name="b", created_by=admin.id)
    db.add_all([build_b, trace_b, unit_b])
    await db.commit()
    state["user"] = operator
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sw.test") as client:
        yield {"api": client, "state": state, "a": a.id, "b": b.id, "item_a": item_a.id, "rows": rows,
               "build_b": build_b.id, "trace_b": trace_b.id, "unit_b": unit_b.id, "admin": admin}
