"""The size class reads risk from structured fields, not from prose (a description's "no dependencies" would match
the risk words and make a small bug L)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.services.workflow_runs.size_class.rules import first_match

SEEDS = json.loads((Path(__file__).parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json")
                   .read_text(encoding="utf-8"))
BUG = next(item for item in SEEDS if item["key"] == "bug-fix-reproduction")["definition"]["size_classes"]


def _item(description: str, labels=(), components=()) -> SimpleNamespace:
    return SimpleNamespace(issue_type="Bug", title="Discount is applied twice", description=description,
                           labels_json=list(labels), components_json=list(components))


def test_a_small_bug_saying_no_dependencies_stays_small():
    item = _item("Steps: add a mug, apply 10 %. Expected 45.00, actual 40.00. No dependencies, no migration, "
                 "no login involved.", labels=["ui"])
    assert first_match(BUG, item)[0] == "S"


def test_risk_comes_from_labels_and_components():
    assert first_match(BUG, _item("Totals are off.", labels=["Security"]))[0] == "L"
    assert first_match(BUG, _item("Totals are off.", components=["payments"]))[0] == "L"
    assert first_match(BUG, _item("Totals are off.", labels=["full-flow"]))[0] == "L"
    assert first_match(BUG, _item("Totals are off.", labels=["ui"]))[0] == "S"
    assert not any("text_matches" in rule["when"] for rule in BUG["rules"])


def test_an_item_without_labels_and_components_is_m_never_the_lightest_class():
    # A team that does not label must not get class S for "Login fails after password reset".
    auth = SimpleNamespace(issue_type="Bug", title="Login fails after password reset", description="Since today.",
                           labels_json=[], components_json=[])
    assert first_match(BUG, auth)[0] == "M"
    assert first_match(BUG, _item("Since today.", labels=["ui"]))[0] == "S"
    assert first_match(BUG, _item("Since today.", components=["checkout-page"]))[0] == "S"
