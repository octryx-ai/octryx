"""Project repository operation checks deny missing sessions, scopes, unconfigured or inactive repositories and read-only mutations."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import CodeRepository, Project
from app.services.project_resource_policy import require_project_repository_operation


@pytest.mark.asyncio
async def test_project_repository_operation_denies_missing_database_session():
    with pytest.raises(HTTPException) as exc_info:
        await require_project_repository_operation(
            None,
            project_ids=["project-1"],
            provider="bitbucket",
            operation="read",
            repository_refs=["service-api"],
        )

    assert exc_info.value.status_code == 403
    assert "database session is unavailable" in exc_info.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("project_ids", "provider", "repository_refs", "expected_reason"),
    [
        ([], "bitbucket", ["service-api"], "project scope is missing"),
        (["project-1"], "", ["service-api"], "provider is missing"),
        (["project-1"], "bitbucket", [], "repository reference is missing"),
    ],
)
async def test_project_repository_operation_denies_missing_required_scope(
    db,
    project_ids,
    provider,
    repository_refs,
    expected_reason,
):
    with pytest.raises(HTTPException) as exc_info:
        await require_project_repository_operation(
            db,
            project_ids=project_ids,
            provider=provider,
            operation="read",
            repository_refs=repository_refs,
        )

    assert exc_info.value.status_code == 403
    assert expected_reason in exc_info.value.detail


@pytest.mark.asyncio
async def test_project_repository_operation_denies_unconfigured_repository(db):
    project = Project(name="repo-unconfigured-policy-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="service-api",
            provider="bitbucket",
            repo_root="/workspace/service-api",
            remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
            config_json={"operation_policy": {"read": True}},
        )
    )
    await db.commit()

    await require_project_repository_operation(
        db,
        project_ids=[project.id],
        provider="bitbucket",
        operation="read",
        repository_refs=["service-api"],
    )
    with pytest.raises(HTTPException) as exc_info:
        await require_project_repository_operation(
            db,
            project_ids=[project.id],
            provider="bitbucket",
            operation="read",
            repository_refs=["unknown-api"],
        )

    assert exc_info.value.status_code == 403
    assert "repository is not configured" in exc_info.value.detail


@pytest.mark.asyncio
async def test_project_repository_operation_readonly_repository_denies_mutations(db):
    project = Project(name="repo-readonly-policy-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="service-api",
            provider="bitbucket",
            repo_root="/workspace/service-api",
            remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
            config_json={"operation_policy": {"read": True, "branch": False, "write": False, "pr": False}},
        )
    )
    await db.commit()

    await require_project_repository_operation(
        db,
        project_ids=[project.id],
        provider="bitbucket",
        operation="read",
        repository_refs=["service-api"],
    )

    for operation in ("branch", "write", "pr"):
        with pytest.raises(HTTPException) as exc_info:
            await require_project_repository_operation(
                db,
                project_ids=[project.id],
                provider="bitbucket",
                operation=operation,
                repository_refs=["service-api"],
            )
        assert exc_info.value.status_code == 403
        assert operation in exc_info.value.detail


@pytest.mark.asyncio
async def test_project_repository_operation_matches_slugified_workspace_directory(db):
    # Workspace checkouts slugify PROJECT/repo into project-repo as directory
    # name; a write from such a workspace must match the configured repository.
    project = Project(name="repo-slug-match-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="SHOP/aws-shop-infrastructure",
            provider="bitbucket",
            repo_root="/var/repos/bitbucket/SHOP/aws-shop-infrastructure",
            config_json={"operation_policy": {"read": True, "branch": True, "write": True, "pr": True}},
        )
    )
    await db.commit()

    await require_project_repository_operation(
        db,
        project_ids=[project.id],
        provider="bitbucket",
        operation="write",
        repository_refs=[
            "/tmp/workspaces/run-1/shop-aws-shop-infrastructure",
            "shop-aws-shop-infrastructure",
        ],
    )


@pytest.mark.asyncio
async def test_project_repository_operation_inactive_repository_is_not_configured(db):
    project = Project(name="repo-inactive-policy-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="service-api",
            provider="bitbucket",
            repo_root="/workspace/service-api",
            remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
            config_json={"operation_policy": {"read": True, "branch": True}},
            is_active=False,
        )
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await require_project_repository_operation(
            db,
            project_ids=[project.id],
            provider="bitbucket",
            operation="read",
            repository_refs=["service-api"],
        )

    assert exc_info.value.status_code == 403
    assert "repository is not configured" in exc_info.value.detail
