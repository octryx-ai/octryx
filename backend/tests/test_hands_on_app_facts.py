"""The scenario generator learns how a fresh profile starts and that the app title is the window title."""

from __future__ import annotations

from pathlib import Path

from app.services.workflow_runs.hands_on.app_facts import first_start_note, title_note


def _app(tmp_path: Path, onboarding: bool) -> tuple[Path, dict[str, str]]:
    lib = tmp_path / "lib"
    (lib / "app").mkdir(parents=True)
    (lib / "app" / "app.dart").write_text(
        "return MaterialApp(\n  onGenerateTitle: (context) => AppLocalizations.of(context)!.appTitle,\n);\n")
    catalog = {"appTitle": "Coffee Companion", "save": "Save"}
    if onboarding:
        (lib / "features" / "onboarding").mkdir(parents=True)
        catalog |= {"onboardingSkip": "Skip", "onboardingNext": "Next"}
    return tmp_path, catalog


def test_a_fresh_profile_of_an_app_with_onboarding_skips_it_first(tmp_path):
    root, catalog = _app(tmp_path, onboarding=True)
    note = first_start_note(root, catalog)
    assert "first shows its onboarding" in note and 'clicks "Skip" first' in note


def test_an_app_without_onboarding_gets_no_first_start_note(tmp_path):
    root, catalog = _app(tmp_path, onboarding=False)
    assert first_start_note(root, catalog) == ""


def test_the_generated_title_is_named_as_the_window_title(tmp_path):
    root, catalog = _app(tmp_path, onboarding=False)
    assert '"Coffee Companion" is the browser window title' in title_note(root, catalog)


def test_a_literal_material_app_title_is_found(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "main.dart").write_text("runApp(MaterialApp(title: 'Bean Log', home: Home()));\n")
    assert '"Bean Log"' in title_note(tmp_path, {})
    assert title_note(tmp_path / "lib" / "missing", {}) == ""


def test_the_ui_texts_come_from_the_changed_app_not_its_neighbours_or_packages(tmp_path: Path):
    import json

    from app.services.workflow_runs.hands_on.generate import app_root, screen_actions, ui_texts

    def app(folder: str, texts: dict[str, str]) -> Path:
        root = tmp_path / folder
        (root / "lib" / "l10n").mkdir(parents=True)
        (root / "pubspec.yaml").write_text("name: app\n", encoding="utf-8")
        (root / "lib" / "l10n" / "app_en.arb").write_text(json.dumps(texts), encoding="utf-8")
        return root

    app("coffee/flutter/claude", {"aboutSources": "About and sources", "grinders": "Grinders"})
    codex = app("coffee/flutter/codex", {"export": "Export", "about": "About & sources"})
    package = codex / ".pub-cache" / "hosted" / "material_ui" / "lib" / "l10n"
    package.mkdir(parents=True)
    (package / "material_en.arb").write_text(json.dumps({"ok": "OK"}), encoding="utf-8")
    screen = codex / "lib" / "features" / "settings" / "settings_screen.dart"
    screen.parent.mkdir(parents=True)
    screen.write_text("Text(copy.export)", encoding="utf-8")
    changed = ("coffee/flutter/codex/lib/features/settings/settings_screen.dart",)

    assert app_root(tmp_path, changed) == codex
    assert ui_texts(app_root(tmp_path, changed)) == ["Export", "About & sources"]
    assert screen_actions(tmp_path, changed) == ["Export"]
    assert app_root(tmp_path, ("README.md",)) == tmp_path
