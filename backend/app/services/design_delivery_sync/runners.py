"""Sync runners for design delivery traceability workflows."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .link_payloads import checkpoint_link_payload, link_key, release_link_payload
from .matching import artifact_match_tokens, checkpoint_matches_artifact, release_matches_artifact
from .references import artifact_pull_request_refs, artifact_release_refs, artifact_task_titles
from .runner_common import TEXT_RULES, SyncRun, load_sync_base
from .workflows import normalize_match_rules


async def sync_release_traceability_impl(
    db: AsyncSession,
    *,
    project_id: str,
    limit_per_repository: int = 30,
    providers: list[str] | None = None,
    mode: str = "auto_link",
    match_rules: list[str] | None = None,
    normalize_text,
) -> dict[str, Any]:
    repositories, artifact_payloads, existing_keys = await load_sync_base(
        db, project_id=project_id, providers=providers
    )
    artifact_ids = {item["id"] for item in artifact_payloads}
    task_titles = await artifact_task_titles(db, artifact_ids)
    linked_pr_refs = await artifact_pull_request_refs(db, artifact_ids)
    run = SyncRun(db, project_id, mode, limit_per_repository, existing_keys)
    active_rules = normalize_match_rules(match_rules, ["artifact_tokens", "task_titles", "linked_pull_requests"])
    for repo in repositories:
        repo_name, releases = await run.fetch(repo, "release")
        for artifact in artifact_payloads:
            task_title_list = task_titles.get(artifact["id"], [])
            tokens = artifact_match_tokens(normalize_text, artifact, task_title_list)
            linked_prs = linked_pr_refs.get(artifact["id"], [])
            if not tokens and not linked_prs and not any(rule in active_rules for rule in TEXT_RULES):
                continue
            for release in releases:
                if not release_matches_artifact(
                    normalize_match_rules,
                    normalize_text,
                    release,
                    artifact=artifact,
                    task_titles=task_title_list,
                    tokens=tokens,
                    linked_prs=linked_prs,
                    rules=active_rules,
                ):
                    continue
                await run.link(
                    link_key(artifact, "release", release),
                    release_link_payload(artifact, release, repo_name),
                )
    return run.result(active_rules)


async def sync_checkpoint_traceability_impl(
    db: AsyncSession,
    *,
    project_id: str,
    limit_per_repository: int = 30,
    providers: list[str] | None = None,
    mode: str = "auto_link",
    match_rules: list[str] | None = None,
    normalize_text,
) -> dict[str, Any]:
    repositories, artifact_payloads, existing_keys = await load_sync_base(
        db, project_id=project_id, providers=providers
    )
    artifact_ids = {item["id"] for item in artifact_payloads}
    task_titles = await artifact_task_titles(db, artifact_ids)
    linked_pr_refs = await artifact_pull_request_refs(db, artifact_ids)
    linked_release_refs = await artifact_release_refs(db, artifact_ids)
    run = SyncRun(db, project_id, mode, limit_per_repository, existing_keys)
    active_rules = normalize_match_rules(
        match_rules, ["artifact_tokens", "task_titles", "linked_pull_requests", "linked_releases"]
    )
    for repo in repositories:
        repo_name, checkpoints = await run.fetch(repo, "checkpoint")
        for artifact in artifact_payloads:
            task_title_list = task_titles.get(artifact["id"], [])
            tokens = artifact_match_tokens(normalize_text, artifact, task_title_list)
            linked_prs = linked_pr_refs.get(artifact["id"], [])
            linked_releases = linked_release_refs.get(artifact["id"], [])
            if not (tokens or linked_prs or linked_releases or any(rule in active_rules for rule in TEXT_RULES)):
                continue
            for checkpoint in checkpoints:
                if not checkpoint_matches_artifact(
                    normalize_match_rules,
                    normalize_text,
                    checkpoint,
                    artifact=artifact,
                    task_titles=task_title_list,
                    tokens=tokens,
                    linked_prs=linked_prs,
                    linked_releases=linked_releases,
                    rules=active_rules,
                ):
                    continue
                await run.link(
                    link_key(artifact, "checkpoint", checkpoint),
                    checkpoint_link_payload(artifact, checkpoint, repo_name),
                )
    return run.result(active_rules)
