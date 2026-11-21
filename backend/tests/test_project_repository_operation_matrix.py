from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models import CodeRepository, Project
from app.services.project_resource_policy import normalize_repository_operations, require_project_repository_operation

PROVIDER_CASES = (
    (
        "bitbucket",
        "service-api",
        "https://bitbucket.example/scm/PROJ/service-api.git",
        ("service-api", "PROJ/service-api", "https://bitbucket.example/scm/PROJ/service-api.git"),
    ),
    (
        "github",
        "service-api",
        "https://github.com/risk/service-api.git",
        ("service-api", "risk/service-api", "https://github.com/risk/service-api.git"),
    ),
    (
        "gitlab",
        "service-api",
        "https://gitlab.example/group/service-api.git",
        ("service-api", "group/service-api", "https://gitlab.example/group/service-api.git"),
    ),
)

POLICY_MODE_CASES = (
    (
        "readonly",
        {"read": True, "index": True, "branch": False, "write": False, "pr": False, "migration": False},
        ("read", "index"),
        ("branch", "write", "pr", "migration"),
    ),
    (
        "branch-only",
        {"read": True, "index": True, "branch": True, "write": False, "pr": False, "migration": False},
        ("read", "index", "branch"),
        ("write", "pr", "migration"),
    ),
    (
        "delivery",
        {"read": True, "index": True, "branch": True, "write": True, "pr": True, "migration": False},
        ("read", "index", "branch", "write", "pr"),
        ("migration",),
    ),
    (
        "migration-only",
        {"read": False, "index": False, "branch": False, "write": False, "pr": False, "migration": True},
        ("migration",),
        ("read", "index", "branch", "write", "pr"),
    ),
)


async def _create_repository_project(
    db,
    *,
    provider: str,
    repository_name: str,
    remote_url: str,
    operation_policy: dict[str, bool],
    is_active: bool = True,
) -> str:
    project = Project(name=f"repo-policy-matrix-{provider}-{uuid4().hex}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name=repository_name,
            provider=provider,
            repo_root=f"/workspace/{repository_name}",
            remote_url=remote_url,
            default_branch="main",
            config_json={"operation_policy": operation_policy},
            is_active=is_active,
        )
    )
    await db.commit()
    return project.id


def test_repository_operation_defaults_are_read_and_index_only():
    assert normalize_repository_operations({}) == {
        "read": True,
        "branch": False,
        "write": False,
        "pr": False,
        "index": True,
        "migration": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("provider", "repository_name", "remote_url", "repository_refs"), PROVIDER_CASES)
@pytest.mark.parametrize(("mode", "operation_policy", "allowed_operations", "denied_operations"), POLICY_MODE_CASES)
async def test_repository_operation_access_mode_matrix(
    db,
    provider,
    repository_name,
    remote_url,
    repository_refs,
    mode,
    operation_policy,
    allowed_operations,
    denied_operations,
):
    project_id = await _create_repository_project(
        db,
        provider=provider,
        repository_name=repository_name,
        remote_url=remote_url,
        operation_policy=operation_policy,
    )

    for operation in allowed_operations:
        await require_project_repository_operation(
            db,
            project_ids=[project_id],
            provider=provider,
            operation=operation,
            repository_refs=list(repository_refs),
        )

    for operation in denied_operations:
        with pytest.raises(HTTPException) as exc_info:
            await require_project_repository_operation(
                db,
                project_ids=[project_id],
                provider=provider,
                operation=operation,
                repository_refs=list(repository_refs),
            )
        assert exc_info.value.status_code == 403
        assert operation in exc_info.value.detail
        assert mode in {"readonly", "branch-only", "delivery", "migration-only"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("provider", "repository_name", "remote_url", "repository_refs"), PROVIDER_CASES)
async def test_repository_operation_denies_unconfigured_repository_for_each_provider(
    db,
    provider,
    repository_name,
    remote_url,
    repository_refs,
):
    project_id = await _create_repository_project(
        db,
        provider=provider,
        repository_name=repository_name,
        remote_url=remote_url,
        operation_policy={"read": True, "branch": True, "write": True, "pr": True, "index": True, "migration": True},
    )

    await require_project_repository_operation(
        db,
        project_ids=[project_id],
        provider=provider,
        operation="read",
        repository_refs=list(repository_refs),
    )
    with pytest.raises(HTTPException) as exc_info:
        await require_project_repository_operation(
            db,
            project_ids=[project_id],
            provider=provider,
            operation="read",
            repository_refs=["unknown/service-api"],
        )

    assert exc_info.value.status_code == 403
    assert "repository is not configured" in exc_info.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(("provider", "repository_name", "remote_url", "repository_refs"), PROVIDER_CASES)
async def test_inactive_repositories_do_not_satisfy_access_mode_matrix(
    db,
    provider,
    repository_name,
    remote_url,
    repository_refs,
):
    project_id = await _create_repository_project(
        db,
        provider=provider,
        repository_name=repository_name,
        remote_url=remote_url,
        operation_policy={"read": True, "branch": True, "write": True, "pr": True, "index": True, "migration": True},
        is_active=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_project_repository_operation(
            db,
            project_ids=[project_id],
            provider=provider,
            operation="read",
            repository_refs=list(repository_refs),
        )

    assert exc_info.value.status_code == 403
    assert "repository is not configured" in exc_info.value.detail
