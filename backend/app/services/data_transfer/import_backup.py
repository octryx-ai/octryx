"""Restore of an admin config backup into a target Workspace, section by section."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.data_transfer.backup import restore_skill_rows
from app.services.data_transfer.import_rows import _import_agent_rows, _import_task_rows

from ...models import Project, User
from ..tool_config.connection_fields import refused_connection_keys

ADMIN_CONFIG_RESTORE_SECTIONS = {"project_config", "tasks", "agents", "skills"}
PROTECTED_PROJECT_NAMES = {"default", "master"}


def _normalize_restore_sections(value: list[str] | None, *, manifest: dict[str, Any]) -> set[str]:
    raw_sections = value
    if raw_sections is None:
        included_sections = manifest.get("included_sections")
        raw_sections = included_sections if isinstance(included_sections, list) else None
    if raw_sections is None:
        return set(ADMIN_CONFIG_RESTORE_SECTIONS)
    normalized: set[str] = set()
    for item in raw_sections:
        section = str(item or "").strip().lower()
        if section in ADMIN_CONFIG_RESTORE_SECTIONS:
            normalized.add(section)
    return normalized


def _is_protected_project_payload(value: dict[str, Any]) -> bool:
    return bool(value.get("is_system")) or str(value.get("name") or "").strip().lower() in PROTECTED_PROJECT_NAMES


def _is_protected_project(project: Project) -> bool:
    return bool(project.is_system) or str(project.name or "").strip().lower() in PROTECTED_PROJECT_NAMES


async def _import_admin_config_backup(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
    target_project_id: str,
    overwrite_existing: bool,
    restore_sections: list[str] | None,
    overwrite_skills: bool = False,
) -> tuple[int, int, int, list[str], dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
    package_type = str(manifest.get("package_type") or "").strip().lower()
    if package_type != "admin_config_backup":
        raise HTTPException(status_code=400, detail="Admin config backup payload is invalid")

    project = await db.get(Project, target_project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Target project not found")

    project_payload = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    sections = _normalize_restore_sections(restore_sections, manifest=manifest)

    errors: list[str] = []
    totals = [0, 0, 0]  # rows total, succeeded, failed over all restored sections
    summary: dict[str, Any] = {"restore_sections": sorted(sections)}

    if "project_config" in sections:
        _restore_project_config(db, project, project_payload, summary)
    else:
        summary["project_config_updated"] = False

    await _restore_skills(
        db, current_user=current_user, payload=payload, sections=sections, overwrite_skills=overwrite_skills,
        totals=totals, errors=errors, summary=summary,
    )
    await _restore_definitions(
        db, current_user=current_user, payload=payload, sections=sections, target_project_id=target_project_id,
        overwrite_existing=overwrite_existing, totals=totals, errors=errors, summary=summary,
    )
    summary["excluded_sections"] = list(manifest.get("excluded_sections") or [])
    return totals[0], totals[1], totals[2], errors, summary


async def _restore_skills(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
    sections: set[str],
    overwrite_skills: bool,
    totals: list[int],
    errors: list[str],
    summary: dict[str, Any],
) -> None:
    skill_rows = payload.get("skills") if isinstance(payload.get("skills"), list) else []
    if "skills" not in sections:
        summary["skill_count"] = 0
        return
    # Skills are platform-wide: existing ones are kept unless overwriting them is asked for explicitly.
    success, failed, section_errors, outcome = await restore_skill_rows(
        db, current_user=current_user, rows=skill_rows, overwrite_skills=overwrite_skills
    )
    _tally(totals, errors, "skills", len(skill_rows), success, failed, section_errors)
    summary["skill_count"] = success
    summary.update(outcome)


async def _restore_definitions(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
    sections: set[str],
    target_project_id: str,
    overwrite_existing: bool,
    totals: list[int],
    errors: list[str],
    summary: dict[str, Any],
) -> None:
    for section, rows_importer, count_key in (
        ("tasks", _import_task_rows, "task_count"),
        ("agents", _import_agent_rows, "agent_count"),
    ):
        section_rows = payload.get(section) if isinstance(payload.get(section), list) else []
        if section not in sections:
            summary[count_key] = 0
            continue
        success, failed, section_errors = await rows_importer(
            db,
            current_user=current_user,
            rows=section_rows,
            target_project_id=target_project_id,
            overwrite_existing=overwrite_existing,
        )
        _tally(totals, errors, section, len(section_rows), success, failed, section_errors)
        summary[count_key] = success


def _tally(
    totals: list[int],
    errors: list[str],
    section: str,
    rows: int,
    success: int,
    failed: int,
    section_errors: list[str],
) -> None:
    totals[0] += rows
    totals[1] += success
    totals[2] += failed
    errors.extend([f"{section} {error}" for error in section_errors])


def _restore_project_config(
    db: AsyncSession, project: Project, project_payload: dict[str, Any], summary: dict[str, Any]
) -> None:
    source_protected = _is_protected_project_payload(project_payload)
    target_protected = _is_protected_project(project)
    if source_protected != target_protected:
        summary["project_config_updated"] = False
        summary["project_config_skip_reason"] = "protected_project_mismatch"
        return
    if isinstance(project_payload.get("config"), dict):
        # A connection lives in the Workspace's tool entry, never in Project.config: the
        # restore applies the write paths' rule and drops (and names) any connection key it would set.
        restored = dict(project_payload["config"])
        dropped = refused_connection_keys(restored)
        project.config = {key: value for key, value in restored.items() if key not in dropped}
        summary["project_config_connection_keys_dropped"] = dropped
    project.description = str(project_payload.get("description") or project.description or "")
    # A restore never archives or reactivates the target Workspace.
    db.add(project)
    summary["project_config_updated"] = True
