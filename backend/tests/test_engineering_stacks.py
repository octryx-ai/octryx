"""Stacks are data next to the Engineering Knowledge Packs: manifests, build folders, l10n catalogs and app facts
come from ``stacks.json`` and its levels; the consumers name none."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.engineering_knowledge import stacks
from app.services.workflow_runs.hands_on.generate import app_root, ui_texts
from app.services.workflow_runs.review.decision_evidence import AppFiles, technology_evidence


def test_the_built_in_stacks_carry_todays_values():
    data = stacks.built_in()
    assert "pubspec.yaml" in stacks.manifests(data) and "package.json" in stacks.manifests(data)
    assert {"build", ".dart_tool", "node_modules"} <= stacks.skip_folders(data)
    assert "python" in data["stacks"]  # the key of the shipped Python Engineering Knowledge Pack


def test_a_level_adds_a_stack_and_removes_one():
    level = {"elixir": {"manifests": [{"file": "mix.exs", "format": "lines", "comment": "#"}],
                        "code_suffixes": [".ex"], "skip_folders": ["_build"]}, "flutter": None}
    data = stacks.merged({}, level)
    assert "mix.exs" in stacks.manifests(data) and "pubspec.yaml" not in stacks.manifests(data)
    assert "_build" in stacks.skip_folders(data)


def test_a_new_stack_is_data_only(tmp_path: Path):
    """A stack the platform never shipped: its app folder, l10n texts and dependencies are found from the data."""
    app = tmp_path / "apps" / "shop"
    (app / "priv" / "locales").mkdir(parents=True)
    (app / "mix.exs").write_text('{:phoenix, "~> 1.7"}\n', encoding="utf-8")
    (app / "priv" / "locales" / "en.json").write_text(json.dumps({"checkout": "Checkout"}), encoding="utf-8")
    (app / "lib").mkdir()
    (app / "lib" / "shop.ex").write_text("use Phoenix.Router\n", encoding="utf-8")
    level = {"elixir": {"manifests": [{"file": "mix.exs", "format": "lines", "comment": "#"}],
                        "code_suffixes": [".ex"], "skip_folders": ["_build"],
                        "ui_catalogs": [{"glob": "*.json", "english": ["en"]}]}}
    data = stacks.merged({}, level)
    changed = ("apps/shop/lib/shop.ex",)
    assert app_root(tmp_path, changed, data) == app
    assert ui_texts(app, data) == ["Checkout"]
    files = AppFiles.read(app, tmp_path, data)
    dependencies, uses = technology_evidence(files, {"packages": [":phoenix"], "uses": r"Phoenix\."})
    assert uses and uses[0].startswith("apps/shop/lib/shop.ex")


def test_the_consumers_name_no_manifest_folder_or_catalog():
    import app.services.workflow_runs.hands_on.app_facts as app_facts
    import app.services.workflow_runs.hands_on.generate as generate
    import app.services.workflow_runs.review.decision_evidence as decision_evidence

    terms = ('"pubspec.yaml"', '"package.json"', '"*.arb"', '"build"', '"node_modules"', '".dart_tool"',
             '"features"', '"onboarding"', '"*.dart"', '".dart"', "MaterialApp", '"go.mod"', '"pom.xml"',
             "integration_test", "__tests__", "e2e")
    for module in (generate, app_facts, decision_evidence):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert not [term for term in terms if term in source], module.__name__


def test_a_test_file_is_known_by_the_stacks_test_folders_and_names():
    """The test paths are stack data too; today's set is unchanged."""
    for path in ("app/test/x_test.dart", "app/integration_test/app.dart", "web/src/__tests__/a.ts", "web/e2e/b.ts",
                 "web/src/a.test.ts", "web/src/a.spec.ts", "api/tests/conftest.py", "api/test_a.py",
                 "app/system_test/run_system_test.py", "svc/handler_test.go"):
        assert stacks.is_test(path), path
    for path in ("app/lib/main.dart", "web/src/attest.ts", "api/app/service.py"):
        assert not stacks.is_test(path), path
    only = stacks.merged({}, {"flutter": {"tests": {"folders": ["checks"], "names": []}}, "node": None,
                              "python": None, "go": None})
    data = {**only, "general": {}}
    assert stacks.is_test("app/checks/a.dart", data) and not stacks.is_test("web/e2e/b.ts", data)


def test_a_declared_runner_takes_its_harmless_options_in_every_phase_and_the_hint_names_them():
    """The fix phase must accept `flutter test -j 1`, the command the platform's own hint asks for.
    The options and the hint come from the same stack data (test_runner)."""
    from app.services.workflow_runs.evidence_pause import concurrent_hint
    from app.services.workflow_runs.octryx.shell_rules import strict_shell_allows

    prefixes = (("flutter", "test"), ("dart", "test"))
    for command in ("flutter test -j 1", "flutter test --reporter json", "flutter test --reporter=json test/a_test.dart",
                    "cd app && flutter test -j 1", "dart test --concurrency=1"):
        assert strict_shell_allows(command, runs_tests=True, test_prefixes=prefixes, protected=True), command
    for command in ("flutter test --dart-define=X=1", "flutter test -j 1;id", "flutter test /etc/passwd",
                    "flutter test --reporter json5"):
        assert not strict_shell_allows(command, runs_tests=True, test_prefixes=prefixes, protected=True), command
    hint = concurrent_hint()
    assert "`flutter test --reporter json`" in hint and "-j 1" not in hint
    assert strict_shell_allows("flutter test --reporter json", runs_tests=True, test_prefixes=prefixes,
                               protected=True)


def test_the_full_run_hint_is_the_runners_own():
    """A generic "-q, -x are fine" would send a Flutter agent to `flutter test -q`, which the shell policy refuses; the
    Stop feedback and the system test rule name the runner's own full-run options (stack data)."""
    from app.services.workflow_runs.octryx.system_tests import rule_text

    assert "-q, -x" in stacks.full_run_hint(".venv/bin/python -m pytest -v")
    flutter = stacks.full_run_hint("export PUB_CACHE=$PWD/.pub-cache; flutter test")
    # The JSON reporter's output can be the largest text in a Flutter story's context; the
    # pipeline after the phase attributes each test, so the full run keeps the short output.
    assert "-q" not in flutter and "--reporter json" not in flutter and "tail -40" in flutter
    assert stacks.full_run_hint("make check") == "the runner's own output options and '| tail' are fine"
    rule = rule_text("flutter test integration_test")
    assert "-q, -x" not in rule and "-j or '| tail -40'" in rule
