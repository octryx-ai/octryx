"""Project-scoped design artifacts for outcome, requirements and architecture."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.design_artifact.common import (
    RECOMMENDED_DESIGN_ARTIFACTS,
    artifact_template_markdown,
    list_recommended_design_artifacts,
    normalize_id_list,
    recommended_map,
)
from app.services.design_artifact.crud import create_design_artifact, list_design_artifacts, list_design_trace_links
from app.services.design_artifact.support import (
    project_exists,
    project_repository_ids,
    project_task_options,
)

from ..models import CodeRepository


async def bootstrap_design_artifacts(
    db: AsyncSession,
    *,
    project_id: str,
    include_optional: bool = False,
) -> dict[str, object]:
    await project_exists(db, project_id)
    existing = await list_design_artifacts(db, project_id=project_id)
    existing_kinds = {str(item.get("artifact_kind") or "").strip() for item in existing}
    created: list[dict[str, object]] = []
    for template in RECOMMENDED_DESIGN_ARTIFACTS:
        if not include_optional and not bool(template.get("required_by_default")):
            continue
        kind = str(template.get("artifact_kind") or "").strip()
        if not kind or kind in existing_kinds:
            continue
        created.append(
            await create_design_artifact(
                db,
                project_id=project_id,
                payload={
                    "artifact_kind": kind,
                    "title": str(template.get("label") or kind.replace("_", " ").title()),
                    "status": "draft",
                    "summary": str(template.get("description") or "").strip(),
                    "content_markdown": artifact_template_markdown(template),
                    "is_required": bool(template.get("required_by_default")),
                    "order_index": int(template.get("order_index") or 100),
                    "metadata_json": {},
                },
            )
        )
    return {
        "project_id": project_id,
        "created": created,
        "created_count": len(created),
        "items": await list_design_artifacts(db, project_id=project_id),
    }


async def get_project_design_readiness(
    db: AsyncSession,
    *,
    project_id: str,
) -> dict[str, object]:
    items = await list_design_artifacts(db, project_id=project_id)
    repositories = (
        await db.execute(select(CodeRepository.id, CodeRepository.name).where(CodeRepository.project_id == project_id))
    ).all()
    repository_ids = {str(row[0]) for row in repositories if row and row[0]}
    required_kinds = _required_design_kinds(items)
    coverage, linked_repository_ids = _design_coverage(items, repository_ids)
    approved_required_kinds, pending_required_kinds, missing_required_kinds = _classify_required_kinds(
        required_kinds, coverage
    )

    required_total = len(required_kinds)
    approved_total = len(approved_required_kinds)
    linked_repo_ratio = (len(linked_repository_ids) / len(repository_ids)) if repository_ids else 1.0
    required_ratio = (approved_total / required_total) if required_total else 1.0
    readiness_score = int(round(((required_ratio * 0.85) + (linked_repo_ratio * 0.15)) * 100))

    blockers: list[str] = []
    if missing_required_kinds:
        blockers.append(f"Missing required artifacts: {', '.join(missing_required_kinds)}")
    if pending_required_kinds:
        blockers.append(f"Required artifacts not approved: {', '.join(pending_required_kinds)}")
    if repository_ids and not linked_repository_ids:
        blockers.append("No design artifact is linked to a code intelligence repository.")

    return {
        "project_id": project_id,
        "required_total": required_total,
        "approved_required_total": approved_total,
        "required_approval_rate": round(required_ratio, 4),
        "readiness_score": readiness_score,
        "missing_required_kinds": missing_required_kinds,
        "pending_required_kinds": pending_required_kinds,
        "approved_required_kinds": approved_required_kinds,
        "blockers": blockers,
        "artifact_coverage": coverage,
        "repository_traceability": {
            "total_repositories": len(repository_ids),
            "linked_repositories": len(linked_repository_ids),
            "linked_repository_ids": sorted(linked_repository_ids),
            "coverage_rate": round(linked_repo_ratio, 4),
        },
    }


def _required_design_kinds(items: list[dict[str, object]]) -> set[str]:
    recommended = recommended_map()
    required_kinds = {kind for kind, template in recommended.items() if bool(template.get("required_by_default"))}
    required_kinds.update(
        str(item.get("artifact_kind") or "").strip()
        for item in items
        if bool(item.get("is_required")) and str(item.get("artifact_kind") or "").strip()
    )
    return required_kinds


def _design_coverage(
    items: list[dict[str, object]], repository_ids: set[str]
) -> tuple[dict[str, dict[str, int]], set[str]]:
    coverage: dict[str, dict[str, int]] = {}
    linked_repository_ids: set[str] = set()
    for item in items:
        kind = str(item.get("artifact_kind") or "").strip()
        if not kind:
            continue
        bucket = coverage.setdefault(kind, {"total": 0, "approved": 0})
        bucket["total"] += 1
        if str(item.get("status") or "") == "approved":
            bucket["approved"] += 1
        linked_repository_ids.update(
            repo_id for repo_id in normalize_id_list(item.get("linked_repository_ids")) if repo_id in repository_ids
        )
    return coverage, linked_repository_ids


def _classify_required_kinds(
    required_kinds: set[str], coverage: dict[str, dict[str, int]]
) -> tuple[list[str], list[str], list[str]]:
    approved_required_kinds: list[str] = []
    pending_required_kinds: list[str] = []
    missing_required_kinds: list[str] = []
    for kind in sorted(required_kinds):
        stats = coverage.get(kind) or {"total": 0, "approved": 0}
        if stats["approved"] > 0:
            approved_required_kinds.append(kind)
        elif stats["total"] > 0:
            pending_required_kinds.append(kind)
        else:
            missing_required_kinds.append(kind)
    return approved_required_kinds, pending_required_kinds, missing_required_kinds


async def get_project_design_traceability(
    db: AsyncSession,
    *,
    project_id: str,
) -> dict[str, object]:
    items = await list_design_artifacts(db, project_id=project_id)
    links = await list_design_trace_links(db, project_id=project_id)
    tasks = await project_task_options(db, project_id)
    artifact_ids = {str(item.get("id") or "") for item in items if item.get("id")}
    approved_artifact_ids = {
        str(item.get("id") or "") for item in items if str(item.get("status") or "") == "approved" and item.get("id")
    }
    linked_artifact_ids = {str(link.get("artifact_id") or "") for link in links if link.get("artifact_id")}
    approved_linked_count = len(approved_artifact_ids & linked_artifact_ids)
    link_counts_by_type: dict[str, int] = {}
    for link in links:
        kind = str(link.get("target_type") or "").strip()
        if not kind:
            continue
        link_counts_by_type[kind] = link_counts_by_type.get(kind, 0) + 1
    approved_total = len(approved_artifact_ids)
    approved_trace_rate = (approved_linked_count / approved_total) if approved_total else 1.0
    delivery_links = sum(link_counts_by_type.get(kind, 0) for kind in ("pull_request", "release", "checkpoint"))
    task_links = link_counts_by_type.get("task", 0)
    score = int(
        round(((approved_trace_rate * 0.7) + (0.2 if task_links else 0.0) + (0.1 if delivery_links else 0.0)) * 100)
    )
    blockers: list[str] = []
    unlinked_approved = sorted(approved_artifact_ids - linked_artifact_ids)
    if unlinked_approved:
        blockers.append(f"{len(unlinked_approved)} approved artifacts are not linked to downstream delivery objects.")
    if tasks and task_links == 0:
        blockers.append("No artifact is linked to a project task.")
    if approved_total and delivery_links == 0:
        blockers.append("No pull request, release or checkpoint trace is linked yet.")
    return {
        "project_id": project_id,
        "total_links": len(links),
        "artifacts_total": len(artifact_ids),
        "artifacts_linked": len(linked_artifact_ids),
        "approved_artifacts_total": approved_total,
        "approved_artifacts_linked": approved_linked_count,
        "approved_trace_rate": round(approved_trace_rate, 4),
        "traceability_score": score,
        "link_counts_by_type": link_counts_by_type,
        "blockers": blockers,
        "task_options": tasks,
        "items": links,
    }


async def get_project_design_context(
    db: AsyncSession,
    *,
    project_id: str,
    artifact_kind: str | None = None,
) -> dict[str, object]:
    items = await list_design_artifacts(db, project_id=project_id, artifact_kind=artifact_kind)
    coverage: dict[str, int] = {}
    approved_count = 0
    for item in items:
        kind = str(item.get("artifact_kind") or "").strip()
        if kind:
            coverage[kind] = coverage.get(kind, 0) + 1
        if str(item.get("status") or "") == "approved":
            approved_count += 1
    return {
        "project_id": project_id,
        "items": items,
        "recommended_artifacts": list_recommended_design_artifacts(),
        "coverage": coverage,
        "approved_count": approved_count,
        "total_count": len(items),
        "readiness": await get_project_design_readiness(db, project_id=project_id),
        "traceability": await get_project_design_traceability(db, project_id=project_id),
        "repositories": {
            "items": [{"id": repository_id} for repository_id in sorted(await project_repository_ids(db, project_id))],
        },
    }


__all__ = [
    "bootstrap_design_artifacts",
    "get_project_design_readiness",
    "get_project_design_traceability",
    "get_project_design_context",
]
