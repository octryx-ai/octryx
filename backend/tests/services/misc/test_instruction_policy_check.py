"""A8 follow-up: an instruction naming a tool its scope's policy forbids gets a finding with the forbidding policy."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, User
from app.services.instructions import lifecycle, review
from app.services.instructions.policy_check import FINDING_CODE
from app.services.policy_engine import test_bench

FORBID_WEB_SEARCH = (
    '@id("no-web-search")\nforbid (principal, action == Action::"call_tool", resource)\n'
    'when { resource in [Tool::"web_search"] };\n'
)


async def _draft(db, *, body: str, project_id: str | None):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    _instruction, version = await lifecycle.create_instruction(
        db, key=f"policy.{uuid.uuid4().hex[:6]}", title="Policy check", scope_type="workspace" if project_id else "global",
        scope_id=project_id, workflow_key=None, body=body, change_note="", user=admin,
    )
    return admin, version


def _policy_findings(findings: list[dict]) -> list[dict]:
    return [item for item in findings if item["code"] == FINDING_CODE]


@pytest.mark.asyncio
async def test_a_tool_on_the_workspace_deny_list_is_forbidden_and_blocks_submit(db):
    project = Project(name=f"deny-{uuid.uuid4().hex[:6]}", config={"tool_policy": {"denylist": ["run_cli_command"]}},
                      is_active=True)
    db.add(project)
    await db.flush()
    admin, version = await _draft(db, body="Inspect the host with run_cli_command first.", project_id=project.id)

    findings = _policy_findings(await review.check_version(db, version_id=version.id))
    assert [(item["names"], item["kind"], item["policy"]) for item in findings] == [
        (["run_cli_command"], "tool_policy", "Tool policy deny list")
    ]
    with pytest.raises(lifecycle.InstructionRefusal) as refused:
        await review.submit_for_review(db, version_id=version.id, user=admin)
    assert refused.value.code == "instruction_conflicts"
    submitted = await review.submit_for_review(db, version_id=version.id, user=admin, accept_findings=True)
    assert submitted.state == "in_review"


@pytest.mark.asyncio
async def test_a_cedar_forbid_for_every_role_is_reported_with_the_policy(db, monkeypatch):
    async def published(_db, _source, _policies=None):
        return test_bench.CustomText(FORBID_WEB_SEARCH, "published version 1")

    monkeypatch.setattr(test_bench, "custom_text", published)
    _admin, version = await _draft(db, body="Search the web with web_search for vendor notes.", project_id=None)

    findings = _policy_findings(await review.check_version(db, version_id=version.id))
    assert len(findings) == 1 and findings[0]["names"] == ["web_search"]
    assert findings[0]["kind"] == "cedar" and "no-web-search" in findings[0]["policy"]


@pytest.mark.asyncio
async def test_an_allowed_tool_yields_no_policy_finding(db, monkeypatch):
    async def published(_db, _source, _policies=None):
        return test_bench.CustomText(FORBID_WEB_SEARCH, "published version 1")

    monkeypatch.setattr(test_bench, "custom_text", published)
    project = Project(name=f"allow-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    _admin, version = await _draft(db, body="Answer with knowledge_search and cite the sources.", project_id=project.id)

    assert _policy_findings(await review.check_version(db, version_id=version.id)) == []
