"""Resolve runtime Engineering Knowledge context for an explicit migration target."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..project_resource_policy import repository_operation_policy
from ._runtime_pack_resolution import (
    append_blocker,
    attach_retrieved_index_records,
    attach_retrieved_items,
    evaluate_selected_pack,
    resolve_runtime_pack,
)
from ._runtime_repository_resolution import resolve_runtime_repository
from ._runtime_types import (
    EngineeringKnowledgeRuntimeRequest,
    EngineeringKnowledgeRuntimeResolution,
    EngineeringUpgradeTarget,
    RepositoryResolution,
)
from .runtime_prompt import build_engineering_runtime_request


async def resolve_engineering_runtime_context(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    repository_id: str | None = None,
    local_search_roots: list[str] | None = None,
    max_items: int = 8,
    budget_tokens: int = 12_000,
    target: EngineeringUpgradeTarget | None = None,
) -> EngineeringKnowledgeRuntimeResolution:
    """Resolve the repository and pack for an explicit ``target``; no prompt text is an input."""
    request = build_engineering_runtime_request(target=target)
    blockers = list(request.blockers)
    resolution = EngineeringKnowledgeRuntimeResolution(
        request=request,
        blockers=blockers,
        clarification_questions=questions_for_blockers(blockers, request=request),
        budget_tokens=budget_tokens,
    )
    if request.intent != "coding_migration" or blockers:
        return resolution

    repo_resolution = await resolve_runtime_repository(
        db,
        project_id=project_id,
        repository_id=repository_id,
        local_search_roots=local_search_roots,
    )
    resolution.repository_resolution = repo_resolution
    repo = repo_resolution.repository
    if _repository_blocked(resolution, repo_resolution) or not _apply_stack(resolution, repo_resolution):
        return resolution

    await _attach_pack(
        db, resolution, repo=repo, project_id=project_id, max_items=max_items, budget_tokens=budget_tokens
    )
    return resolution


async def _attach_pack(
    db: AsyncSession,
    resolution: EngineeringKnowledgeRuntimeResolution,
    *,
    repo: Any,
    project_id: str | None,
    max_items: int,
    budget_tokens: int,
) -> None:
    request = resolution.request
    pack_resolution = await resolve_runtime_pack(db, request=request, repository=repo, project_id=project_id)
    resolution.pack_resolution = pack_resolution
    if pack_resolution.pack_version is None:
        append_blocker(
            resolution,
            "missing_engineering_knowledge_pack",
            "No published quality-passed Engineering Knowledge Pack matched the requested exact target versions.",
        )
        return

    evaluate_selected_pack(resolution, pack_resolution.pack_version)
    if resolution.blockers:
        resolution.clarification_questions.extend(questions_for_blockers(resolution.blockers, request=request))
        return

    attach_retrieved_items(
        resolution,
        pack_resolution.pack_version,
        max_items=max_items,
        budget_tokens=budget_tokens,
    )
    await attach_retrieved_index_records(
        db,
        resolution,
        pack_resolution.pack_version,
        max_records_per_kind=max_items,
    )


def _repository_blocked(
    resolution: EngineeringKnowledgeRuntimeResolution, repo_resolution: RepositoryResolution
) -> bool:
    repo = repo_resolution.repository
    if repo is None:
        append_blocker(
            resolution,
            "ambiguous_repository" if repo_resolution.candidates else "missing_repository",
            "Resolve the target repository before selecting an Engineering Knowledge Pack.",
        )
        resolution.clarification_questions.extend(repository_questions(repo_resolution))
        return True
    if (
        repo.id
        and not str(repo.id).startswith("local:")
        and not repository_operation_policy(repo).get("migration", False)
    ):
        append_blocker(
            resolution,
            "repository_migration_disabled",
            "Project repository policy does not allow migration operations for the resolved repository.",
        )
        resolution.clarification_questions.append(
            "Should migration be explicitly allowed for this repository in the Project Settings?"
        )
        return True
    return False


def _apply_stack(resolution: EngineeringKnowledgeRuntimeResolution, repo_resolution: RepositoryResolution) -> bool:
    request = resolution.request
    effective_stack_key = request.stack_key or repo_resolution.detected_stack_key
    if not effective_stack_key:
        append_blocker(
            resolution,
            "missing_stack_key",
            "Neither the upgrade target nor the repository manifest names the technology stack.",
        )
        resolution.clarification_questions.append("Which technology stack should this migration use?")
        return False
    request.stack_key = effective_stack_key
    if not request.source_versions:
        request.source_versions = dict(repo_resolution.detected_source_versions)
    return True


def questions_for_blockers(
    blockers: list[dict[str, str]],
    *,
    request: EngineeringKnowledgeRuntimeRequest,
) -> list[str]:
    questions: list[str] = []
    codes = {blocker.get("code") for blocker in blockers}
    if "missing_target_versions" in codes:
        questions.append("Which exact target versions should I use, for example Java 25 and Spring Boot 4.0.3?")
    if "stale_engineering_knowledge_pack" in codes and not request.source_versions:
        questions.append("Which exact source versions should I use for the Knowledge Pack update?")
    return questions


def repository_questions(repo_resolution: RepositoryResolution) -> list[str]:
    # The chat text does not select a repository: the answer must become a binding.
    if repo_resolution.candidates:
        names = ", ".join(candidate["name"] for candidate in repo_resolution.candidates[:5])
        return [
            f"Which repository should be used? Candidates: {names}. Bind it to this session or keep it the only "
            "active repository of the Workspace; naming it in the chat does not select it."
        ]
    return ["Which repository should be used? Register it for this Workspace or bind it to this session."]


__all__ = [
    "resolve_engineering_runtime_context",
]
