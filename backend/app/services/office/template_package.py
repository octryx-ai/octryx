"""Extract reusable metadata and assets from Office template files."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from app.services.office_template_package.assets import _extract_media
from app.services.office_template_package.constants import OFFICE_TEMPLATE_SUFFIXES
from app.services.office_template_package.icons import _copy_named_icon_catalog
from app.services.office_template_package.xml import _layout_summaries, _slide_size, _slide_summaries, _theme_colors


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or "template"


def _recommendations(layouts: list[dict[str, Any]], slides: list[dict[str, Any]]) -> list[str]:
    recommendations = [
        "Use a dedicated automation template instead of a showcase deck with many sample slides.",
        "Define a small stable layout set for AI generation: title, section, content, two-column, closing.",
        "Ensure each automation layout has predictable title/body placeholders instead of freeform shapes only.",
        "Keep brand assets in reusable form and reference them from layouts instead of embedding them ad hoc per slide.",
    ]
    if len(slides) > 20:
        recommendations.append(
            "This template currently contains many example slides; consider a reduced AI-ready variant."
        )
    if len(layouts) > 10:
        recommendations.append(
            "The layout catalog is broad; define a curated subset and map them by key for automation."
        )
    return recommendations


def _prepare_package_root(source: Path, output_root: str | Path) -> tuple[Path, Path, Path]:
    package_root = Path(output_root).expanduser().resolve() / _slugify(source.stem)
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)

    source_dir = package_root / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    copied_template = source_dir / source.name
    shutil.copy2(source, copied_template)
    extracted_root = package_root / "_extracted"
    with zipfile.ZipFile(source) as zip_file:
        zip_file.extractall(extracted_root)
    return package_root, copied_template, extracted_root


def _tag_named_icons(media: dict[str, Any], icon_catalog: dict[str, Any], package_root: Path) -> None:
    named_icons_by_file = {
        str(item.get("original_file") or ""): item for group in icon_catalog["categories"].values() for item in group
    }
    for asset in media["all"]:
        named_icon = named_icons_by_file.get(str(asset.get("file_name") or ""))
        if named_icon is None:
            continue
        tags = set(asset.get("tags") or [])
        tags.add("icon")
        asset["tags"] = sorted(tags)
        asset["icon_name"] = named_icon.get("name")
        asset["icon_slug"] = named_icon.get("slug")
        asset["icon_category"] = (
            named_icon.get("named_path", "").split("/")[1] if "/" in str(named_icon.get("named_path") or "") else ""
        )
        asset["named_icon_path"] = str(package_root / str(named_icon.get("named_path") or ""))


def _readme_lines(manifest: dict[str, Any], *, source: Path, copied_template: Path) -> list[str]:
    return [
        f"# {source.stem}",
        "",
        f"- Source template: `{copied_template}`",
        f"- Document type: `{manifest['doc_type']}`",
        f"- Slide size: `{manifest['slide_size']}`",
        f"- Layout count: `{manifest['layout_count']}`",
        f"- Slide count: `{manifest['slide_count']}`",
        f"- Exported vector assets: `{manifest['vector_asset_count']}`",
        f"- Exported raster assets: `{manifest['raster_asset_count']}`",
        f"- Named icons: `{manifest['icon_count']}`",
        "",
        "## Recommendations",
        *[f"- {item}" for item in manifest["recommendations"]],
    ]


def extract_office_template_package(template_path: str | Path, output_root: str | Path) -> dict[str, Any]:
    source = Path(template_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))
    doc_type = OFFICE_TEMPLATE_SUFFIXES.get(source.suffix.lower())
    if doc_type is None:
        raise ValueError(f"unsupported template type: {source.suffix}")

    package_root, copied_template, extracted_root = _prepare_package_root(source, output_root)
    with zipfile.ZipFile(source) as zip_file:
        media = _extract_media(zip_file, package_root)
        theme_colors = _theme_colors(zip_file)
        slide_size = _slide_size(zip_file)
        layouts = _layout_summaries(zip_file)
        slides = _slide_summaries(zip_file)
    icon_catalog = _copy_named_icon_catalog(package_root, extracted_root)
    _tag_named_icons(media, icon_catalog, package_root)

    manifest = {
        "template_name": source.stem,
        "template_file": str(copied_template),
        "doc_type": doc_type,
        "package_root": str(package_root),
        "extracted_root": str(extracted_root),
        "slide_size": slide_size,
        "theme_colors": theme_colors,
        "layout_count": len(layouts),
        "slide_count": len(slides),
        "vector_asset_count": len(media["vector"]),
        "raster_asset_count": len(media["raster"]),
        "icon_count": icon_catalog["icon_count"],
        "icon_catalog_path": icon_catalog["catalog_path"],
        "icon_categories": sorted(icon_catalog["categories"].keys()),
        "layouts": layouts,
        "slides": slides,
        "assets": media["all"],
        "recommendations": _recommendations(layouts, slides),
    }

    (package_root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    readme_lines = _readme_lines(manifest, source=source, copied_template=copied_template)
    (package_root / "README.md").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")
    return manifest


__all__ = [
    "extract_office_template_package",
]
