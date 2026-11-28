"""Platform chat delivery — skill_search/skill_get read published catalog versions."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, SkillUsageEvent, User
from app.services.skill_catalog.bundle import BundleFile
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.policy_engine_support import bearer
from tests.skill_catalog.support import BASE, category, draft_skill, published_skill, skill_md


def _context(db, user: User, project_id: str | None = None, roles: list[str] | None = None) -> ToolContext:
    return ToolContext(user_id=user.id, project_ids=[project_id] if project_id else [], roles=roles or ["admin"],
                       session_id=str(uuid.uuid4()), project_config={"project_id": project_id} if project_id else {},
                       current_user_message="", db=db, turn_context_snapshot={"tool_names": ["skill_search"]})


FILES = [BundleFile("SKILL.md", skill_md("chart-review", "Review Helm charts.", "\n# Chart review\n\n## Steps\n")),
         BundleFile("references/checklist.md", "# Checklist\n- values documented\n"),
         BundleFile("scripts/lint.sh", "#!/bin/sh\nhelm lint .\n", True)]


@pytest.mark.asyncio
async def test_search_and_get_deliver_the_published_version_with_references_but_never_scripts(client, db, auth_user):
    helm = (await category(db, "kubernetes.helm")).id
    skill, _ = await published_skill(db, helm, "chart-review", approver_id=auth_user.id, files=FILES)
    skill_id = skill.id
    await db.commit()

    found = await execute_tool("skill_search", {"query": "helm charts", "category": "kubernetes"}, _context(db, auth_user))
    assert [item["name"] for item in found["results"]] == ["chart-review"]
    assert found["results"][0]["resources"] == ["references/checklist.md"]
    assert found["results"][0]["category"] == "kubernetes.helm"
    other = await execute_tool("skill_search", {"query": "helm charts", "category": "iac"}, _context(db, auth_user))
    assert other["results"] == []

    card = await execute_tool("skill_get", {"skill_id": skill_id, "content_level": "card"}, _context(db, auth_user))
    assert card["content"] == "Review Helm charts.\n\nSections:\n- Chart review\n  - Steps"
    reference = await execute_tool("skill_get", {"skill_id": skill_id, "resource": "references/checklist.md"},
                                   _context(db, auth_user))
    assert reference["content_level"] == "resource" and "values documented" in reference["content"]
    script = await execute_tool("skill_get", {"skill_id": skill_id, "resource": "scripts/lint.sh"},
                                _context(db, auth_user))
    assert script["error"] == "Resource not found: scripts/lint.sh"

    # An open draft is never delivered: chat keeps reading the published version.
    draft = (await client.post(f"{BASE}/skills/{skill_id}/edit", headers=bearer(auth_user.id))).json()
    await client.put(f"{BASE}/skills/{skill_id}/versions/2", json={"body": "\n# Draft only\n"},
                     headers={**bearer(auth_user.id), "If-Match": draft["digest"]})
    full = await execute_tool("skill_get", {"skill_id": skill_id, "content_level": "full"}, _context(db, auth_user))
    assert full["content"].startswith("# Chart review") and full["version"] == 1
    event = (await db.execute(select(SkillUsageEvent).where(SkillUsageEvent.skill_id == skill_id,
                                                            SkillUsageEvent.content_level == "full"))).scalar_one()
    assert (event.surface, event.invocation, event.skill_version) == ("platform_chat", "get", 1)


@pytest.mark.asyncio
async def test_unpublished_skills_and_mcp_entries_never_reach_chat(db, auth_user):
    docs = (await category(db, "engineering.documentation")).id
    draft, _ = await draft_skill(db, docs, "draft-only")
    draft_id = draft.id
    await db.commit()
    assert (await execute_tool("skill_search", {"query": "draft"}, _context(db, auth_user)))["results"] == []
    refused = await execute_tool("skill_get", {"skill_id": draft_id}, _context(db, auth_user))
    assert refused["error"] == "Skill is not published"
    diagnostics = await execute_tool("skill_get", {"skill_id": draft_id, "diagnostics": True}, _context(db, auth_user))
    assert diagnostics["diagnostics"] is True and diagnostics["status"] == "draft"
    viewer = await execute_tool("skill_get", {"skill_id": draft_id, "diagnostics": True},
                                _context(db, auth_user, roles=["viewer"]))
    assert viewer["error"] == "Skill is not published"


@pytest.mark.asyncio
async def test_a_workspace_category_assignment_controls_what_chat_finds(client, db, auth_user):
    project_id = (await db.execute(select(Project.id).where(Project.name == "acme-orders"))).scalar_one()
    terraform, helm = (await category(db, "iac.terraform")).id, (await category(db, "kubernetes.helm")).id
    await published_skill(db, terraform, "tf-style", approver_id=auth_user.id)
    await published_skill(db, helm, "chart-style", approver_id=auth_user.id)
    await db.commit()
    view = (await client.get(f"{BASE}/workspaces/{project_id}/skills", headers=bearer(auth_user.id))).json()
    await client.put(f"{BASE}/workspaces/{project_id}/skills", headers={**bearer(auth_user.id), "If-Match": view["digest"]},
                     json={"mode": "selected_only", "category_keys": ["iac"], "skill_ids": [], "blocked_skill_ids": [],
                           "surfaces": {"platform_chat": True, "octryx_claude": True}})
    found = await execute_tool("skill_search", {"query": "check", "project_id": project_id},
                               _context(db, auth_user, project_id))
    assert [item["name"] for item in found["results"]] == ["tf-style"]
    denied = await execute_tool("skill_get", {"name": "chart-style", "project_id": project_id},
                                _context(db, auth_user, project_id))
    assert denied["error"] == "Skill is not assigned to the current project"


