"""The Corporate Identity as the Spec Studio's default direction, taken from the platform's own CI pipeline
(``office_identity.build_corporate_identity``)."""

from __future__ import annotations

from app.services.office_identity import build_corporate_identity
from app.services.workflow_runs.spec_studio.corporate import corporate_direction, until_aa
from app.services.workflow_runs.spec_studio.design import AA, contrast, on_accent

_TEMPLATE = {
    "kind": "presentation",
    "source_file": "brand.potx",
    "theme": {
        "fonts": {"major": "Georgia", "minor": "Verdana"},
        "colors": {"dk1": "#14213D", "lt1": "#FFFFFF", "dk2": "#4A5568", "lt2": "#F1F3F6",
                   "accent1": "#0B5FA5", "accent2": "#2E8B57", "accent3": "#C0392B"},
        "theme_name": "Example Brand",
    },
}


def _brief(**extra) -> dict:
    brief = build_corporate_identity([_TEMPLATE])
    brief.update(profile_id="ci-1", profile_name="Example Brand", **extra)
    return brief


def test_the_templates_values_are_taken_as_they_are_and_marked_ci():
    direction = corporate_direction(_brief())
    light, sources = direction["light"], direction["corporate"]["sources"]
    assert direction["name"] == "Corporate: Example Brand"
    assert (light["bg"], light["surface"], light["text"], light["muted"], light["accent"]) == (
        "#FFFFFF", "#F1F3F6", "#14213D", "#4A5568", "#0B5FA5")
    assert {sources[f"light.{key}"] for key in ("bg", "surface", "text", "muted", "accent")} == {"ci"}
    assert direction["fonts"]["head"].startswith("Georgia") and direction["fonts"]["body"].startswith("Verdana")
    assert (sources["fonts.head"], sources["radius"]) == ("ci", "derived")
    # error: the template's red accent (fitting hue, AA on the card). ok: its green is below AA on the card, so it is
    # darkened in its own hue (derived). warn: no accent of that hue, the neutral default.
    assert (light["error"], sources["light.error"]) == ("#C0392B", "ci")
    assert (light["ok"], sources["light.ok"]) == ("#297C4D", "derived")
    assert (light["warn"], sources["light.warn"]) == ("#8A5A00", "derived")


def test_what_the_template_does_not_say_is_derived_and_meets_aa_in_both_themes():
    direction = corporate_direction(_brief())
    sources = direction["corporate"]["sources"]
    assert {value for key, value in sources.items() if key.startswith("dark.")} == {"derived"}
    for theme in ("light", "dark"):
        tokens = direction[theme]
        for key in ("text", "muted", "ok", "warn", "error"):
            if sources[f"{theme}.{key}"] == "derived":
                assert contrast(tokens[key], tokens["surface"]) >= AA, (theme, key)
    assert contrast(direction["dark"]["accent"], direction["dark"]["bg"]) >= AA
    # The button text on the derived main action too (Studio contrast "Button text on main action").
    assert contrast(direction["dark"]["accent"], on_accent(direction["dark"]["accent"])) >= AA


def test_a_weak_ci_colour_is_never_changed_and_a_missing_one_is_filled():
    template = {**_TEMPLATE, "theme": {**_TEMPLATE["theme"], "colors": {"dk1": "#14213D", "lt1": "#FFFFFF",
                                                                         "dk2": "#B8BEC8", "accent1": "#7FB3E0"}}}
    direction = corporate_direction({**build_corporate_identity([template]), "profile_name": "Weak"})
    light, sources = direction["light"], direction["corporate"]["sources"]
    assert (light["muted"], sources["light.muted"]) == ("#B8BEC8", "ci")  # below AA: stays, the gate reports it
    assert sources["light.surface"] == "derived" and light["surface"] != light["bg"]


def test_an_empty_profile_still_gives_a_complete_direction():
    direction = corporate_direction({})
    assert set(direction["light"]) == set(direction["dark"]) == {"bg", "surface", "text", "muted", "accent", "ok",
                                                                 "warn", "error"}
    assert direction["name"] == "Corporate: Corporate"


def test_the_logo_and_the_icons_come_from_the_ci_assets_by_slug():
    assets = {"logos": [{"name": "logo", "path": "assets/logo.png", "kind": "logo"}],
              "icons": [{"name": "Coffee Cup", "kind": "icon", "path": "icons/general/coffee-cup.svg"},
                        {"name": "Broken", "kind": "icon", "path": ""}]}
    corporate = corporate_direction(_brief(assets=assets))["corporate"]
    assert corporate["logo"] == "assets/logo.png"
    assert corporate["icons"] == {"coffee-cup": "icons/general/coffee-cup.svg"}
    assert (corporate["profile_id"], corporate["profile_name"]) == ("ci-1", "Example Brand")


def test_until_aa_keeps_the_hue_and_stops_at_aa():
    darker = until_aa("#9FC5E8", "#FFFFFF", lighter=False)
    assert contrast(darker, "#FFFFFF") >= AA and darker != "#9FC5E8"
    assert until_aa("#0B5FA5", "#FFFFFF", lighter=False) == "#0B5FA5"  # already AA: unchanged
