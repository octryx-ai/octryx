"""A record set up from a Knowledge repository source decides repository operations with its own policy.

scm.create_branch on a GitHub repository must not be "not configured" for a record "Set up" from the linked GitHub
source (provider knowledge_snapshot, no remote of its own).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.models import CodeRepository
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.project_resource_policy import require_project_repository_operation
from tests.knowledge_evidence_seed_support import seed_workspace


async def _snapshot_record(db, *, branch: bool) -> str:
    workspace_id = await seed_workspace(db)
    source = KnowledgeSourceConnector(project_id=workspace_id, connector_key=f"bench-{uuid.uuid4().hex[:6]}",
                                      kind="git_repository",
                                      scope={"remote": "https://github.com/octryx-ai/bench", "ref": "main"})
    db.add(source)
    await db.flush()
    db.add(CodeRepository(project_id=workspace_id, provider="knowledge_snapshot", name="octryx-ai/bench",
                          repo_root=f"/central-repositories/{uuid.uuid4()}", is_active=True,
                          config_json={"central_source": {"mode": "knowledge_snapshot", "connector_id": source.id},
                                       "operation_policy": {"read": True, "branch": branch, "write": branch,
                                                            "pr": branch, "index": True}}))
    await db.flush()
    return workspace_id


async def _check(db, workspace_id: str, *, provider: str = "github", ref: str = "octryx-ai/bench",
                 operation: str = "branch") -> None:
    await require_project_repository_operation(db, project_ids=[workspace_id], provider=provider,
                                               operation=operation, repository_refs=[ref])


@pytest.mark.asyncio
async def test_the_records_policy_allows_the_operation_on_its_sources_repository(db):
    workspace_id = await _snapshot_record(db, branch=True)
    await _check(db, workspace_id)
    await _check(db, workspace_id, ref="https://github.com/octryx-ai/bench".split("github.com/")[1])


@pytest.mark.asyncio
async def test_the_records_policy_still_decides_and_other_repositories_stay_unconfigured(db):
    workspace_id = await _snapshot_record(db, branch=False)
    with pytest.raises(HTTPException) as disabled:
        await _check(db, workspace_id)
    assert "disabled by the configured repository policy" in str(disabled.value.detail)
    await _check(db, workspace_id, operation="read")
    with pytest.raises(HTTPException) as other:
        await _check(db, workspace_id, ref="octryx-ai/other")
    assert "not configured" in str(other.value.detail)
    with pytest.raises(HTTPException):
        await _check(db, workspace_id, provider="bitbucket")
