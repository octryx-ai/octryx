"""Effective setup (A1): the dry run of the real run preparation, its parts, and the turn comparison."""

from __future__ import annotations

import uuid

import pytest

from app.models import Project
from app.services.effective_setup import (
    external_effective_setup,
)
from tests.phased_workflow_fixtures import phased_definition, publish_phased

PART_ORDER = ["system_texts", "agent", "instructions", "workflow", "skills", "tools", "approvals"]












@pytest.mark.asyncio
async def test_octryx_claude_setup_reads_the_mcp_contract_and_instructions(db) -> None:
    project = Project(name=f"setup-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.commit()
    key = await publish_phased(db, phased_definition())

    setup = await external_effective_setup(db, project_id=project.id, workflow_key=key)

    assert [part["id"] for part in setup["parts"]] == PART_ORDER
    texts = setup["parts"][0]
    assert texts["details"]["keys"][0]["key"] == "knowledge.mcp.instructions"
    workflow = setup["parts"][3]
    assert workflow["details"]["selected"] is False
    assert key in workflow["details"]["available_workflow_keys"]
    assert setup["summary"]["profile_status"] == "workflow_run_required"
    assert setup["summary"]["capability"]["class"] == "read_only"


