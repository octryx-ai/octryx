"""Canonical service surface for design delivery synchronization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from . import fetch as _delivery_fetch_module
from .fetch import (
    fetch_bitbucket_checkpoints,
    fetch_bitbucket_releases,
    fetch_github_checkpoints,
    fetch_github_releases,
    fetch_gitlab_checkpoints,
    fetch_gitlab_releases,
)
from .project_workflow import load_project_workflow
from .runners import (
    sync_checkpoint_traceability_impl,
    sync_release_traceability_impl,
)
from .workflows import ALLOWED_PROVIDERS

FetchFn = Callable[..., Awaitable[list[dict[str, Any]]]]


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("-", " ").replace("_", " ").split())


def _bind_fetch_overrides(
    *,
    fetch_github_releases_fn: FetchFn | None = None,
    fetch_github_checkpoints_fn: FetchFn | None = None,
    fetch_gitlab_releases_fn: FetchFn | None = None,
    fetch_gitlab_checkpoints_fn: FetchFn | None = None,
    fetch_bitbucket_releases_fn: FetchFn | None = None,
    fetch_bitbucket_checkpoints_fn: FetchFn | None = None,
) -> None:
    _delivery_fetch_module.fetch_github_releases = fetch_github_releases_fn
    _delivery_fetch_module.fetch_github_checkpoints = fetch_github_checkpoints_fn
    _delivery_fetch_module.fetch_gitlab_releases = fetch_gitlab_releases_fn
    _delivery_fetch_module.fetch_gitlab_checkpoints = fetch_gitlab_checkpoints_fn
    _delivery_fetch_module.fetch_bitbucket_releases = fetch_bitbucket_releases_fn
    _delivery_fetch_module.fetch_bitbucket_checkpoints = fetch_bitbucket_checkpoints_fn


def _resolved_fetchers(
    *,
    fetch_github_releases_fn: FetchFn | None = None,
    fetch_github_checkpoints_fn: FetchFn | None = None,
    fetch_gitlab_releases_fn: FetchFn | None = None,
    fetch_gitlab_checkpoints_fn: FetchFn | None = None,
    fetch_bitbucket_releases_fn: FetchFn | None = None,
    fetch_bitbucket_checkpoints_fn: FetchFn | None = None,
) -> dict[str, FetchFn]:
    # Resolve at call time so monkeypatched module attributes take effect.
    return {
        "fetch_github_releases_fn": fetch_github_releases_fn or fetch_github_releases,
        "fetch_github_checkpoints_fn": fetch_github_checkpoints_fn or fetch_github_checkpoints,
        "fetch_gitlab_releases_fn": fetch_gitlab_releases_fn or fetch_gitlab_releases,
        "fetch_gitlab_checkpoints_fn": fetch_gitlab_checkpoints_fn or fetch_gitlab_checkpoints,
        "fetch_bitbucket_releases_fn": fetch_bitbucket_releases_fn or fetch_bitbucket_releases,
        "fetch_bitbucket_checkpoints_fn": fetch_bitbucket_checkpoints_fn or fetch_bitbucket_checkpoints,
    }


async def sync_release_traceability(
    db: AsyncSession,
    *,
    project_id: str,
    limit_per_repository: int = 30,
    fetch_github_releases_fn: FetchFn | None = None,
    fetch_github_checkpoints_fn: FetchFn | None = None,
    fetch_gitlab_releases_fn: FetchFn | None = None,
    fetch_gitlab_checkpoints_fn: FetchFn | None = None,
    fetch_bitbucket_releases_fn: FetchFn | None = None,
    fetch_bitbucket_checkpoints_fn: FetchFn | None = None,
) -> dict[str, Any]:
    # The workflow runner resolves unset fetchers at call time, so monkeypatched module attributes take effect.
    result = await run_design_trace_sync_workflow(
        db,
        project_id=project_id,
        workflow_id="releases",
        limit_per_repository=limit_per_repository,
        fetch_github_releases_fn=fetch_github_releases_fn,
        fetch_github_checkpoints_fn=fetch_github_checkpoints_fn,
        fetch_gitlab_releases_fn=fetch_gitlab_releases_fn,
        fetch_gitlab_checkpoints_fn=fetch_gitlab_checkpoints_fn,
        fetch_bitbucket_releases_fn=fetch_bitbucket_releases_fn,
        fetch_bitbucket_checkpoints_fn=fetch_bitbucket_checkpoints_fn,
    )
    result["release_candidates"] = result.get("candidate_count", 0)
    return result


async def sync_checkpoint_traceability(
    db: AsyncSession,
    *,
    project_id: str,
    limit_per_repository: int = 30,
    fetch_github_releases_fn: FetchFn | None = None,
    fetch_github_checkpoints_fn: FetchFn | None = None,
    fetch_gitlab_releases_fn: FetchFn | None = None,
    fetch_gitlab_checkpoints_fn: FetchFn | None = None,
    fetch_bitbucket_releases_fn: FetchFn | None = None,
    fetch_bitbucket_checkpoints_fn: FetchFn | None = None,
) -> dict[str, Any]:
    # The workflow runner resolves unset fetchers at call time, so monkeypatched module attributes take effect.
    result = await run_design_trace_sync_workflow(
        db,
        project_id=project_id,
        workflow_id="checkpoints",
        limit_per_repository=limit_per_repository,
        fetch_github_releases_fn=fetch_github_releases_fn,
        fetch_github_checkpoints_fn=fetch_github_checkpoints_fn,
        fetch_gitlab_releases_fn=fetch_gitlab_releases_fn,
        fetch_gitlab_checkpoints_fn=fetch_gitlab_checkpoints_fn,
        fetch_bitbucket_releases_fn=fetch_bitbucket_releases_fn,
        fetch_bitbucket_checkpoints_fn=fetch_bitbucket_checkpoints_fn,
    )
    result["checkpoint_candidates"] = result.get("candidate_count", 0)
    return result


async def run_design_trace_sync_workflow(
    db: AsyncSession,
    *,
    project_id: str,
    workflow_id: str,
    limit_per_repository: int | None = None,
    fetch_github_releases_fn: FetchFn | None = None,
    fetch_github_checkpoints_fn: FetchFn | None = None,
    fetch_gitlab_releases_fn: FetchFn | None = None,
    fetch_gitlab_checkpoints_fn: FetchFn | None = None,
    fetch_bitbucket_releases_fn: FetchFn | None = None,
    fetch_bitbucket_checkpoints_fn: FetchFn | None = None,
) -> dict[str, Any]:
    fetchers = _resolved_fetchers(
        fetch_github_releases_fn=fetch_github_releases_fn,
        fetch_github_checkpoints_fn=fetch_github_checkpoints_fn,
        fetch_gitlab_releases_fn=fetch_gitlab_releases_fn,
        fetch_gitlab_checkpoints_fn=fetch_gitlab_checkpoints_fn,
        fetch_bitbucket_releases_fn=fetch_bitbucket_releases_fn,
        fetch_bitbucket_checkpoints_fn=fetch_bitbucket_checkpoints_fn,
    )
    _bind_fetch_overrides(**fetchers)
    workflow = await load_project_workflow(db, project_id=project_id, workflow_id=workflow_id)
    effective_limit = max(1, min(int(limit_per_repository or workflow.get("limit_per_repository") or 30), 100))
    source_kind = str(workflow.get("source_kind") or "")
    providers = [
        str(value).strip().lower()
        for value in (workflow.get("providers") if isinstance(workflow.get("providers"), list) else [])
        if str(value).strip().lower() in ALLOWED_PROVIDERS
    ] or ["github", "bitbucket"]
    mode = str(workflow.get("mode") or "auto_link").strip().lower()
    result = await _run_source_kind(
        db,
        source_kind,
        project_id=project_id,
        limit_per_repository=effective_limit,
        providers=providers,
        mode=mode,
        workflow=workflow,
    )
    result["workflow"] = workflow
    result["workflow_id"] = workflow_id
    result["mode"] = mode
    result["limit_per_repository"] = effective_limit
    return result


async def _run_source_kind(
    db: AsyncSession,
    source_kind: str,
    *,
    project_id: str,
    limit_per_repository: int,
    providers: list[str],
    mode: str,
    workflow: dict[str, Any],
) -> dict[str, Any]:
    runners = {
        "release": sync_release_traceability_impl,
        "checkpoint": sync_checkpoint_traceability_impl,
    }
    runner = runners.get(source_kind)
    if runner is None:
        raise ValueError("Unsupported trace sync source kind")
    return await runner(
        db,
        project_id=project_id,
        limit_per_repository=limit_per_repository,
        providers=providers,
        mode=mode,
        match_rules=list(workflow.get("match_rules") or []),
        normalize_text=_normalize_text,
    )


__all__ = [
    "_bind_fetch_overrides",
    "_normalize_text",
    "run_design_trace_sync_workflow",
    "sync_checkpoint_traceability",
    "sync_release_traceability",
]
