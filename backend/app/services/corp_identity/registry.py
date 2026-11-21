"""Registry helpers for corporate identity profiles."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..system_config import get_system_config_value, set_system_config_value
from .normalized_template_manifest import NORMALIZATION_MANIFEST_NAME
from .registry_templates import _build_template_map
from .storage import describe_profile_storage_lifecycle
from .templates import CORP_IDENTITY_TEMPLATE_SUFFIXES

CORP_IDENTITY_REGISTRY_KEY = "agent.corp_identity_registry"
CORP_IDENTITY_DEFAULT_PROFILE_KEY = "agent.corp_identity_default_profile_id"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _profile_root_exists(profile: dict[str, Any]) -> bool:
    profile_root = Path(str(profile.get("profile_root") or "")).expanduser()
    return profile_root.exists() and profile_root.is_dir()


def _content_identity_kind_for_suffix(suffix: str) -> str:
    normalized = str(suffix or "").lower()
    if normalized in CORP_IDENTITY_TEMPLATE_SUFFIXES["pptx"]:
        return "pptx"
    if normalized in CORP_IDENTITY_TEMPLATE_SUFFIXES["docx"]:
        return "docx"
    if normalized in CORP_IDENTITY_TEMPLATE_SUFFIXES["xlsx"]:
        return "xlsx"
    return "unknown"


def build_source_content_identity(*, file_name: str, file_bytes: bytes) -> str:
    suffix = Path(file_name or "template.bin").suffix.lower()
    digest = hashlib.sha256(file_bytes).hexdigest()
    return f"sha256:{_content_identity_kind_for_suffix(suffix)}:{len(file_bytes)}:{digest}"


async def find_profile_by_source_content_identity(
    db: AsyncSession,
    content_identity: str,
) -> dict[str, Any] | None:
    """The stored profile whose upload had these exact bytes (``source_content_identity``, set by every upload)."""
    for item in await load_registry(db):
        if str(item.get("source_content_identity") or "").strip() == content_identity and _profile_root_exists(item):
            return item
    return None


async def load_registry(db: AsyncSession) -> list[dict[str, Any]]:
    raw = await get_system_config_value(db, CORP_IDENTITY_REGISTRY_KEY)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


async def save_registry(db: AsyncSession, profiles: list[dict[str, Any]]) -> None:
    await set_system_config_value(
        db,
        key=CORP_IDENTITY_REGISTRY_KEY,
        value=json.dumps(profiles, ensure_ascii=False),
        description="Corporate identity profiles and Office templates for PPTX, DOCX, and XLSX generation.",
    )


async def ensure_ai_ready_profile_assets(
    db: AsyncSession,
    profile: dict[str, Any],
    *,
    build_ai_ready_template: Callable[[Path, Path], dict[str, str]],
    utc_now_iso: Callable[[], str],
) -> dict[str, Any]:
    ai_template_path = Path(str(profile.get("ai_template_path") or "")).expanduser()
    if ai_template_path.exists() and ai_template_path.is_file():
        return profile
    source_path = Path(str(profile.get("source_path") or "")).expanduser()
    profile_root = Path(str(profile.get("profile_root") or "")).expanduser()
    if not source_path.exists() or not source_path.is_file():
        return profile
    if source_path.suffix.lower() not in {".potx", ".pptx"}:
        return profile
    ai_ready = build_ai_ready_template(source_path, profile_root)
    updated_profile = {
        **profile,
        "updated_at": utc_now_iso(),
        "ai_template_path": ai_ready["ai_template_path"],
        "ai_pptx_path": ai_ready.get("ai_pptx_path", ""),
        "example_slide_map_path": ai_ready.get("example_slide_map_path", ""),
        "ai_slide_count": ai_ready.get("slide_count", 0),
        "ai_layout_count": ai_ready.get("layout_count", 0),
        "ai_size_mb": ai_ready.get("size_mb", 0),
    }
    registry = await load_registry(db)
    changed = False
    for index, item in enumerate(registry):
        if str(item.get("id") or "") != str(profile.get("id") or ""):
            continue
        registry[index] = updated_profile
        changed = True
        break
    if changed:
        await save_registry(db, registry)
        await db.commit()
    return updated_profile


async def list_corp_identity_profiles(db: AsyncSession) -> dict[str, Any]:
    profiles = await load_registry(db)
    default_profile_id = str(await get_system_config_value(db, CORP_IDENTITY_DEFAULT_PROFILE_KEY) or "").strip()
    items: list[dict[str, Any]] = []
    changed = False
    for item in profiles:
        profile_root = Path(str(item.get("profile_root") or "")).expanduser()
        if not profile_root.exists():
            changed = True
            continue
        templates = _build_template_map(item, profile_root)
        items.append({
            **item,
            "is_default": str(item.get("id") or "") == default_profile_id,
            "templates": templates,
        })
    if changed:
        await save_registry(db, items)
    if default_profile_id and not any(item["id"] == default_profile_id for item in items):
        await set_system_config_value(
            db,
            key=CORP_IDENTITY_DEFAULT_PROFILE_KEY,
            value=(items[0]["id"] if items else None),
            description="Default corporate identity profile.",
        )
        default_profile_id = items[0]["id"] if items else ""
    return {"profiles": items, "default_profile_id": default_profile_id}


async def get_corp_identity_profile_detail(
    db: AsyncSession,
    profile_id: str,
    *,
    build_ai_ready_template: Callable[[Path, Path], dict[str, str]],
    utc_now_iso: Callable[[], str],
) -> dict[str, Any]:
    payload = await list_corp_identity_profiles(db)
    profile = next((item for item in payload["profiles"] if item["id"] == profile_id), None)
    if profile is None:
        raise FileNotFoundError(profile_id)
    profile = await ensure_ai_ready_profile_assets(
        db,
        profile,
        build_ai_ready_template=build_ai_ready_template,
        utc_now_iso=utc_now_iso,
    )
    profile_root = Path(str(profile.get("profile_root") or "")).expanduser()
    return {
        **profile,
        "brand_profile": _read_json(profile_root / "brand-profile.json", {}),
        "layout_catalog": _read_json(profile_root / "layout-catalog.json", {}),
        "icon_catalog": _read_json(profile_root / "icon-catalog.json", {}),
        "guide_markdown": _read_text(profile_root / "llm-guide.md"),
        "normalization": _read_json(profile_root / NORMALIZATION_MANIFEST_NAME, {}),
        "storage_lifecycle": describe_profile_storage_lifecycle(profile),
    }


async def get_default_corp_identity_profile(
    db: AsyncSession,
    *,
    get_profile_detail: Callable[[str], Awaitable[dict[str, Any]]],
) -> dict[str, Any] | None:
    payload = await list_corp_identity_profiles(db)
    default_profile_id = str(payload.get("default_profile_id") or "").strip()
    if not default_profile_id:
        return None
    profile = next((item for item in payload["profiles"] if item["id"] == default_profile_id), None)
    if profile is None:
        return None
    return await get_profile_detail(default_profile_id)


async def set_default_corp_identity_profile(db: AsyncSession, profile_id: str) -> dict[str, Any]:
    payload = await list_corp_identity_profiles(db)
    if not any(item["id"] == profile_id for item in payload["profiles"]):
        raise FileNotFoundError(profile_id)
    await set_system_config_value(
        db,
        key=CORP_IDENTITY_DEFAULT_PROFILE_KEY,
        value=profile_id,
        description="Default corporate identity profile.",
    )
    return await list_corp_identity_profiles(db)


async def delete_corp_identity_profile(db: AsyncSession, profile_id: str) -> dict[str, Any]:
    payload = await list_corp_identity_profiles(db)
    profiles = payload["profiles"]
    profile = next((item for item in profiles if item["id"] == profile_id), None)
    if profile is None:
        raise FileNotFoundError(profile_id)
    profile_root = Path(str(profile.get("profile_root") or "")).expanduser()
    if profile_root.exists():
        shutil.rmtree(profile_root)
    remaining = [item for item in profiles if item["id"] != profile_id]
    await save_registry(db, remaining)
    default_profile_id = str(await get_system_config_value(db, CORP_IDENTITY_DEFAULT_PROFILE_KEY) or "").strip()
    if default_profile_id == profile_id:
        await set_system_config_value(
            db,
            key=CORP_IDENTITY_DEFAULT_PROFILE_KEY,
            value=(remaining[0]["id"] if remaining else None),
            description="Default corporate identity profile.",
        )
    return await list_corp_identity_profiles(db)
