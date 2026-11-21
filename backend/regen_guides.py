#!/usr/bin/env python3
"""
Standalone script to:
1. Rebuild the lean AI template for each corp identity profile
2. Regenerate all LLM guides using the lean template's slide indices

Run from the backend/ directory:
  python3 regen_guides.py
  python3 regen_guides.py --no-rebuild   # skip lean template rebuild, just regen guides
"""
import argparse
import json
import sys
from pathlib import Path

# Add backend to Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.corp_identity.guide import generate_llm_guide
from app.services.corp_identity.icons import extract_icon_catalog
from app.services.corp_identity.layouts import extract_layout_catalog, extract_slide_dimensions, extract_theme
from app.services.corp_identity_service import CORP_IDENTITY_ROOT
from app.services.lean_template_builder import build_lean_ai_template


def regen_profile(profile_dir: Path, rebuild_lean: bool = True) -> str:
    extracted_root = profile_dir / "_extracted"
    if not extracted_root.exists():
        return "SKIP (no _extracted)"

    brand_profile_path = profile_dir / "brand-profile.json"
    layout_catalog_path = profile_dir / "layout-catalog.json"
    icon_catalog_path = profile_dir / "icon-catalog.json"

    # Always re-extract layout catalog (picks up example_slide_index fix)
    brand = extract_theme(extracted_root)
    slide_dims = extract_slide_dimensions(extracted_root)
    layout_catalog = extract_layout_catalog(extracted_root, brand, slide_dims)
    layout_catalog_path.write_text(json.dumps(layout_catalog, indent=2), encoding="utf-8")

    if icon_catalog_path.exists():
        icon_catalog = json.loads(icon_catalog_path.read_text(encoding="utf-8"))
    else:
        icon_catalog = extract_icon_catalog(extracted_root, profile_dir)
        icon_catalog_path.write_text(json.dumps(icon_catalog, indent=2), encoding="utf-8")

    summary: dict = {}
    if brand_profile_path.exists():
        brand_profile = json.loads(brand_profile_path.read_text(encoding="utf-8"))
        summary = brand_profile.get("summary", {})
        summary["profile_root"] = str(profile_dir)

    # Try to build / use lean template
    lean_slide_map: dict[str, int] = {}
    lean_info = ""

    if rebuild_lean:
        source_dir = profile_dir / "source"
        source_files = list(source_dir.glob("*.potx")) + list(source_dir.glob("*.pptx")) if source_dir.exists() else []
        if source_files:
            source_path = source_files[0]
            ai_root = profile_dir / "ai-template"
            ai_root.mkdir(parents=True, exist_ok=True)
            stem = source_path.stem
            output_pptx = ai_root / f"{stem}-ai.pptx"
            output_potx = ai_root / f"{stem}-ai.potx"
            try:
                result = build_lean_ai_template(source_path, output_pptx, output_potx)
                lean_slide_map = result.get("example_slide_map", {})
                example_map_path = ai_root / "example-slide-map.json"
                example_map_path.write_text(json.dumps(lean_slide_map, indent=2), encoding="utf-8")
                lean_info = f" lean={result['size_mb']}MB({result['slide_count']}slides)"
            except Exception as e:
                lean_info = f" lean=ERR({e})"
        else:
            # Try loading existing lean map
            existing_map = profile_dir / "ai-template" / "example-slide-map.json"
            if existing_map.exists():
                lean_slide_map = json.loads(existing_map.read_text())
                lean_info = " lean=cached"
    else:
        existing_map = profile_dir / "ai-template" / "example-slide-map.json"
        if existing_map.exists():
            lean_slide_map = json.loads(existing_map.read_text())
            lean_info = " lean=cached"

    guide = generate_llm_guide(summary, layout_catalog, icon_catalog, lean_slide_map)
    (profile_dir / "llm-guide.md").write_text(guide, encoding="utf-8")
    return f"OK ({len(guide)//1024}KB){lean_info}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-rebuild", action="store_true", help="Skip lean template rebuild")
    args = parser.parse_args()

    profiles = sorted(CORP_IDENTITY_ROOT.iterdir())
    print(f"Found {len(profiles)} profiles in {CORP_IDENTITY_ROOT}")
    for profile_dir in profiles:
        if not profile_dir.is_dir():
            continue
        status = regen_profile(profile_dir, rebuild_lean=not args.no_rebuild)
        print(f"  {profile_dir.name[:32]}: {status}")
    print("Done.")


if __name__ == "__main__":
    main()
