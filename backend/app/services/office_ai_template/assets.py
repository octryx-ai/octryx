"""Asset enrichment helpers for AI-ready Office templates."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from app.services.office_ai_template.presentation import PRESENTATION_REL_NS
from app.services.office_template_package.assets import _asset_index_entry


def _slide_media_targets(source: Path) -> dict[int, set[str]]:
    targets_by_slide: dict[int, set[str]] = {}
    with zipfile.ZipFile(source) as src:
        for name in src.namelist():
            if not name.startswith("ppt/slides/_rels/slide") or not name.endswith(".xml.rels"):
                continue
            stem = Path(name).stem
            digits = "".join(ch for ch in stem if ch.isdigit())
            if not digits:
                continue
            slide_number = int(digits)
            root = ET.fromstring(src.read(name))
            targets: set[str] = set()
            for rel in root.findall(f"{{{PRESENTATION_REL_NS}}}Relationship"):
                target = str(rel.attrib.get("Target") or "").strip()
                if "../media/" in target:
                    targets.add(Path(target).name)
            if targets:
                targets_by_slide[slide_number] = targets
    return targets_by_slide


def _enrich_manifest_assets(
    extracted_root: Path,
    manifest_assets: list[dict[str, Any]],
    roles: list[dict[str, Any]],
    source: Path,
) -> list[dict[str, Any]]:
    slide_media = _slide_media_targets(source)
    role_media: dict[str, set[str]] = {}
    for role in roles:
        role_name = str(role.get("role") or "").strip()
        slide_number = int(role.get("source_slide_number") or 0)
        if role_name and slide_number > 0 and slide_number in slide_media:
            role_media[role_name] = set(slide_media[slide_number])

    enriched: list[dict[str, Any]] = []
    for raw_item in manifest_assets:
        item = dict(raw_item)
        path = Path(str(item.get("path") or "")).expanduser()
        if not path.exists():
            alt_path = extracted_root / "assets" / "media" / path.name
            if alt_path.exists():
                path = alt_path
                item["path"] = str(path)
        category = str(item.get("category") or "").strip() or "binary"
        file_name = str(item.get("file_name") or path.name)
        if path.exists():
            item.update(_asset_index_entry(path, category=category))
        preferred_roles = {str(role).strip() for role in item.get("preferred_roles") or [] if str(role).strip()}
        for role_name, media_names in role_media.items():
            if file_name in media_names:
                preferred_roles.add(role_name)
        if preferred_roles:
            item["preferred_roles"] = sorted(preferred_roles)
        enriched.append(item)
    return enriched
