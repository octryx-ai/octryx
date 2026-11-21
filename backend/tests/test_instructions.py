"""A8: Instructions are bound explicitly, conflict-checked, published with four eyes, read in a fixed order.

- a turn reads exactly the published instructions its scope (global, Workspace, agent) and binding
  (always, or the selected workflow) select, in the order agent → Workspace → workflow;
- the conflict check names tools outside the bound workflow, changing tools in a read-only workflow,
  skill duplicates and an exceeded layer budget; findings block submit until accepted;
- publish needs the four-eyes approval; ``instruction_get`` reads one by exact key in scope only.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, Approval, Project, User
from app.services.instructions import lifecycle, review
from app.services.instructions.resolve import instruction_get, render_instructions_section, turn_instructions
from tests.phased_workflow_fixtures import phased_definition, publish_phased
from tests.prompt_catalog_publish_support import second_admin
from tests.skill_catalog.support import publish_chat_skill


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _workspace(db) -> Project:
    project = Project(name=f"instr-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    return project


async def _published(db, *, key: str, body: str, scope_type: str = "global", scope_id: str | None = None,
                     workflow_key: str | None = None, title: str | None = None):
    admin = await _admin(db)
    instruction, version = await lifecycle.create_instruction(
        db, key=key, title=title or key, scope_type=scope_type, scope_id=scope_id, workflow_key=workflow_key,
        body=body, change_note="", user=admin,
    )
    await review.submit_for_review(db, version_id=version.id, user=admin, accept_findings=True)
    approval = await db.get(Approval, version.approval_id)
    approval.status, approval.approved_by = "approved", (await second_admin(db)).id
    await review.publish(db, version_id=version.id, user=admin)
    return instruction


@pytest.mark.asyncio
async def test_a_turn_reads_exactly_its_scope_and_binding_in_the_fixed_order(db) -> None:
    workspace, other = await _workspace(db), await _workspace(db)
    admin = await _admin(db)
    agent = AgentDefinition(owner_id=admin.id, project_id=workspace.id, name="instr-agent")
    db.add(agent)
    await db.flush()
    await _published(db, key="zz.global", body="Global rule.")
    await _published(db, key="ws.rule", body="Workspace rule.", scope_type="workspace", scope_id=workspace.id)
    await _published(db, key="other.rule", body="Other Workspace.", scope_type="workspace", scope_id=other.id)
    await _published(db, key="agent.rule", body="Agent rule.", scope_type="agent", scope_id=agent.id)
    await _published(db, key="wf.rule", body="Workflow rule.", workflow_key="answer-docs")

    items = await turn_instructions(db, project_id=workspace.id, agent_definition_id=agent.id, workflow_key="answer-docs")
    keys = [item["key"] for item in items if item["key"] in {"zz.global", "ws.rule", "other.rule", "agent.rule", "wf.rule"}]
    assert keys == ["agent.rule", "ws.rule", "zz.global", "wf.rule"]
    without_workflow = await turn_instructions(db, project_id=workspace.id, agent_definition_id=None, workflow_key=None)
    assert "wf.rule" not in {item["key"] for item in without_workflow}
    section = render_instructions_section([item for item in items if item["key"] == "ws.rule"])
    assert section.startswith("## Instructions") and "### ws.rule v1" in section and "Workspace rule." in section

    assert (await instruction_get(db, key="ws.rule", project_id=workspace.id))["body"] == "Workspace rule."
    on_request = await lifecycle.create_instruction(
        db, key="fetch.only", title="x", scope_type="global", scope_id=None, workflow_key=None, body="Fetched.",
        change_note="", user=admin, binding="on_request",
    )
    assert on_request[0].binding == "on_request"
    assert await instruction_get(db, key="other.rule", project_id=workspace.id) is None


@pytest.mark.asyncio
async def test_the_conflict_check_blocks_submit_until_the_findings_are_accepted(db) -> None:
    await publish_phased(db, phased_definition(), key="answer-docs")  # read-only, offers knowledge_search
    admin = await _admin(db)
    # A published skill whose method text the instruction repeats.
    await publish_chat_skill(db, "release-notes-digest", approver_id=admin.id, description="Digest release notes.",
                             body="Search with knowledge_search, then edit_workspace_file and git_push.")
    await db.flush()
    _instruction, version = await lifecycle.create_instruction(
        db, key="wf.conflicts", title="Release notes digest", scope_type="global", scope_id=None,
        workflow_key="answer-docs", body="Search with knowledge_search, then edit_workspace_file and git_push.",
        change_note="", user=admin,
    )
    with pytest.raises(lifecycle.InstructionRefusal) as refused:
        await review.submit_for_review(db, version_id=version.id, user=admin)
    codes = {item["code"]: item["names"] for item in refused.value.facts["findings"]}
    assert "knowledge_search" not in codes["tool_not_in_workflow"]
    assert "edit_workspace_file" in codes["tool_not_in_workflow"]
    assert "edit_workspace_file" in codes["tool_against_capability"]
    assert codes["duplicates_skill"] == ["release-notes-digest"]

    submitted = await review.submit_for_review(db, version_id=version.id, user=admin, accept_findings=True)
    assert submitted.state == "in_review" and submitted.findings_accepted == 1
    with pytest.raises(lifecycle.InstructionRefusal) as unapproved:
        await review.publish(db, version_id=version.id, user=admin)
    assert unapproved.value.code == "governance_approval_required"

    big = await lifecycle.create_draft(db, instruction_id=version.instruction_id, body="word " * 2000, change_note="",
                                       user=admin)
    findings = await review.check_version(db, version_id=big.id)
    assert any(item["code"] == "over_budget" for item in findings)


@pytest.mark.asyncio
async def test_the_admin_api_creates_checks_and_lists(client, auth_headers, db) -> None:
    created = await client.post("/api/v1/instructions", headers=auth_headers, json={
        "key": "api.rule", "title": "API rule", "scope_type": "global", "body": "Be brief.",
    })
    assert created.status_code == 201, created.text
    version_id = created.json()["latest"]["id"]
    conflicts = await client.get(f"/api/v1/instructions/versions/{version_id}/conflicts", headers=auth_headers)
    assert conflicts.json() == {"findings": []}
    submitted = await client.post(f"/api/v1/instructions/versions/{version_id}/submit", headers=auth_headers, json={})
    assert submitted.json()["state"] == "in_review"
    listed = await client.get("/api/v1/instructions", headers=auth_headers)
    assert "api.rule" in {item["key"] for item in listed.json()["items"]}
    invalid = await client.post("/api/v1/instructions", headers=auth_headers, json={
        "key": "Bad Key", "title": "x", "body": "x",
    })
    assert invalid.json()["detail"]["code"] == "instruction_key_invalid"
