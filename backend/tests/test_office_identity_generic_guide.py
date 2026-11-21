"""The corporate identity guide and the template-package icon catalog are structure first.

The guide's layout hints, its "when to use which layout" table and its worked
example must name the template's *own* layouts, chosen by structure — on the
synthetic brand template, python-pptx's default template and a template whose
layouts are only called "Layout 1…n". The template-package icon catalog must
name icons the way the corporate identity extraction does: ``ICO_`` caption by
distance, alt text, shape name, telling file name.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.services.corp_identity.guide import build_identity_summary, generate_llm_guide
from app.services.corp_identity.icons import extract_icon_catalog
from app.services.corp_identity.layouts import extract_layout_catalog, extract_slide_dimensions
from app.services.office_template_package.icons import _copy_named_icon_catalog
from tests.office_generic_templates_support import TEMPLATE_NAMES, write_named_template

#: name of the cover, the divider and the icon topics layout per template —
#: what the guide has to pick by structure.
EXPECTED = {
    "brand": ("Title Slide", "Section Header", "Icons 3 Topics"),
    "default": ("Title Slide", "Section Header", None),
    "neutral": ("Layout 1", "Layout 5", "Layout 8"),
}


def _extract(directory: Path, name: str) -> Path:
    extracted = directory / "extracted"
    with zipfile.ZipFile(write_named_template(directory, name)) as archive:
        archive.extractall(extracted)
    return extracted


@pytest.fixture(scope="module", params=TEMPLATE_NAMES)
def guide(request, tmp_path_factory) -> tuple[str, dict[str, Any], str]:
    folder = tmp_path_factory.mktemp(f"guide-{request.param}")
    extracted = _extract(folder, request.param)
    catalog = extract_layout_catalog(extracted, {}, extract_slide_dimensions(extracted))
    icons = extract_icon_catalog(extracted, folder / "profile")
    summary = build_identity_summary(
        profile_id="p", name=request.param, source_file_name="t.potx", brand={},
        layout_catalog=catalog, icon_catalog=icons, profile_root=folder / "profile",
    )
    return request.param, catalog, generate_llm_guide(summary, catalog, icons)


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0] if heading in text else ""


def test_layout_categories_come_from_structure(guide):
    name, catalog, _text = guide
    by_name = {layout["name"]: layout for layout in catalog["layouts"]}
    cover, divider, icons = EXPECTED[name]
    assert by_name[cover]["category"] == "title"
    assert by_name[divider]["category"] == "section"
    if icons:
        assert by_name[icons]["content_shape"] == "icons_3"
        assert by_name[icons]["category"] == "icons"


def test_choice_table_names_only_this_templates_layouts(guide):
    name, catalog, text = guide
    table = _section(text, "## When to Use Which Layout")
    named = set(re.findall(r"`([^`]+)`", table))
    assert named and named <= {layout["name"] for layout in catalog["layouts"]}
    cover, divider, icons = EXPECTED[name]
    assert f"| Opening title slide | `{cover}`" in table
    assert f"`{divider}`" in _line(table, "| Chapter divider |")
    if icons:
        assert f"`{icons}`" in _line(table, "| Visual topics with icons |")
    else:
        assert "Visual topics with icons" not in table


def _line(block: str, prefix: str) -> str:
    return next((line for line in block.splitlines() if line.startswith(prefix)), "")


def test_layout_hints_describe_structure(guide):
    name, _catalog, text = guide
    reference = _section(text, "## Full Layout Reference")
    cover, divider, icons = EXPECTED[name]
    assert f"### `{cover}`\n*opening cover slide*" in reference
    assert f"### `{divider}`\n*chapter / section divider*" in reference
    if icons:
        assert f"### `{icons}`\n*3 visual topics with icon + heading + body*" in reference


def test_worked_example_uses_this_templates_layouts(guide):
    name, catalog, text = guide
    example = _section(text, "## Worked Example")
    cloned = set(re.findall(r'# clone "([^"]+)"|"layout": "([^"]+)"', example))
    used = {value for pair in cloned for value in pair if value}
    assert used <= {layout["name"] for layout in catalog["layouts"]}
    cover, divider, _icons = EXPECTED[name]
    assert cover in used and divider in used
    samples = catalog["summary"]["sample_slide_count"]
    assert f"remove the {samples} template example slides" in example


@pytest.mark.parametrize("name", ["library", "neutral", "brand", "default"])
def test_template_package_icons_match_corporate_identity_naming(name, tmp_path):
    extracted = _extract(tmp_path, name)
    package = _copy_named_icon_catalog(tmp_path / "package", extracted)
    named = {icon["name"] for icon in package["named_icons"]}
    unlabeled = {icon["file"] for icon in package["unlabeled_icons"]}
    if name == "library":
        assert {"ICO_Server", "ICO_Shield", "ICO_Networks"} <= named
        assert unlabeled == {"image9.svg"}
        assert set(package["categories"]) == {"Security", "Technology"}
    elif name == "neutral":
        assert named == {"Shield", "Globe", "padlock", "Server rack"}
        assert unlabeled == set() and set(package["categories"]) == {"General"}
    else:
        assert named == set() and unlabeled == set()
    corp = extract_icon_catalog(extracted, tmp_path / "profile")
    corp_names = {item["name"] for items in corp["categories"].values() for item in items}
    assert named <= corp_names
