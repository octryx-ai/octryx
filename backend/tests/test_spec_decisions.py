"""The specification's decisions against the code: an in-memory store must not pass review when SPEC.md decided
drift/SQLite."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.services.workflow_runs.review.convergence import Settled
from app.services.workflow_runs.review.decisions_gate import decisions_gate
from app.services.workflow_runs.review.spec_decisions import (
    IMPLEMENTED,
    MISSING,
    UNCLEAR,
    check_decisions,
    decision_items,
)
from app.services.workflow_runs.review.verdict import Finding, Verdict

COF50 = Path(__file__).parent / "fixtures" / "cof50_flutter"
APP = "coffee/flutter/claude"


def test_the_cof50_change_misses_its_storage_decision():
    check = check_decisions(COF50, (f"{APP}/lib/app/app_data.dart",))
    assert check is not None and check.spec == f"{APP}/SPEC.md"
    storage = check.decisions[1]
    assert storage.number == 2 and "drift/SQLite" in storage.text
    assert (storage.hard, storage.state) == (True, MISSING)
    assert "drift: no dependency" in storage.reason and "sqlite: no dependency" in storage.reason
    # A comment that names drift is no evidence ("meant to be backed by SQLite (drift)").
    assert not storage.evidence
    assert check.missing == [storage]
    assert all(item.state == UNCLEAR and not item.hard for item in check.decisions if item is not storage)
    assert check.table().splitlines()[1].startswith("✗ 2. Lokale Speicherung mit drift/SQLite")


def test_a_declared_and_imported_store_is_implemented_with_file_and_line(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(COF50, root)
    app = root / APP
    pubspec = app / "pubspec.yaml"
    pubspec.write_text(pubspec.read_text().replace("  uuid: ^4.5.0\n", "  uuid: ^4.5.0\n  drift: ^2.20.0\n"
                                                                       "  drift_flutter: ^0.2.0\n"))
    (app / "lib/core/data/database.dart").write_text("import 'package:drift/drift.dart';\n\nclass AppDb {}\n")
    check = check_decisions(root, (f"{APP}/lib/core/data/database.dart",))
    storage = check.decisions[1]
    assert storage.state == IMPLEMENTED and check.missing == []
    assert any(item.startswith(f"{APP}/pubspec.yaml:") and "dependency: drift:" in item for item in storage.evidence)
    assert f"{APP}/lib/core/data/database.dart:1 use: import 'package:drift/drift.dart';" in storage.evidence


def test_a_dependency_nobody_imports_is_unclear(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(COF50, root)
    pubspec = root / APP / "pubspec.yaml"
    pubspec.write_text(pubspec.read_text().replace("  uuid: ^4.5.0\n", "  uuid: ^4.5.0\n  drift: ^2.20.0\n"))
    storage = check_decisions(root, (f"{APP}/pubspec.yaml",)).decisions[1]
    assert storage.state == UNCLEAR and "drift: declared but never used" in storage.reason


def test_only_the_decisions_sections_are_read():
    spec = ("# App\n## 3 Data\n1. A table\n## Decisions\n1. Use **React** with Vite\n   and Tailwind.\n"
            "- Persistence: IndexedDB\n### Detail\n2. Nested still counts\n## 9 Open questions\n1. None\n")
    assert decision_items(spec) == ["Use **React** with Vite and Tailwind.", "Persistence: IndexedDB",
                                    "Nested still counts"]
    assert decision_items("# App\n## Technische Anforderungen\n- drift\n") == ["drift"]
    assert decision_items("# App\nno decisions here\n") == []


def test_a_missing_hard_decision_blocks_whatever_the_model_answered():
    check = check_decisions(COF50, (f"{APP}/lib/app/app_data.dart",))
    passed = Settled(Verdict("pass", "looks good", ()))
    gated = decisions_gate(passed, check)
    assert gated.verdict.verdict == "changes"
    (finding,) = gated.verdict.findings
    assert (finding.severity, finding.file, finding.id) == ("high", f"{APP}/SPEC.md", "D1")
    assert finding.fix.startswith('Spec decision 2 not implemented: "Lokale Speicherung mit drift/SQLite')
    # A follow-up that already carries it keeps its findings; no duplicate.
    again = decisions_gate(gated, check)
    assert again.verdict.findings == gated.verdict.findings
    other = Settled(Verdict("changes", "", (Finding("medium", "lib/a.dart", 3, "rename"),)))
    assert len(decisions_gate(other, check).verdict.findings) == 2
    assert decisions_gate(passed, None) is passed


# ---- a feature request on an existing app ---------------------------------------------------------------------------

ONBOARDING_DECISION = ("16. Onboarding: drei Seiten beim ersten Start, überspringbar; der Status „Onboarding erledigt“ "
                       "wird mit shared_preferences gespeichert.\n")


def _git(root: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                    *args], cwd=root, check=True, capture_output=True)


def _existing_app_with_onboarding_spec(tmp_path: Path) -> Path:
    """The Coffee app as its first spec defined it (drift decided, never built), then the feature epic's spec
    commit adds the onboarding decision."""
    root = tmp_path / "repo"
    shutil.copytree(COF50, root)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "CAF-44: Kaffee-Begleiter")
    spec = root / APP / "SPEC.md"
    spec.write_text(spec.read_text().replace("\n## 9 Offene Fragen", f"{ONBOARDING_DECISION}\n## 9 Offene Fragen"))
    _git(root, "commit", "-qam", "CAF-60: Onboarding für den Kaffee-Begleiter")
    return root


async def test_a_feature_checks_only_its_own_decisions_the_existing_ones_are_context(tmp_path):
    from app.services.workflow_runs.review.spec_decisions import CONTEXT, feature_decisions

    root = _existing_app_with_onboarding_spec(tmp_path)
    onboarding = root / APP / "lib/features/onboarding/onboarding_page.dart"
    onboarding.parent.mkdir(parents=True)
    onboarding.write_text("class OnboardingPage {}\n")  # the decided storage left out
    check = await feature_decisions(root, (f"{APP}/lib/features/onboarding/onboarding_page.dart",),
                                    ("CAF-60", "CAF-61"))
    assert check.scope.startswith("feature: ") and "CAF-60: Onboarding" in check.scope
    feature = check.decisions[-1]
    assert feature.text.startswith("Onboarding: drei Seiten") and (feature.hard, feature.state) == (True, MISSING)
    # drift/SQLite was decided before and never built: context for this feature, never its ✗.
    assert check.decisions[1].state == CONTEXT
    assert check.missing == [feature]
    assert check.table().splitlines()[1].startswith("· 2. Lokale Speicherung mit drift/SQLite")

    # The onboarding that keeps its flag as decided: implemented.
    pubspec = root / APP / "pubspec.yaml"
    pubspec.write_text(pubspec.read_text().replace("  uuid: ^4.5.0\n", "  uuid: ^4.5.0\n  shared_preferences: ^2.3.0\n"))
    onboarding.write_text("import 'package:shared_preferences/shared_preferences.dart';\n\nclass OnboardingPage {}\n")
    check = await feature_decisions(root, (f"{APP}/lib/features/onboarding/onboarding_page.dart",), ("CAF-60",))
    assert check.decisions[-1].state == IMPLEMENTED and check.missing == []


async def test_a_new_app_checks_its_whole_spec_and_a_spec_edit_in_the_change_counts(tmp_path):
    from app.services.workflow_runs.review.spec_decisions import feature_decisions

    root = _existing_app_with_onboarding_spec(tmp_path)
    changed = (f"{APP}/lib/app/app_data.dart",)
    # The first commit created the spec: every decision is new, drift/SQLite is checked (the in-memory store is red).
    check = await feature_decisions(root, changed, ("CAF-44", "CAF-50"))
    assert [item.number for item in check.missing] == [2]
    # No spec commit names the work: the whole spec.
    assert (await feature_decisions(root, changed, ("XYZ-1",))).scope == "whole_spec"
    # A story that adds a decision to the spec itself has it checked.
    spec = root / APP / "SPEC.md"
    spec.write_text(spec.read_text().replace("\n## 9 Offene Fragen", "17. Export als CSV mit Riverpod-Status.\n\n## 9 Offene Fragen"))
    check = await feature_decisions(root, (*changed, f"{APP}/SPEC.md"), ("XYZ-1",))
    checked = [item for item in check.decisions if item.state != "context"]
    assert [item.text for item in checked] == ["Export als CSV mit Riverpod-Status."]
    assert checked[0].state == MISSING


def _app_with(tmp_path: Path, decisions: str, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "app/SPEC.md").write_text(f"# App\n## Decisions\n{decisions}")
    for name, text in files.items():
        (root / "app" / name).parent.mkdir(parents=True, exist_ok=True)
        (root / "app" / name).write_text(text)
    return root


def test_a_platform_api_needs_only_its_use_in_the_code(tmp_path):
    decision = "1. Persistence in IndexedDB, offline first.\n"
    used = _app_with(tmp_path, decision, {"package.json": "{}", "src/db.ts": "const req = indexedDB.open('app', 1);\n"})
    check = check_decisions(used, ("app/src/db.ts",))
    assert (check.decisions[0].hard, check.decisions[0].state) == (True, IMPLEMENTED)
    shutil.rmtree(used)
    unused = _app_with(tmp_path, decision, {"src/db.ts": "const store = new Map();\n"})
    assert check_decisions(unused, ("app/src/db.ts",)).decisions[0].state == MISSING


def test_a_decided_value_is_found_near_its_term_or_differs_softly(tmp_path):
    from app.services.workflow_runs.review.decisions_gate import missing_findings

    decision = "1. Grind setting: default `grindSetting` 15.\n"
    right = _app_with(tmp_path, decision, {"lib/brew.dart": "const double grindSetting = 15;\n"})
    found = check_decisions(right, ("app/lib/brew.dart",)).decisions[0]
    assert found.state == IMPLEMENTED and found.evidence[0].startswith("app/lib/brew.dart:1 value:")
    shutil.rmtree(right)
    wrong = _app_with(tmp_path, decision, {"lib/brew.dart": "  double grindSetting = 0.0;\n"})
    check = check_decisions(wrong, ("app/lib/brew.dart",))
    differs = check.decisions[0]
    assert (differs.hard, differs.state) == (False, MISSING) and "other value 0.0" in differs.evidence[0]
    (finding,) = missing_findings(check)
    assert (finding["severity"], finding["file"], finding["line"]) == ("low", "app/lib/brew.dart", 1)
    # Soft: a medium finding, the verdict stays as the model gave it.
    passed = Settled(Verdict("pass", "", ()))
    gated = decisions_gate(passed, check)
    assert gated.verdict.verdict == "pass" and gated.verdict.findings[0].severity == "low"
    # A comment is no value; a longer name containing the term is not the setting.
    shutil.rmtree(wrong)
    other = _app_with(tmp_path, decision, {"lib/brew.dart": "// grindSetting 15\nconst maxGrindSettingStep = 2;\n"})
    assert check_decisions(other, ("app/lib/brew.dart",)).decisions[0].state == UNCLEAR


def test_the_catalog_is_extendable_per_level():
    from app.services.code_style.schema import normalize_profile
    from app.services.code_style.technologies import built_in, catalog

    for key in ("sqflite", "isar", "objectbox", "room", "core_data", "swiftdata", "flutter_secure_storage",
                "provider", "mobx", "next", "angular", "django", "spring", "hibernate", "diesel", "sqlx"):
        assert key in built_in()
    own = normalize_profile({"technologies": {"realm": {"kind": "library", "words": ["realm"], "packages": ["realm"],
                                                        "uses": "package:realm/"}, "vue": None}})
    merged = catalog({"workspace": own})
    assert merged["realm"]["packages"] == ["realm"] and "vue" not in merged and "drift" in merged
    import pytest

    from app.services.code_style.schema_values import CodeStyleError

    with pytest.raises(CodeStyleError):
        normalize_profile({"technologies": {"x": {"words": ["x"], "uses": "("}}})


async def test_the_recorded_spec_push_scopes_the_feature_and_no_scope_checks_the_whole_spec(tmp_path):
    from app.services.workflow_runs.review.spec_decisions import CONTEXT, feature_decisions

    root = _existing_app_with_onboarding_spec(tmp_path)
    changed = (f"{APP}/lib/app/app_data.dart",)
    onboarding = ONBOARDING_DECISION.split(". ", 1)[1].strip()
    # Recorded at the push: no commit subject needed (squashed, rebased or renamed).
    recorded = {"sha": "deadbeef", "path": f"{APP}/SPEC.md", "introduced": [onboarding]}
    check = await feature_decisions(root, changed, (), recorded=recorded)
    assert check.scope.startswith("feature: deadbeef") and check.decisions[1].state == CONTEXT
    assert [item.text for item in check.missing] == [onboarding]
    # Neither a record nor a commit that names the work: the whole spec, never nothing.
    whole = await feature_decisions(root, changed, ("NOPE-1",))
    assert whole.scope == "whole_spec" and {item.number for item in whole.missing} == {2, 16}


async def test_a_decision_the_base_never_implemented_is_context_for_an_unrelated_fix(tmp_path):
    """"SPEC decision 2 drift/SQLite not implemented" (high) must not hold an unrelated bug fix red. With nothing
    scoping the work, a technology decision missing at the base too is the app's open decision, not this change's."""
    import subprocess

    from app.services.workflow_runs.review.spec_decisions import feature_decisions

    root = _existing_app_with_onboarding_spec(tmp_path)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout
    changed = (f"{APP}/lib/app/app_data.dart",)
    check = await feature_decisions(root, changed, ("XYZ-1",), base.strip())
    assert check.scope == "whole_spec" and check.missing == []
    drift = next(item for item in check.decisions if item.number == 2)
    assert drift.state == "context" and "not implemented at the base either" in drift.reason
    # Without a base nothing is downgraded.
    assert [item.number for item in (await feature_decisions(root, changed, ("XYZ-1",))).missing] == [2, 16]


def test_a_carried_decision_finding_leaves_when_the_decision_is_no_longer_missing():
    """Once the decision is context, the follow-up rounds drop the first round's decision finding (high) instead of
    keeping the review at ``changes``."""
    import dataclasses

    check = check_decisions(COF50, (f"{APP}/lib/app/app_data.dart",))
    gated = decisions_gate(Settled(Verdict("pass", "looks good", ())), check)
    for item in check.decisions:
        if item.number == 2:
            item.state = "context"
    now = decisions_gate(gated, check)
    assert now.verdict.findings == () and now.verdict.verdict == "pass"
    medium = Finding("medium", "lib/a.dart", 3, "add a unit test", "F1")
    mixed = dataclasses.replace(gated, verdict=dataclasses.replace(
        gated.verdict, findings=(medium, *gated.verdict.findings)))
    kept = decisions_gate(mixed, check)
    assert kept.verdict.findings == (medium,) and kept.verdict.verdict == "changes"  # still blocked by medium
    # A model finding that merely mentions a decision stays.
    own = Finding("high", "SPEC.md", 1, "Spec decision 2 is contradicted by lib/x.dart", "F2")
    model = Settled(Verdict("changes", "", (own,)))
    assert decisions_gate(model, check).verdict.findings == (own,)


def test_a_technology_the_decision_defers_or_excludes_is_not_checked():
    """A decision that names drift/SQLite only as a later follow-up ticket does not require them: shared_preferences,
    the decided flag store, is declared and used, so there is no high finding."""
    from app.services.code_style.technologies import catalog
    from app.services.workflow_runs.review.decision_evidence import decided_technologies

    known = catalog()
    text = ("OCX-74 Onboarding:\n    - Flag persistence: `shared_preferences`, key `onboardingDone`, set only on "
            "completion\n      (Section 3). Grinder and bean stay in memory until the follow-up ticket “Persistence "
            "with drift/SQLite” (ID pending, not part of OCX-74)\n      (`AppData`), known limitation.")
    assert decided_technologies(text, known) == ["shared_preferences"]
    assert set(decided_technologies("Persist locally with drift/SQLite, offline first.", known)) == {"drift", "sqlite"}
    assert decided_technologies("No cloud sync, no drift in this version.", known) == []


def test_a_platform_api_used_through_a_decided_package_is_unclear_not_missing(tmp_path):
    """"Chrome: `localStorage` via `shared_preferences`" — the app uses shared_preferences, so the decision is not
    "missing" on "local_storage: not used in the app's code"."""
    root = _app_with(tmp_path, "1. Flag with `shared_preferences`; Chrome: `localStorage` via `shared_preferences`.\n",
                     {"pubspec.yaml": "dependencies:\n  shared_preferences: ^2.5.3\n",
                      "lib/flag.dart": "import 'package:shared_preferences/shared_preferences.dart';\n"})
    check = check_decisions(root, ("app/lib/flag.dart",))
    (decision,) = check.decisions
    assert decision.state == "unclear" and check.missing == []
    assert "local_storage: not used directly, possibly through shared_preferences" in decision.reason
    alone = _app_with(tmp_path / "b", "1. Storage in the browser: `localStorage`.\n", {"lib/x.dart": "void main() {}\n"})
    assert [item.number for item in check_decisions(alone, ("app/lib/x.dart",)).missing] == [1]
