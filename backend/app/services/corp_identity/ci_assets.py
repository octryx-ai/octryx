"""Extract a profile's brand assets — logos, icons, images — into one catalog."""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any

_ASSETS_DIRNAME = "ci-assets"
_RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".emf", ".wmf", ".svg"}


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).name).strip("-")
    return stem or "asset"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _header_referenced_media(archive: zipfile.ZipFile) -> set[str]:
    referenced: set[str] = set()
    for name in archive.namelist():
        if not re.match(r"word/_rels/header\d+\.xml\.rels$", name):
            continue
        text = archive.read(name).decode("utf-8", "ignore")
        for target in re.findall(r'Target="([^"]*media/[^"]+)"', text):
            referenced.add(Path(target).name)
    return referenced


def _write_asset(dest_dir: Path, file_name: str, data: bytes, seen: dict[str, Path]) -> Path:
    digest = _sha(data)
    if digest in seen:
        return seen[digest]
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / _safe_name(file_name)
    counter = 2
    while target.exists() and target.read_bytes() != data:
        target = dest_dir / f"{Path(_safe_name(file_name)).stem}-{counter}{target.suffix}"
        counter += 1
    if not target.exists():
        target.write_bytes(data)
    seen[digest] = target
    return target


def _asset_record(profile_root: Path, path: Path, *, kind: str, medium: str, source_file: str) -> dict[str, Any]:
    return {
        "name": path.stem,
        "kind": kind,
        "medium": medium,
        "format": path.suffix.lstrip(".").lower(),
        "source_file": source_file,
        "path": str(path.relative_to(profile_root)),
    }


def _extract_document_assets(
    profile_root: Path, doc_path: Path, seen: dict[str, Path]
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(doc_path) as archive:
            logos = _header_referenced_media(archive)
            media = [n for n in archive.namelist() if n.startswith("word/media/")]
            for name in sorted(media):
                if Path(name).suffix.lower() not in _RASTER_SUFFIXES:
                    continue
                data = archive.read(name)
                written = _write_asset(profile_root / _ASSETS_DIRNAME / "documents", Path(name).name, data, seen)
                kind = "logo" if Path(name).name in logos else "image"
                assets.append(_asset_record(profile_root, written, kind=kind, medium="document", source_file=doc_path.name))
    except (OSError, zipfile.BadZipFile):
        return assets
    return assets


def _extract_presentation_images(
    profile_root: Path, pptx_path: Path, seen: dict[str, Path]
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(pptx_path) as archive:
            master_refs = _master_referenced_media(archive)
            for name in sorted(n for n in archive.namelist() if n.startswith("ppt/media/")):
                suffix = Path(name).suffix.lower()
                if suffix not in _RASTER_SUFFIXES or suffix == ".svg":
                    continue
                data = archive.read(name)
                written = _write_asset(profile_root / _ASSETS_DIRNAME / "presentations", Path(name).name, data, seen)
                kind = "logo" if Path(name).name in master_refs else "image"
                assets.append(_asset_record(profile_root, written, kind=kind, medium="presentation", source_file=pptx_path.name))
    except (OSError, zipfile.BadZipFile):
        return assets
    return assets


def _master_referenced_media(archive: zipfile.ZipFile) -> set[str]:
    referenced: set[str] = set()
    for name in archive.namelist():
        if not re.match(r"ppt/slideMasters/_rels/slideMaster\d+\.xml\.rels$", name):
            continue
        text = archive.read(name).decode("utf-8", "ignore")
        for target in re.findall(r'Target="([^"]*media/[^"]+)"', text):
            referenced.add(Path(target).name)
    return referenced


def _icon_assets(icon_catalog: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    categories = icon_catalog.get("categories") if isinstance(icon_catalog, dict) else None
    if not isinstance(categories, dict):
        return assets
    for category, items in categories.items():
        for item in items if isinstance(items, list) else []:
            named_path = str((item or {}).get("named_path") or "").strip()
            if not named_path:
                continue
            assets.append(
                {
                    "name": str((item or {}).get("name") or (item or {}).get("slug") or ""),
                    "kind": "icon",
                    "medium": "presentation",
                    "format": "svg",
                    "category": str(category),
                    "source_file": "icon catalog",
                    "path": named_path,
                }
            )
    return assets


def extract_ci_assets(
    profile_root: str | Path,
    *,
    presentation_paths: list[str] | None = None,
    document_paths: list[str] | None = None,
    icon_catalog: dict[str, Any] | None = None,
    max_icons: int = 400,
) -> dict[str, Any]:
    root = Path(profile_root).expanduser()
    seen: dict[str, Path] = {}
    logos: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []

    for path in document_paths or []:
        for asset in _extract_document_assets(root, Path(path), seen):
            (logos if asset["kind"] == "logo" else images).append(asset)
    for path in presentation_paths or []:
        for asset in _extract_presentation_images(root, Path(path), seen):
            (logos if asset["kind"] == "logo" else images).append(asset)

    icons = _icon_assets(icon_catalog or {})[:max_icons]
    icon_total = len(_icon_assets(icon_catalog or {}))
    return {
        "logos": logos,
        "images": images,
        "icons": icons,
        "counts": {
            "logos": len(logos),
            "images": len(images),
            "icons": icon_total,
            "icons_listed": len(icons),
        },
    }


__all__ = ["extract_ci_assets"]
