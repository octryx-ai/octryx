"""Candidate detection for safe backend disk hygiene."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..corp_identity.registry import load_registry
from ..corp_identity.storage import describe_profile_storage_lifecycle
from ..office.documents import get_office_template_library

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORP_IDENTITY_ROOT = (REPO_ROOT / "uploads" / "corp-identities").resolve()
DEFAULT_OFFICE_TEMPLATE_IMPORT_ROOT = (REPO_ROOT / "uploads" / "office-templates" / "imports").resolve()
DEFAULT_CORP_IDENTITY_CACHE_MIN_AGE_HOURS = 24
DEFAULT_OFFICE_IMPORT_STALE_MIN_AGE_HOURS = 72


@dataclass(frozen=True)
class DiskHygieneCandidate:
    kind: str
    path: Path
    bytes_used: int
    age_hours: float
    reason: str
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "bytes_used": self.bytes_used,
            "age_hours": round(self.age_hours, 2),
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


def _is_within_root(path: Path, root: Path) -> bool:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        try:
            total += child.stat().st_size
        except OSError:
            continue
    return total


def _age_hours(path: Path, *, now: datetime) -> float:
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return 0.0
    return max(0.0, (now - modified_at).total_seconds() / 3600.0)


def _corp_identity_cache_candidate(
    profile: dict[str, Any],
    *,
    root: Path,
    now: datetime,
    min_age_hours: int,
) -> DiskHygieneCandidate | None:
    lifecycle = describe_profile_storage_lifecycle(profile)
    if not lifecycle.get("reextract_supported"):
        return None
    extracted_entry = next(
        (entry for entry in lifecycle.get("rebuildable") or [] if str(entry.get("kind") or "") == "extracted_cache"),
        None,
    )
    if not extracted_entry:
        return None
    extracted_path = Path(str(extracted_entry.get("path") or "")).expanduser().resolve()
    if not extracted_path.exists() or not extracted_path.is_dir():
        return None
    if extracted_path.name != "_extracted" or not _is_within_root(extracted_path, root):
        return None
    candidate_age_hours = _age_hours(extracted_path, now=now)
    if candidate_age_hours < min_age_hours:
        return None
    source_path = Path(str(profile.get("source_path") or "")).expanduser()
    if not source_path.exists():
        return None
    return DiskHygieneCandidate(
        kind="corp_identity_extracted_cache",
        path=extracted_path,
        bytes_used=_directory_size_bytes(extracted_path),
        age_hours=candidate_age_hours,
        reason="Rebuildable corporate identity extraction cache older than retention threshold.",
        metadata={
            "profile_id": str(profile.get("id") or ""),
            "profile_name": str(profile.get("name") or ""),
            "source_path": str(source_path.resolve()),
        },
    )


def _referenced_office_package_roots(library: list[dict[str, Any]], *, import_root: Path) -> set[Path]:
    referenced: set[Path] = set()
    for entry in library:
        storage_contract = entry.get("storage_contract")
        if not isinstance(storage_contract, dict):
            continue
        package_root_raw = str(storage_contract.get("package_root") or "").strip()
        if not package_root_raw:
            continue
        package_root = Path(package_root_raw).expanduser().resolve()
        if package_root.exists() and package_root.is_dir() and _is_within_root(package_root, import_root):
            referenced.add(package_root)
    return referenced


def _office_import_candidate(
    package_root: Path,
    *,
    now: datetime,
    min_age_hours: int,
) -> DiskHygieneCandidate | None:
    if not package_root.exists() or not package_root.is_dir():
        return None
    candidate_age_hours = _age_hours(package_root, now=now)
    if candidate_age_hours < min_age_hours:
        return None
    return DiskHygieneCandidate(
        kind="office_template_import_package",
        path=package_root,
        bytes_used=_directory_size_bytes(package_root),
        age_hours=candidate_age_hours,
        reason="Unreferenced Office template import package older than retention threshold.",
        metadata={"package_name": package_root.name},
    )


async def collect_disk_hygiene_candidates(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    corp_identity_root: Path | None = None,
    office_import_root: Path | None = None,
    corp_identity_cache_min_age_hours: int = DEFAULT_CORP_IDENTITY_CACHE_MIN_AGE_HOURS,
    office_import_stale_min_age_hours: int = DEFAULT_OFFICE_IMPORT_STALE_MIN_AGE_HOURS,
    include_corp_identity_candidates: bool = True,
    include_office_import_candidates: bool = True,
    excluded_corp_identity_profile_ids: set[str] | None = None,
) -> list[DiskHygieneCandidate]:
    current_time = now or datetime.now(tz=UTC)
    corp_root = (corp_identity_root or DEFAULT_CORP_IDENTITY_ROOT).expanduser().resolve()
    import_root = (office_import_root or DEFAULT_OFFICE_TEMPLATE_IMPORT_ROOT).expanduser().resolve()
    candidates: list[DiskHygieneCandidate] = []
    excluded_profile_ids = {
        str(profile_id).strip()
        for profile_id in (excluded_corp_identity_profile_ids or set())
        if str(profile_id).strip()
    }

    if include_corp_identity_candidates:
        for profile in await load_registry(db):
            if str(profile.get("id") or "").strip() in excluded_profile_ids:
                continue
            candidate = _corp_identity_cache_candidate(
                profile,
                root=corp_root,
                now=current_time,
                min_age_hours=corp_identity_cache_min_age_hours,
            )
            if candidate is not None:
                candidates.append(candidate)

    if include_office_import_candidates:
        library = await get_office_template_library(db=db, project_config=None)
        referenced_package_roots = _referenced_office_package_roots(library, import_root=import_root)
        if import_root.exists():
            for package_root in sorted(import_root.iterdir()):
                resolved = package_root.resolve()
                if (
                    not package_root.is_dir()
                    or resolved in referenced_package_roots
                    or not _is_within_root(resolved, import_root)
                ):
                    continue
                candidate = _office_import_candidate(
                    resolved,
                    now=current_time,
                    min_age_hours=office_import_stale_min_age_hours,
                )
                if candidate is not None:
                    candidates.append(candidate)

    return sorted(candidates, key=lambda item: (item.kind, str(item.path)))


__all__ = [
    "DEFAULT_CORP_IDENTITY_CACHE_MIN_AGE_HOURS",
    "DEFAULT_OFFICE_IMPORT_STALE_MIN_AGE_HOURS",
    "DiskHygieneCandidate",
    "collect_disk_hygiene_candidates",
]
