"""Example decks (Slot 2) of PowerPoint identity profiles: attach and clear."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def attach_example_deck_to_corp_identity_profile(
    db: AsyncSession, *, profile_id: str, file_name: str, file_bytes: bytes
) -> dict[str, Any]:
    """Attach an example presentation (Slot 2) to a PowerPoint identity profile.

    The example teaches *how* each named layout is filled (dramaturgy); it never
    contributes brand, theme, or content. It is validated against the profile's
    own template before it is stored: an example that shares no layout names with
    the brand teaches nothing and is rejected rather than kept as dead weight. A
    new example replaces any prior one — a profile carries at most one.
    """
    from .. import corp_identity_service as svc
    from ..office_identity import build_template_snapshot

    suffix = Path(file_name or "").suffix.lower()
    if suffix not in {".pptx", ".potx"}:
        raise ValueError(f"An example deck must be a .pptx or .potx file, not '{suffix or 'unknown'}'")

    registry = await svc._load_registry(db)
    record = next((item for item in registry if str(item.get("id") or "") == str(profile_id or "")), None)
    if record is None:
        raise FileNotFoundError(profile_id)
    source_path = Path(str(record.get("source_path") or "")).expanduser()
    if source_path.suffix.lower() not in {".potx", ".pptx"} or not source_path.is_file():
        raise ValueError("Example decks apply only to PowerPoint corporate identity profiles")

    profile_root = Path(str(record.get("profile_root") or "")).expanduser()
    example_dir = profile_root / "example"
    example_dir.mkdir(parents=True, exist_ok=True)
    safe_name = svc._safe_upload_name(file_name)

    # Stage, validate against the brand template, and only then commit — a
    # rejected example never overwrites a working one.
    staging = example_dir / f".staging-{safe_name}"
    staging.write_bytes(file_bytes)
    try:
        snapshot = build_template_snapshot(source_path, example_deck_path=staging)
        learned = int((snapshot.get("example_deck") or {}).get("layouts_learned") or 0)
        if learned < 1:
            raise ValueError(
                "This deck shares no layout names with the profile's template, so it teaches "
                "nothing. Upload an example built on this brand template."
            )
    except Exception:
        staging.unlink(missing_ok=True)
        raise

    for existing in example_dir.glob("*"):
        if existing != staging:
            existing.unlink()
    staging.replace(example_dir / safe_name)

    record["example_deck_path"] = str((example_dir / safe_name).resolve())
    record["example_deck_file"] = safe_name
    record["example_deck_layouts_learned"] = learned
    record["updated_at"] = svc._utc_now_iso()
    await svc._save_registry(db, registry)
    return await svc.get_corp_identity_profile_detail(db, profile_id)


async def clear_example_deck_from_corp_identity_profile(
    db: AsyncSession, *, profile_id: str
) -> dict[str, Any]:
    """Remove a profile's example deck; the profile falls back to its own slides."""
    from .. import corp_identity_service as svc

    registry = await svc._load_registry(db)
    record = next((item for item in registry if str(item.get("id") or "") == str(profile_id or "")), None)
    if record is None:
        raise FileNotFoundError(profile_id)
    profile_root = Path(str(record.get("profile_root") or "")).expanduser()
    example_dir = profile_root / "example"
    if example_dir.is_dir():
        shutil.rmtree(example_dir, ignore_errors=True)
    for key in ("example_deck_path", "example_deck_file", "example_deck_layouts_learned"):
        record.pop(key, None)
    record["updated_at"] = svc._utc_now_iso()
    await svc._save_registry(db, registry)
    return await svc.get_corp_identity_profile_detail(db, profile_id)
