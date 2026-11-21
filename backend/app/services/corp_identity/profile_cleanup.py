"""Default-profile bookkeeping and on-disk cleanup after a profile is saved or re-extracted."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..system_config import get_system_config_value, set_system_config_value
from .registry import load_registry


async def _activate_profile(db: AsyncSession, svc: Any, profile_id: str) -> dict[str, Any]:
    """Make the profile the default when none is set, read its detail, then clean up unused profile roots."""
    await _ensure_default_profile(db, profile_id)
    detail = await svc.get_corp_identity_profile_detail(db, profile_id)
    await _run_corp_identity_cleanup(
        db,
        active_profile_id=profile_id,
        corp_identity_root=svc.CORP_IDENTITY_ROOT,
    )
    return detail


async def _ensure_default_profile(db: AsyncSession, profile_id: str) -> None:
    default_profile_id = await get_system_config_value(db, "agent.corp_identity_default_profile_id")
    if not default_profile_id:
        await set_system_config_value(
            db,
            key="agent.corp_identity_default_profile_id",
            value=profile_id,
            description="Default corporate identity profile.",
        )


async def _prune_unreferenced_corp_identity_roots(
    db: AsyncSession,
    *,
    corp_identity_root: Path,
) -> None:
    if not corp_identity_root.exists() or not corp_identity_root.is_dir():
        return
    referenced_roots: set[Path] = set()
    for profile in await load_registry(db):
        profile_root_raw = str(profile.get("profile_root") or "").strip()
        if not profile_root_raw:
            continue
        profile_root = Path(profile_root_raw).expanduser().resolve()
        if profile_root.exists() and profile_root.is_dir():
            referenced_roots.add(profile_root)

    resolved_root = corp_identity_root.resolve()
    for child in corp_identity_root.iterdir():
        try:
            resolved_child = child.resolve()
        except OSError:
            continue
        if not child.is_dir() or resolved_child in referenced_roots or resolved_root not in resolved_child.parents:
            continue
        shutil.rmtree(resolved_child, ignore_errors=True)


async def _run_corp_identity_cleanup(
    db: AsyncSession,
    *,
    active_profile_id: str,
    corp_identity_root: Path,
) -> None:
    from .. import corp_identity_service as svc
    from ..disk_hygiene import run_backend_disk_hygiene
    from .workspace import assigned_profile_ids

    # Every profile a Workspace uses keeps its extracted assets (the Spec Studio's logo and icons), not only the
    # active one.
    keep = {active_profile_id} | await assigned_profile_ids(db)
    await _prune_unreferenced_corp_identity_roots(db, corp_identity_root=corp_identity_root)
    await run_backend_disk_hygiene(
        db,
        dry_run=False,
        corp_identity_root=corp_identity_root,
        include_office_import_candidates=False,
        excluded_corp_identity_profile_ids=keep,
    )
    extracted_cache_root = svc._profile_root(active_profile_id) / "_extracted"
    if extracted_cache_root.exists() and extracted_cache_root.is_dir():
        shutil.rmtree(extracted_cache_root)
