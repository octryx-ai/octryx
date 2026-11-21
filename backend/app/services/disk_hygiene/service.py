"""Execution helpers for safe backend disk hygiene."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..system_config.values import (
    get_disk_hygiene_corp_identity_cache_min_age_hours,
    get_disk_hygiene_office_import_stale_min_age_hours,
)
from .candidates import collect_disk_hygiene_candidates


def _delete_candidate_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink(missing_ok=True)


def _plan_policy(
    *,
    corp_identity_cache_min_age_hours: int,
    office_import_stale_min_age_hours: int,
    include_corp_identity_candidates: bool,
    include_office_import_candidates: bool,
) -> dict[str, object]:
    return {
        "corp_identity_cache_min_age_hours": corp_identity_cache_min_age_hours,
        "office_import_stale_min_age_hours": office_import_stale_min_age_hours,
        "cleanup_scope": [
            kind
            for kind, enabled in (
                ("corp_identity_extracted_cache", include_corp_identity_candidates),
                ("office_template_import_package", include_office_import_candidates),
            )
            if enabled
        ],
        "safety_note": (
            "Only rebuildable corp-identity extraction caches and unreferenced Office import packages "
            "are eligible. Source uploads, companion Office templates, active Office runtime entries, "
            "and database artifacts stay out of scope."
        ),
    }


async def collect_backend_disk_hygiene_plan(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    corp_identity_root: Path | None = None,
    office_import_root: Path | None = None,
    corp_identity_cache_min_age_hours: int | None = None,
    office_import_stale_min_age_hours: int | None = None,
    include_corp_identity_candidates: bool = True,
    include_office_import_candidates: bool = True,
    excluded_corp_identity_profile_ids: set[str] | None = None,
) -> dict[str, object]:
    effective_now = now or datetime.now(tz=UTC)
    effective_corp_identity_cache_min_age_hours = (
        corp_identity_cache_min_age_hours
        if corp_identity_cache_min_age_hours is not None
        else await get_disk_hygiene_corp_identity_cache_min_age_hours(db)
    )
    effective_office_import_stale_min_age_hours = (
        office_import_stale_min_age_hours
        if office_import_stale_min_age_hours is not None
        else await get_disk_hygiene_office_import_stale_min_age_hours(db)
    )
    candidates = await collect_disk_hygiene_candidates(
        db,
        now=effective_now,
        corp_identity_root=corp_identity_root,
        office_import_root=office_import_root,
        corp_identity_cache_min_age_hours=effective_corp_identity_cache_min_age_hours,
        office_import_stale_min_age_hours=effective_office_import_stale_min_age_hours,
        include_corp_identity_candidates=include_corp_identity_candidates,
        include_office_import_candidates=include_office_import_candidates,
        excluded_corp_identity_profile_ids=excluded_corp_identity_profile_ids,
    )
    total_bytes = sum(candidate.bytes_used for candidate in candidates)
    kinds: dict[str, int] = {}
    for candidate in candidates:
        kinds[candidate.kind] = kinds.get(candidate.kind, 0) + 1
    return {
        "generated_at": effective_now.isoformat(),
        "candidates": [candidate.as_dict() for candidate in candidates],
        "totals": {
            "count": len(candidates),
            "bytes_used": total_bytes,
            "bytes_used_mb": round(total_bytes / (1024 * 1024), 2),
            "by_kind": kinds,
        },
        "policy": _plan_policy(
            corp_identity_cache_min_age_hours=effective_corp_identity_cache_min_age_hours,
            office_import_stale_min_age_hours=effective_office_import_stale_min_age_hours,
            include_corp_identity_candidates=include_corp_identity_candidates,
            include_office_import_candidates=include_office_import_candidates,
        ),
    }


async def run_backend_disk_hygiene(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    dry_run: bool = True,
    corp_identity_root: Path | None = None,
    office_import_root: Path | None = None,
    corp_identity_cache_min_age_hours: int | None = None,
    office_import_stale_min_age_hours: int | None = None,
    include_corp_identity_candidates: bool = True,
    include_office_import_candidates: bool = True,
    excluded_corp_identity_profile_ids: set[str] | None = None,
) -> dict[str, object]:
    plan = await collect_backend_disk_hygiene_plan(
        db,
        now=now,
        corp_identity_root=corp_identity_root,
        office_import_root=office_import_root,
        corp_identity_cache_min_age_hours=corp_identity_cache_min_age_hours,
        office_import_stale_min_age_hours=office_import_stale_min_age_hours,
        include_corp_identity_candidates=include_corp_identity_candidates,
        include_office_import_candidates=include_office_import_candidates,
        excluded_corp_identity_profile_ids=excluded_corp_identity_profile_ids,
    )
    deleted: list[dict[str, object]] = []
    if not dry_run:
        for candidate in plan["candidates"]:
            candidate_path = Path(str(candidate.get("path") or "")).expanduser().resolve()
            _delete_candidate_path(candidate_path)
            deleted.append({"kind": candidate["kind"], "path": str(candidate_path)})
    return {
        **plan,
        "dry_run": dry_run,
        "deleted": deleted,
        "deleted_count": len(deleted),
    }


__all__ = [
    "collect_backend_disk_hygiene_plan",
    "run_backend_disk_hygiene",
]
