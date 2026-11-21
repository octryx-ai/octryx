"""One placeholder vocabulary for branch naming rules: ``{type}``, ``{key}``, ``{slug}``.

- unknown names in braces are not placeholders: their braces are dropped;
- Work planning and workflow runs name the same branch from the same rule; the default is ``{type}/{key}-{slug}``.
"""

from __future__ import annotations

import uuid

import pytest

from app.models import CodeRepository, WorkflowRun
from app.models.runtime.secure_work import WorkItem, WorkRepositoryProfile
from app.services.secure_work.plans.repository_planning import normalized_profile_payload, suggest_branch_name
from app.services.source_control.branch_naming import DEFAULT_BRANCH_RULE, render_branch
from app.services.workflow_runs.platform import repo_ref
from tests.agent_definition_revision_fixtures import make_project


def test_placeholders_render_and_unknown_braces_are_dropped():
    assert DEFAULT_BRANCH_RULE == "{type}/{key}-{slug}"
    for rule in ("feature/{key}-{slug}", "{type}/{key}-{slug}", ""):
        assert render_branch(rule, branch_type="feature", key="PAY-1", slug="totals") == "feature/PAY-1-totals"
    assert render_branch("{type}//{team}/{key}", branch_type="bugfix", key="PAY-1", slug="x") == "bugfix/team/PAY-1"


@pytest.mark.parametrize("rule", ["feature/{key}-{slug}", "{type}/{key}-{slug}", None])
async def test_work_planning_and_workflow_runs_name_the_same_branch(db, rule):
    project = await make_project(db)
    db.add(CodeRepository(project_id=project.id, provider="github", name="payments", is_active=True,
                          repo_root="/srv/repos",
                          config_json={"coding_setup": {"branch_naming_rule": rule} if rule else {}}))
    item = WorkItem(source_type="jira", source_instance="t", source_key="PAY-1", source_project_key="PAY",
                    title="Totals", project_id=project.id, work_state="development")
    db.add(item)
    await db.flush()
    run = WorkflowRun(project_id=project.id, ticket_key="PAY-1", work_item_id=item.id, title="Totals",
                      repository="github:acme/payments", requested_by=str(uuid.uuid4()))
    from_run = await repo_ref.branch_name(db, run, repo_ref.parse_repository(run.repository), "feature")
    profile = WorkRepositoryProfile(name="payments", branch_naming_rule=rule) if rule else None
    assert from_run == "feature/PAY-1-totals" and suggest_branch_name(item, profile) == "feature/PAY-1-totals"


async def test_a_platform_work_item_names_the_branch_and_pull_request_with_its_own_key(db):
    """A run on a platform Work item has no Jira ticket; its own key names the branch, commit and PR."""
    project = await make_project(db)
    item = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-24", title="Trip and member API",
                    project_id=project.id, work_state="intake")
    db.add(item)
    await db.flush()
    run = WorkflowRun(project_id=project.id, work_item_id=item.id, title="Trip and member API",
                      repository="github:acme/packmate", requested_by=str(uuid.uuid4()))
    assert repo_ref.work_key(run, item) == "OCX-24"
    assert await repo_ref.branch_name(db, run, repo_ref.parse_repository(run.repository), "feature") == (
        "feature/OCX-24-trip-and-member-api")
    jira_item = WorkItem(source_type="manual", source_instance="m", source_key="M-1", title="x")
    assert repo_ref.work_key(run, jira_item) == ""  # only the platform's own keys stand in for a ticket


async def test_a_saved_rule_is_stored_as_written(db):
    saved = await normalized_profile_payload(db, {"name": "payments", "branch_naming_rule": " {type}/{key} "})
    assert saved["branch_naming_rule"] == "{type}/{key}"
    assert (await normalized_profile_payload(db, {"name": "payments"}))["branch_naming_rule"] == DEFAULT_BRANCH_RULE
