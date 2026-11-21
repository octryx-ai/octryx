from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import (
    Project,
    ResearchPolicyProfile,
    ResearchPolicyProfileVersion,
    WorkspaceResearchPolicyAssignment,
)
from app.services.research_policy import resolve_effective_research_policy


@pytest.mark.asyncio
async def test_default_research_policy_profiles_seeded_with_evidence_archive(db):
    rows = (
        (
            await db.execute(
                select(ResearchPolicyProfile, ResearchPolicyProfileVersion)
                .join(ResearchPolicyProfileVersion)
                .where(ResearchPolicyProfileVersion.status == "published")
            )
        )
        .tuples()
        .all()
    )
    profiles = {profile.key: version for profile, version in rows}

    assert "standard-research-document" in profiles
    assert "deep-research-document" in profiles
    assert "scientific-literature-review" in profiles
    assert profiles["standard-research-document"].spec["evidence_archive"]["workspace_folder"] == "research"

    deep_policy = profiles["deep-research-document"].spec
    assert deep_policy["research_strategy"]["max_source_count"] == 120
    assert deep_policy["output_policy"]["target_pages"]["target"] == 20
    assert deep_policy["quality_gates"]["min_pdf_or_office_sources"] == 3

    literature_policy = profiles["scientific-literature-review"].spec
    assert literature_policy["source_policy"]["research_mode"] == "literature"
    assert literature_policy["source_policy"]["literature_policy"]["require_published_sources"] is True
    assert literature_policy["source_policy"]["literature_policy"]["require_peer_reviewed_sources"] is True
    assert literature_policy["source_policy"]["literature_policy"]["exclude_preprints"] is True


@pytest.mark.asyncio
async def test_workspace_research_policy_assignment_links_profile_version(db):
    deep_version = (
        await db.execute(
            select(ResearchPolicyProfileVersion)
            .join(ResearchPolicyProfile)
            .where(ResearchPolicyProfile.key == "deep-research-document")
        )
    ).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"research-policy-workspace-{uuid.uuid4().hex[:8]}",
        config={},
        is_active=True,
    )
    assignment = WorkspaceResearchPolicyAssignment(
        id=str(uuid.uuid4()),
        workspace_id=project.id,
        profile_version_id=deep_version.id,
        assignment_status="active",
    )
    db.add_all([project, assignment])
    await db.commit()

    loaded_project = (
        await db.execute(
            select(Project)
            .options(
                selectinload(Project.research_policy_assignment).selectinload(
                    WorkspaceResearchPolicyAssignment.profile_version
                )
            )
            .where(Project.id == project.id)
        )
    ).scalar_one()

    loaded_assignment = loaded_project.research_policy_assignment
    assert loaded_assignment is not None
    assert loaded_assignment.profile_version.id == deep_version.id
    assert loaded_assignment.profile_version.spec["evidence_archive"]["workspace_folder"] == "research"


@pytest.mark.asyncio
async def test_default_research_policy_resolution_uses_the_deep_research_profile(db):
    resolution = await resolve_effective_research_policy(db)

    assert resolution["source"] == "default_profile"
    assert resolution["profile_key"] == "deep-research-document"
    assert resolution["spec"]["research_strategy"]["max_source_count"] == 120
    assert resolution["spec"]["evidence_archive"]["workspace_folder"] == "research"


@pytest.mark.asyncio
async def test_workspace_research_policy_assignment_overrides_default_resolution(db):
    standard_version = (
        await db.execute(
            select(ResearchPolicyProfileVersion)
            .join(ResearchPolicyProfile)
            .where(ResearchPolicyProfile.key == "standard-research-document")
        )
    ).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"standard-research-policy-workspace-{uuid.uuid4().hex[:8]}",
        config={},
        is_active=True,
    )
    assignment = WorkspaceResearchPolicyAssignment(
        id=str(uuid.uuid4()),
        workspace_id=project.id,
        profile_version_id=standard_version.id,
        assignment_status="active",
    )
    db.add_all([project, assignment])
    await db.flush()

    resolution = await resolve_effective_research_policy(db, workspace_id=project.id)

    assert resolution["source"] == "workspace_assignment"
    assert resolution["profile_key"] == "standard-research-document"
    assert resolution["spec"]["research_strategy"]["target_source_count"] == 10
    assert resolution["spec"]["output_policy"]["target_pages"]["target"] == 8


def test_infer_topic_captures_full_for_phrase():
    from app.services.workflow_contracts.topic import infer_topic

    # a single-token capture would title "for the loan approval process" as "the" (visible in rendered diagram
    # titles)
    assert infer_topic("Create an activity diagram for the loan approval process.") == "loan approval process"
    assert infer_topic("Create a BPMN process diagram for invoice handling with clerk and reviewer.") == (
        "invoice handling"
    )
    assert infer_topic("Create a diagram for the credit check with application and decision.") == "credit check"
    # a continuation verb terminates the about capture
    assert infer_topic("Write a report about LightRAG and create a presentation.") == "LightRAG"
