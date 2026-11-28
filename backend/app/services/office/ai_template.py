"""Build AI-ready presentation templates: an empty deck on the template's layouts plus role and asset catalogs."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.services.office_ai_template.assets import _enrich_manifest_assets
from app.services.office_ai_template.presentation import (
    _convert_pptx_to_potx,
    _layout_inventory,
    _strip_presentation_slides,
)

# Placeholder type of a layout -> the content field a role fills in it.
_PLACEHOLDER_FIELDS = {
    "title": "title",
    "ctrTitle": "title",
    "subTitle": "subtitle",
    "pic": "image",
    "body": "body",
    "obj": "body",
}


def _role_key(layout_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", layout_name.lower()).strip("_") or "layout"


def _inventory_roles(layout_inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []
    for item in layout_inventory:
        layout_name = str(item.get("layout_name") or "").strip()
        if not layout_name:
            continue
        placeholders = item.get("placeholders", [])
        fields = sorted({_PLACEHOLDER_FIELDS.get(str(ph.get("type") or ""), "body") for ph in placeholders})
        roles.append({
            "role": _role_key(layout_name),
            "layout_name": layout_name,
            "usage": f"Slides built on the template layout '{layout_name}'.",
            "fields": fields,
        })
    return roles


def _layout_role_matrix(
    *,
    source: Path,
    working_pptx: Path,
    ai_potx: Path,
    roles: list[dict[str, Any]],
    layout_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    role_matrix: list[dict[str, Any]] = []
    _strip_presentation_slides(source, working_pptx)
    _convert_pptx_to_potx(working_pptx, ai_potx)
    for role in roles:
        layout_name = str(role.get("layout_name") or "").strip()
        layout_entry = layout_map.get(layout_name)
        if layout_entry is None:
            raise ValueError(f"layout not found in template: {layout_name}")
        role_matrix.append(
            {
                **role,
                "layout_placeholders": layout_entry.get("placeholders", []),
                "reference_slide_number": int(role.get("source_slide_number") or 0),
            }
        )
    return role_matrix


def _asset_catalog(
    manifest: dict[str, Any],
    *,
    extracted_root: Path,
    roles: list[dict[str, Any]],
    source: Path,
) -> dict[str, Any]:
    manifest_assets = manifest.get("assets", [])
    enriched_assets = _enrich_manifest_assets(extracted_root, manifest_assets, roles, source)
    return {
        "theme_colors": manifest.get("theme_colors", {}),
        "vector_assets": [item for item in enriched_assets if item.get("category") == "vector"],
        "raster_assets": [item for item in enriched_assets if item.get("category") == "raster"],
    }


def _write_catalogs(
    *,
    output_dir: Path,
    extracted_root: Path,
    role_matrix: list[dict[str, Any]],
    asset_catalog: dict[str, Any],
    layout_inventory: list[dict[str, Any]],
) -> tuple[Path, Path, Path]:
    role_matrix_path = output_dir / "role-matrix.json"
    asset_catalog_path = output_dir / "asset-catalog.json"
    named_icon_catalog_source = extracted_root / "icons" / "catalog.json"
    named_icon_catalog_path = output_dir / "icon-catalog.json"
    named_icon_dir_source = extracted_root / "icons"
    named_icon_dir_target = output_dir / "icons"
    layout_inventory_path = output_dir / "layout-inventory.json"
    role_matrix_path.write_text(json.dumps(role_matrix, indent=2, ensure_ascii=False), encoding="utf-8")
    asset_catalog_path.write_text(json.dumps(asset_catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    if named_icon_catalog_source.exists():
        named_icon_catalog_path.write_text(named_icon_catalog_source.read_text(encoding="utf-8"), encoding="utf-8")
    if named_icon_dir_source.exists():
        if named_icon_dir_target.exists():
            shutil.rmtree(named_icon_dir_target)
        shutil.copytree(named_icon_dir_source, named_icon_dir_target)
    layout_inventory_path.write_text(json.dumps(layout_inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    return role_matrix_path, asset_catalog_path, layout_inventory_path


def _readme_text(
    *,
    source: Path,
    working_pptx: Path,
    ai_potx: Path,
    roles: list[dict[str, Any]],
    role_matrix: list[dict[str, Any]],
) -> str:
    return (
        "\n".join(
            [
                f"# {source.stem} AI Template",
                "",
                f"- Source template: `{source}`",
                f"- Working presentation: `{working_pptx}`",
                f"- AI template: `{ai_potx}`",
                "- Base deck: no retained showcase slides; slides are created from official layouts.",
                "",
                "## Roles",
                *[f"- `{item['role']}` -> layout `{item['layout_name']}`" for item in role_matrix],
                "",
                "## Notes",
                "- This AI template keeps the corporate masters, layouts, theme and assets.",
                "- The deck starts empty so generated presentations cannot inherit showcase text.",
                "- Slides are created from official layouts and then enriched with indexed corporate SVG assets.",
                "- Brand assets remain available through the extracted asset catalog.",
            ]
        )
        + "\n"
    )


def build_ai_ready_presentation_template(
    *,
    source_template: str | Path,
    extracted_package_root: str | Path,
    output_root: str | Path,
    role_definitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source = Path(source_template).expanduser().resolve()
    extracted_root = Path(extracted_package_root).expanduser().resolve()
    output_dir = Path(output_root).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = extracted_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(str(manifest_path))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    layout_inventory = _layout_inventory(source)
    layout_map = {
        str(item.get("layout_name") or "").strip(): item
        for item in layout_inventory
        if str(item.get("layout_name") or "").strip()
    }

    roles = role_definitions or _inventory_roles(layout_inventory)
    unnamed = [str(role.get("role") or "") for role in roles if not str(role.get("layout_name") or "").strip()]
    if unnamed:
        raise ValueError(f"role definitions without a layout_name: {', '.join(unnamed)}")

    working_pptx = output_dir / f"{source.stem}-ai.pptx"
    ai_potx = output_dir / f"{source.stem}-ai.potx"
    decks = {"source": source, "working_pptx": working_pptx, "ai_potx": ai_potx, "roles": roles}
    role_matrix = _layout_role_matrix(**decks, layout_map=layout_map)

    asset_catalog = _asset_catalog(manifest, extracted_root=extracted_root, roles=roles, source=source)
    role_matrix_path, asset_catalog_path, layout_inventory_path = _write_catalogs(
        output_dir=output_dir,
        extracted_root=extracted_root,
        role_matrix=role_matrix,
        asset_catalog=asset_catalog,
        layout_inventory=layout_inventory,
    )
    readme = output_dir / "README.md"
    readme.write_text(_readme_text(**decks, role_matrix=role_matrix), encoding="utf-8")

    return {
        "working_pptx": str(working_pptx),
        "ai_potx": str(ai_potx),
        "role_matrix_path": str(role_matrix_path),
        "asset_catalog_path": str(asset_catalog_path),
        "layout_inventory_path": str(layout_inventory_path),
        "role_matrix": role_matrix,
    }
