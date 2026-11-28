"""A run's pull request asks a Workspace owner when its requester cannot review;
the rule is data (``pr_reviewers.json`` ``fallback_roles``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import UserLinkedAccount
from app.services.linked_accounts.resolution import scm_platform
from app.services.workflow_runs.platform import repo_ref, scm
from tests.knowledge_evidence_seed_support import seed_member
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_workflow_run_platform_actions import FakeTools, _item, _repository, _run

pytestmark = pytest.mark.usefixtures("scripted_pool")

CHAIN = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "branch", "type": "platform_action", "config": {"action": "scm.create_branch",
                                                                     "params": {"branch_type": "bugfix"}}},
              {"id": "push", "type": "platform_action", "config": {"action": "scm.push"}},
              {"id": "pr", "type": "platform_action", "config": {"action": "scm.open_pr"}},
              {"id": "ok", "type": "outcome", "config": {"outcome": "delivered"}},
              {"id": "ko", "type": "outcome", "config": {"outcome": "blocked"}}],
    "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "branch"},
              {"id": "2", "source_node_id": "branch", "target_node_id": "push", "when": "succeeded"},
              {"id": "3", "source_node_id": "branch", "target_node_id": "ko", "when": "failed"},
              {"id": "4", "source_node_id": "push", "target_node_id": "pr", "when": "succeeded"},
              {"id": "5", "source_node_id": "push", "target_node_id": "ko", "when": "failed"},
              {"id": "6", "source_node_id": "pr", "target_node_id": "ok", "when": "succeeded"},
              {"id": "7", "source_node_id": "pr", "target_node_id": "ko", "when": "failed"}],
}


def test_the_rule_is_data():
    data = json.loads((Path(scm.__file__).with_name("pr_reviewers.json")).read_text(encoding="utf-8"))
    assert data["fallback_roles"] == ["owner", "admin"]


@pytest.mark.asyncio
async def test_an_unlinked_requester_gets_the_workspace_owner_as_reviewer_and_the_description_says_so(db, monkeypatch):
    from tests.agent_definition_revision_fixtures import make_project

    tools = FakeTools(monkeypatch, {repo_ref.TOOLS["github"]["prepare"]: [{"local_path": "repos/payments"}],
                                    "create_github_pull_request": [{"number": 12, "html_url": "https://scm.test/pr/12",
                                                                    "status": "created", "reviewers_unresolved": []}]})
    project = await make_project(db)
    await admin_user(db)  # the requester: no linked GitHub account (as a service key's user)
    owner = await seed_member(db, workspace_id=project.id, role="owner")
    db.add(UserLinkedAccount(user_id=owner, platform=scm_platform("github"), username="anna-owner"))
    await db.flush()
    await _repository(db, project.id, "github", "payments", owners=["lead-dev"])
    item = await _item(db, project_id=project.id)
    run = await _run(db, CHAIN, work_item_id=item.id, project_id=project.id, repository="github:acme/payments")
    assert run.outcome == "delivered", run.context
    call = next(item[1] for item in tools.calls if item[0] == "create_github_pull_request")
    assert call["reviewers"] == ["anna-owner", "lead-dev"] and "requester" not in call
    assert "is asked to review it instead" in call["description"]
    assert run.pull_request["reviewers"] == ["anna-owner", "lead-dev"]


@pytest.mark.asyncio
async def test_without_a_linked_owner_or_admin_the_description_says_nobody_was_asked(db, monkeypatch):
    from tests.agent_definition_revision_fixtures import make_project

    tools = FakeTools(monkeypatch, {repo_ref.TOOLS["github"]["prepare"]: [{"local_path": "repos/payments"}],
                                    "create_github_pull_request": [{"number": 13, "html_url": "https://scm.test/pr/13",
                                                                    "status": "created", "reviewers_unresolved": []}]})
    project = await make_project(db)
    await admin_user(db)
    await seed_member(db, workspace_id=project.id, role="owner")
    await _repository(db, project.id, "github", "payments", owners=[])
    item = await _item(db, project_id=project.id)
    run = await _run(db, CHAIN, work_item_id=item.id, project_id=project.id, repository="github:acme/payments")
    call = next(item[1] for item in tools.calls if item[0] == "create_github_pull_request")
    assert call["reviewers"] == [] and "account is not linked" in call["description"]
    assert run.pull_request["reviewer_skipped"] == "requester_unresolved"
