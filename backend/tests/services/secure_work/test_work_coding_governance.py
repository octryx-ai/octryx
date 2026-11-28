"""Contract: coding governance in one place."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    Project,
    User,
    UserProject,
    WorkChangePlan,
    WorkCodingPipelineConfig,
    WorkItem,
)
from app.services.coding_policy_runtime import enforce_workspace_path_policy
from app.services.policy_engine.runtime import MODE_ENFORCE
from app.services.secure_work.coding.effective_rules import effective_rules
from app.services.secure_work.coding.pipeline_checks import normalize_checks, preview_pipeline_checks
from tests.policy_engine_support import use_custom_policies


async def _world(db) -> tuple[User, Project]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name=f"gov-{uuid.uuid4().hex[:6]}", config={
        "agent_gateway_policy": {"tool_rules": [{"id": "no-env", "kind": "path_denied", "tools": ["Edit", "Write"],
                                                 "glob": "*.env"}]},
        "approval_policy": {"require_for_risks": ["write"], "require_for_tools": ["merge_pull_request"]}})
    db.add(project)
    await db.commit()
    return admin, project


def _enforce(text: str) -> None:
    # As the published version installs it: the custom text together with its policy ids, so a custom forbid
    # counts as ``custom_policy`` in the shadow comparison, never as a mismatch.
    use_custom_policies(text, mode=MODE_ENFORCE)


async def _decide(db, admin, project, path):
    return await enforce_workspace_path_policy(db, user_id=admin.id, session_id=None, project_id=project.id,
                                               work_item_id=None, tool_name="edit_workspace_file", paths=[path])


async def test_edits_ask_the_tool_rules_and_the_published_policies(db):
    admin, project = await _world(db)
    _enforce(f'@id("prod-manifests")\nforbid (principal, action == Action::"write_path", resource)\n'
             f'when {{ context.workspace == Workspace::"{project.id}" && resource.path like "deploy/prod/*" }};\n')
    assert (await _decide(db, admin, project, "src/app.py"))["status"] == "allowed"
    rule = await _decide(db, admin, project, "config/.env")
    assert rule["status"] == "blocked" and rule["outcomes"][0]["policy_type"] == "workspace_tool_rule"
    cedar = await _decide(db, admin, project, "deploy/prod/app.yaml")
    assert cedar["status"] == "blocked" and cedar["outcomes"][0]["evidence"]["policy_ids"] == ["prod-manifests"]


async def test_pipeline_checks_and_effective_rules(db):
    admin, project = await _world(db)
    with pytest.raises(HTTPException):
        normalize_checks([{"type": "naming_contest"}])
    checks = normalize_checks([{"type": "pr_size_threshold", "effect": "review", "rule": {"max_changed_lines": 10}}])
    db.add(WorkCodingPipelineConfig(name="Delivery", project_id=project.id, stages_json=[], created_by=admin.id,
                                    controls_json={"checks": checks}))
    await db.commit()
    preview = await preview_pipeline_checks(db, current_user=admin, payload={"project_id": project.id, "changed_files": [
        {"path": "a.py", "additions": 40, "deletions": 0}]})
    assert [outcome["name"] for outcome in preview["outcomes"]] == ["PR size"]
    rules = await effective_rules(db, project.id)
    assert any(entry["source"] == "tool_rule" and entry["id"] == "no-env" for entry in rules["denied"])
    assert {"kind": "tool", "value": "merge_pull_request"} in rules["needs_approval"]["items"]
    assert rules["who_approves"]["edit"] == "approval_rule" and rules["checks"]["items"][0]["label"] == "PR size"


async def test_effective_rules_say_each_rule_once_with_its_parts_and_origin(db, monkeypatch):
    from types import SimpleNamespace

    from app.services.secure_work.coding import effective_rules as rules_module

    admin, project = await _world(db)
    project.config = {**project.config, "agent_gateway_policy": {"tool_rules": [
        {"id": "no-force-push", "kind": "command_argument_denied", "command": ["git", "push"], "argument": "--force"},
        {"id": "no-force-push-short", "kind": "command_argument_denied", "command": ["git", "push"], "argument": "-f"},
        {"id": "no-pem", "kind": "path_denied", "tools": ["Read", "Edit"], "glob": "**/*.pem"},
        {"id": "no-pem-again", "kind": "path_denied", "tools": ["Edit", "Read"], "glob": "**/*.pem"},
    ]}}
    await db.commit()
    generated = (f'@id("workspace:{project.id}:tool-rule:no-pem")\nforbid (principal, action == Action::"write_path", '
                 f'resource)\nwhen {{ context.workspace == Workspace::"{project.id}" && resource.path like "*.pem" }};\n')

    async def published_now(_db):
        return SimpleNamespace(version=7, policies_text=generated)

    monkeypatch.setattr(rules_module, "published", published_now)
    denied = (await effective_rules(db, project.id))["denied"]
    assert [entry["source"] for entry in denied] == ["tool_rule"] * 3, "the generated policy is not a second entry"
    force, short, pem = denied
    assert (force["kind"], force["command"], force["argument"], force["origin"]) == (
        "command_argument_denied", "git push", "--force", "baseline")
    assert force["title"] == "command argument denied: git push --force" and short["argument"] == "-f"
    assert pem["ids"] == ["no-pem", "no-pem-again"] and pem["tools"] == ["Edit", "Read"]
    assert (pem["glob"], pem["origin"], pem["published_version"]) == ("**/*.pem", "workspace", 7)
    assert force["published_version"] is None


async def test_the_preview_reads_a_change_plan_only_in_the_callers_workspaces(db):
    admin, project = await _world(db)
    foreign = Project(name=f"gov-{uuid.uuid4().hex[:6]}", config={})
    member = User(username=f"m-{uuid.uuid4().hex[:6]}", email=f"m-{uuid.uuid4().hex[:6]}@example.test", password_hash="x")
    db.add_all([foreign, member])
    await db.flush()
    items = [WorkItem(project_id=pid, source_type="manual", source_instance="gov", source_key=uuid.uuid4().hex[:8],
                      title="t") for pid in (project.id, foreign.id)]
    db.add_all([*items, UserProject(user_id=member.id, project_id=project.id, role="member", granted_by=admin.id)])
    await db.flush()
    plans = [WorkChangePlan(work_item_id=item.id, version=1, status="draft", title="p", created_by=admin.id)
             for item in items]
    db.add_all(plans)
    await db.commit()
    own, foreign_plan = plans
    assert "summary" in await preview_pipeline_checks(db, current_user=member, payload={"change_plan_id": own.id})
    for payload in ({"change_plan_id": foreign_plan.id}, {"work_item_id": items[1].id},
                    {"work_item_id": items[0].id, "change_plan_id": foreign_plan.id}):
        with pytest.raises(HTTPException) as refused:
            await preview_pipeline_checks(db, current_user=member, payload=payload)
        assert refused.value.status_code == 404, payload
    for workspace_id in (foreign.id, str(uuid.uuid4())):
        with pytest.raises(HTTPException) as refused:
            await preview_pipeline_checks(db, current_user=member, payload={"project_id": workspace_id})
        assert (refused.value.status_code, refused.value.detail["code"]) == (404, "project_not_found")
