"""A repository record without a default branch shows its Knowledge source's branch (octryx/kitchen-helper: main,
SHOP/demo-shop: master), and the cost report names workflows by their title."""

from __future__ import annotations

import uuid

import pytest

from app.models import CodeRepository, FlowDefinition, KnowledgeSourceConnector, Project
from app.services.operations.costs import _labels
from app.services.secure_work.repositories.record import workspace_repositories


def uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_a_record_without_a_branch_shows_its_sources_branch(db):
    project = Project(id=uid(), name="Kitchen helper", is_active=True, config={})
    db.add(project)
    await db.flush()
    own = KnowledgeSourceConnector(project_id=project.id, connector_key="bitbucket-shop-demo-shop",
                                   kind="git_repository", scope={
                                       "remote": "https://scm.example.test/bitbucket/projects/SHOP/repos/demo-shop",
                                       "ref": "master"})
    by_remote = KnowledgeSourceConnector(project_id=project.id, connector_key="kitchen-helper", kind="git_repository",
                                         scope={"remote": "https://bitbucket.org/octryx/kitchen-helper", "ref": "main"})
    db.add_all([own, by_remote])
    await db.flush()
    demo_shop = CodeRepository(project_id=project.id, name="bitbucket/projects/SHOP/repos/demo-shop", repo_root="/c/z",
                           provider="knowledge_snapshot", config_json={"central_source": {"connector_id": own.id}})
    kitchen_helper = CodeRepository(project_id=project.id, name="octryx/kitchen-helper", repo_root="/c/m",
                            provider="knowledge_snapshot", config_json={})
    pinned = CodeRepository(project_id=project.id, name="octryx/other", repo_root="/c/o", provider="bitbucket",
                            default_branch="develop", config_json={})
    lonely = CodeRepository(project_id=project.id, name="octryx/lonely", repo_root="/c/l", provider="bitbucket",
                            config_json={})
    db.add_all([demo_shop, kitchen_helper, pinned, lonely])
    await db.flush()

    rows = {row["name"]: row for row in await workspace_repositories(db, project.id)}

    assert (rows["bitbucket/projects/SHOP/repos/demo-shop"]["default_branch"],
            rows["bitbucket/projects/SHOP/repos/demo-shop"]["default_branch_from"]) == ("master", "knowledge_source")
    assert rows["octryx/kitchen-helper"]["default_branch"] == "main"
    assert rows["octryx/other"]["default_branch"] == "develop" and "default_branch_from" not in rows["octryx/other"]
    assert rows["octryx/lonely"]["default_branch"] is None


@pytest.mark.asyncio
async def test_cost_groups_name_workflows_by_their_title(db, auth_user):
    key = f"feature-delivery-tdd-{uid()[:6]}"
    db.add(FlowDefinition(key=key, name="Feature delivery (TDD)", created_by=auth_user.id))
    await db.flush()

    labels = await _labels(db, "workflow", {key, "unknown-flow"}, [])

    assert labels == {key: "Feature delivery (TDD)", "unknown-flow": "unknown-flow"}
