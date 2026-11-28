"""Corporate-identity profile extraction and storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.corp_identity.normalized_template_resolve import ResolvedTemplate
from app.services.corp_identity.normalized_template_resolve import (
    resolve_template_for_profile as _resolve_template_for_profile,
)
from app.services.corp_identity.profile_examples import (
    attach_example_deck_to_corp_identity_profile as _attach_example_deck_to_corp_identity_profile,
)
from app.services.corp_identity.profile_examples import (
    clear_example_deck_from_corp_identity_profile as _clear_example_deck_from_corp_identity_profile,
)
from app.services.corp_identity.profile_merge import reextract_corp_identity_profile as _reextract_corp_identity_profile
from app.services.corp_identity.profile_upload import (
    save_uploaded_corp_identity_profile as _save_uploaded_corp_identity_profile,
)

from .corp_identity.extraction import _build_ai_ready_corp_identity_template
from .corp_identity.parsing import (
    profile_root as _profile_root_impl,
)
from .corp_identity.parsing import (
    safe_upload_name as _safe_upload_name_impl,
)
from .corp_identity.parsing import (
    utc_now_iso as _utc_now_iso,
)
from .corp_identity.registry import (
    get_corp_identity_profile_detail as _get_corp_identity_profile_detail,
)
from .corp_identity.registry import (
    get_default_corp_identity_profile as _get_default_corp_identity_profile,
)
from .corp_identity.registry import (
    list_corp_identity_profiles as _list_corp_identity_profiles,
)
from .corp_identity.registry import (
    load_registry as _load_registry_impl,
)
from .corp_identity.registry import (
    save_registry as _save_registry_impl,
)
from .corp_identity.registry import (
    set_default_corp_identity_profile as _set_default_corp_identity_profile_impl,
)
from .corp_identity.templates import (
    resolve_corp_identity_office_template_path as _resolve_corp_identity_office_template_path,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
CORP_IDENTITY_ROOT = (WORKSPACE_ROOT / "uploads" / "corp-identities").resolve()


def _profile_root(profile_id: str) -> Path:
    return _profile_root_impl(CORP_IDENTITY_ROOT, profile_id)


def _safe_upload_name(name: str) -> str:
    return _safe_upload_name_impl(name)


async def resolve_corp_identity_template_path(
    db: AsyncSession,
    *,
    profile_id: str = "",
) -> tuple[Path, dict[str, Any]]:
    return await _resolve_corp_identity_office_template_path(
        doc_type="pptx",
        profile_id=profile_id,
        get_profile_detail=lambda current_profile_id: get_corp_identity_profile_detail(db, current_profile_id),
        get_default_profile=lambda: get_default_corp_identity_profile(db),
    )


async def resolve_corp_identity_office_template_path(
    db: AsyncSession,
    *,
    doc_type: str,
    profile_id: str = "",
) -> tuple[Path, dict[str, Any]]:
    return await _resolve_corp_identity_office_template_path(
        doc_type=doc_type,
        profile_id=profile_id,
        get_profile_detail=lambda current_profile_id: get_corp_identity_profile_detail(db, current_profile_id),
        get_default_profile=lambda: get_default_corp_identity_profile(db),
    )


def resolve_corp_identity_composer_template(profile: dict[str, Any]) -> ResolvedTemplate:
    # A derivative that is not current is never silently substituted: the original comes back with the reason.
    return _resolve_template_for_profile(profile)


async def get_corp_identity_profile_detail(db: AsyncSession, profile_id: str) -> dict[str, Any]:
    return await _get_corp_identity_profile_detail(
        db,
        profile_id,
        build_ai_ready_template=_build_ai_ready_corp_identity_template,
        utc_now_iso=_utc_now_iso,
    )


async def get_default_corp_identity_profile(db: AsyncSession) -> dict[str, Any] | None:
    return await _get_default_corp_identity_profile(
        db,
        get_profile_detail=lambda current_profile_id: get_corp_identity_profile_detail(db, current_profile_id),
    )


async def list_corp_identity_profiles(db: AsyncSession) -> dict[str, Any]:
    return await _list_corp_identity_profiles(db)


async def _load_registry(db: AsyncSession) -> list[dict[str, Any]]:
    return await _load_registry_impl(db)


async def _save_registry(db: AsyncSession, profiles: list[dict[str, Any]]) -> None:
    await _save_registry_impl(db, profiles)


async def save_uploaded_corp_identity_profile(
    db: AsyncSession,
    *,
    file_name: str,
    file_bytes: bytes,
    merge_into_profile_id: str | None = None,
) -> dict[str, Any]:
    return await _save_uploaded_corp_identity_profile(
        db,
        file_name=file_name,
        file_bytes=file_bytes,
        merge_into_profile_id=merge_into_profile_id,
    )


async def reextract_corp_identity_profile(db: AsyncSession, profile_id: str) -> dict[str, Any]:
    return await _reextract_corp_identity_profile(db, profile_id)


async def attach_example_deck_to_corp_identity_profile(
    db: AsyncSession, *, profile_id: str, file_name: str, file_bytes: bytes
) -> dict[str, Any]:
    return await _attach_example_deck_to_corp_identity_profile(
        db, profile_id=profile_id, file_name=file_name, file_bytes=file_bytes
    )


async def clear_example_deck_from_corp_identity_profile(
    db: AsyncSession, *, profile_id: str
) -> dict[str, Any]:
    return await _clear_example_deck_from_corp_identity_profile(db, profile_id=profile_id)


async def set_default_corp_identity_profile(db: AsyncSession, profile_id: str) -> dict[str, Any]:
    return await _set_default_corp_identity_profile_impl(db, profile_id)

async def delete_corp_identity_template(
    db: AsyncSession,
    profile_id: str,
    template_id: str,
) -> dict[str, Any]:
    from .corp_identity.registry import load_registry, save_registry

    registry = await load_registry(db)
    index = next((idx for idx, item in enumerate(registry) if item.get("id") == profile_id), None)
    if index is None:
        raise FileNotFoundError(f"Profile '{profile_id}' not found")
    profile = registry[index]
    templates: dict[str, list[dict[str, Any]]] = dict(profile.get("templates") or {
        "pptx": [], "docx": [], "xlsx": [],
    })
    found = False
    for doc_type in templates:
        templates[doc_type] = [
            e for e in templates[doc_type]
            if str(e.get("template_id") or "") != template_id
        ]
        if len(templates[doc_type]) < len(list(profile.get("templates") or {}).get(doc_type, [])):
            found = True
    if not found:
        raise FileNotFoundError(f"Template '{template_id}' not found in profile '{profile_id}'")
    registry[index] = {**profile, "templates": templates}
    await save_registry(db, registry)
    return await list_corp_identity_profiles(db)


async def delete_corp_identity_profile(db: AsyncSession, profile_id: str) -> dict[str, Any]:
    from .corp_identity.registry import delete_corp_identity_profile as _delete

    return await _delete(db, profile_id)


__all__ = [
    "_load_registry",
    "_save_registry",
    "_safe_upload_name",
    "attach_example_deck_to_corp_identity_profile",
    "clear_example_deck_from_corp_identity_profile",
    "delete_corp_identity_profile",
    "delete_corp_identity_template",
    "get_corp_identity_profile_detail",
    "get_default_corp_identity_profile",
    "list_corp_identity_profiles",
    "reextract_corp_identity_profile",
    "resolve_corp_identity_composer_template",
    "resolve_corp_identity_office_template_path",
    "resolve_corp_identity_template_path",
    "save_uploaded_corp_identity_profile",
    "set_default_corp_identity_profile",
]
