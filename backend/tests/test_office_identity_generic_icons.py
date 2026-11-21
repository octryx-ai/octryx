"""Icons are catalogued from what the template says about them, on any slide.

The ``library`` template names its icons with ``ICO_`` captions on "Icons …"
slides; the ``neutral`` template has no captions and no "Icons" title — its
SVG pictures carry alt text, or only a telling media file name. Both must
yield a catalog the closed topic vocabulary can match, and the corporate
identity extraction must read the same names and the topic columns by geometry.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.services.corp_identity.icons import extract_icon_catalog
from app.services.corp_identity.layouts import extract_layout_catalog
from app.services.office_identity.aws_deck_plan import build_aws_deck_plan
from app.services.office_identity.icon_slots import select_icon
from app.services.office_identity.icon_topics import icon_words
from app.services.office_identity.layout_shapes import classify_layout
from app.services.office_identity.presentation_composer import build_presentation_from_plan
from app.services.office_identity.template_snapshot import build_template_snapshot
from tests.office_identity_aws_deck_plan_support import _aws_snapshot, _knowledge_facts
from tests.office_template_fixture import write_template


@pytest.fixture(scope="module")
def neutral(tmp_path_factory) -> tuple[Path, dict]:
    path = write_template(tmp_path_factory.mktemp("neutral") / "neutral.potx", "neutral")
    return path, build_template_snapshot(path)


@pytest.fixture(scope="module")
def library(tmp_path_factory) -> dict:
    return build_template_snapshot(write_template(tmp_path_factory.mktemp("library") / "lib.potx", "library"))


def test_icons_are_named_by_alt_text_or_file_name(neutral):
    _path, snapshot = neutral
    names = {icon["name"]: icon for icon in snapshot["icons"]}
    assert set(names) == {"Shield", "Globe", "padlock", "Server rack"}
    assert names["padlock"]["part"] == "ppt/media/padlock.svg"  # no alt text: file name
    assert all(icon["category"] == "General" for icon in snapshot["icons"])


def test_caption_names_still_win_on_a_captioned_library(library):
    slugs = {icon["slug"] for icon in library["icons"]}
    assert {"server", "cogs", "globe", "database", "shield", "lock", "networks"} <= slugs
    # the uncaptioned picture falls back to its media name
    assert "image9" in slugs
    assert {icon["category"] for icon in library["icons"]} == {"Security", "Technology"}


@pytest.mark.parametrize(
    ("topic", "neutral_name", "library_slug"),
    [
        ("security", "Shield", "shield"),
        ("regions", "Globe", "globe"),
        ("compute", "Server rack", "server"),
        ("network", "Globe", "networks"),
        ("data", "Server rack", "database"),
    ],
)
def test_topics_match_by_synonym_not_by_library_slug(neutral, library, topic, neutral_name, library_slug):
    assert select_icon(neutral[1], topic)["name"] == neutral_name
    assert select_icon(library, topic)["slug"] == library_slug


def test_security_falls_back_to_a_file_named_icon():
    catalog = {"icons": [{"slug": "padlock", "name": "padlock", "part": "ppt/media/padlock.svg"}]}
    assert select_icon(catalog, "security")["slug"] == "padlock"


def test_category_words_do_not_make_an_icon_match():
    icon = {"slug": "apple", "name": "Apple", "category": "Security", "category_key": "security",
            "tags": ["apple", "security"], "part": "ppt/media/a.svg"}
    assert "security" not in icon_words(icon)
    assert select_icon({"icons": [icon]}, "security") is None


def test_neutral_topics_slide_places_alt_text_icons(neutral, tmp_path):
    path, snapshot = neutral
    plan = build_aws_deck_plan(_aws_snapshot(), snapshot, knowledge_facts=_knowledge_facts())
    topics = next(entry for entry in plan if entry["title"] == "The survey in three numbers")
    result = build_presentation_from_plan(path, snapshot, [topics], tmp_path / "topics.pptx")
    placed = [slot for slot in result["filled_slots"] if slot.startswith("icon:")]
    assert placed == ["icon:server_rack@resource_types", "icon:server_rack@services", "icon:globe@regions"]
    assert "icons_unavailable" not in {finding["code"] for finding in result["quality_findings"]}


def test_icon_layout_needs_one_holder_per_column():
    columns = [
        {"idx": 10 + i, "role": "content", "placeholder_type": "body", "x_emu": x, "y_emu": y, "w_emu": 900_000,
         "h_emu": h}
        for i, (x, y, h) in enumerate(
            (x, y, h) for x in (200_000, 3_000_000, 6_000_000) for y, h in ((2_000_000, 400_000), (2_600_000, 1_500_000))
        )
    ]
    slots = [{"idx": 0, "role": "title", "placeholder_type": "title"}, *columns]
    size = {"width_emu": 9_144_000, "height_emu": 5_143_500}
    assert classify_layout("Layout 8", slots, size, icon_holders=3)[0] == "icons_3"
    assert classify_layout("Layout 8", slots, size, icon_holders=0)[0] == "columns_3"
    assert classify_layout("Icons 3 Topics", slots, size, icon_holders=0)[0] == "icons_3"  # name as tie-break


def test_corporate_identity_extraction_reads_the_same_icons_and_columns(neutral, tmp_path):
    path, _snapshot = neutral
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(path) as archive:
        archive.extractall(extracted)
    catalog = extract_icon_catalog(extracted, tmp_path / "profile")
    names = {item["name"] for items in catalog["categories"].values() for item in items}
    assert names == {"Shield", "Globe", "padlock", "Server rack"}

    layouts = extract_layout_catalog(extracted, {}, {})["layouts"]
    by_name = {layout["name"]: layout for layout in layouts}
    purposes = sorted(item["purpose"] for item in by_name["Layout 8"]["placeholders"] if "icon" in item["purpose"])
    assert purposes == [f"icon {kind} {n}" for kind in ("body", "heading") for n in (1, 2, 3)]
    assert by_name["Layout 5"]["category"] == "section"  # secHead, by type
    assert by_name["Layout 1"]["category"] == "title"
