"""The line length in the central code style (generated files can ship a style.css with a 4,974 character
line and an app.js with 4,386): red like the other style rules, deterministic in Stop and pipeline."""

from __future__ import annotations

from app.services.code_style.check import findings
from app.services.code_style.resolve import effective, flat
from app.services.code_style.schema import normalize_profile
from app.services.workflow_runs.octryx.code_limits import style_result


def _style(levels=None):
    languages = {name: flat(effective(levels or {}, name)) for name in ("python", "javascript")}
    return {"general": flat(effective(levels or {})), "languages": languages}


SIZES = {"files": {"src/style.css": 1, "src/app.js": 120, "vendor/lib.min.css": 1, "tool.py": 10},
         "long_lines": [["src/style.css", 1, 4974], ["src/app.js", 74, 4386], ["vendor/lib.min.css", 1, 90000],
                        ["tool.py", 3, 140]]}


def test_the_cof37_lines_are_red_and_a_minified_file_is_not():
    assert flat(effective({}))["max_line_length"] == 160
    found = [item for item in findings(_style(), SIZES) if item.rule == "max_line_length"]
    assert [(item.path, item.line) for item in found] == [("src/style.css", 1), ("src/app.js", 74)]
    assert "4974 characters (max 160)" in found[0].message and "octryx: allow-long-line" in found[0].message
    result = style_result(_style(), SIZES)
    assert result.blocking is True and "[max_line_length]" in result.description


def test_a_language_or_workspace_sets_its_own_limit():
    python_100 = normalize_profile({"languages": {"python": {"max_line_length": 100}}})
    found = [item.path for item in findings(_style({"workspace": python_100}), SIZES)
             if item.rule == "max_line_length"]
    assert "tool.py" in found
    off = normalize_profile({"max_line_length": 0})
    assert not [item for item in findings(_style({"repository": off}), SIZES) if item.rule == "max_line_length"]


def test_a_written_specification_is_prose_and_never_judged_by_the_code_style():
    sizes = {"files": {"app/SPEC.md": 316, "app/lib/main.dart": 320},
             "long_lines": [["app/SPEC.md", 221, 1349], ["app/lib/main.dart", 9, 200]],
             "todos": [["app/SPEC.md", 117, "TODO decide later"]]}
    paths = {item.path for item in findings(_style(), sizes)}
    assert "app/SPEC.md" not in paths
    assert "app/lib/main.dart" in paths


def test_the_generated_flutter_platform_scaffold_is_never_judged():
    app = "coffee/flutter/codex"
    scaffold = [f"{app}/ios/Runner.xcodeproj/project.pbxproj", f"{app}/ios/Runner/Base.lproj/Main.storyboard",
                f"{app}/android/app/src/main/AndroidManifest.xml", f"{app}/android/app/build.gradle.kts",
                f"{app}/android/settings.gradle.kts", f"{app}/.octryx/environment.json"]
    sizes = {"files": {**{path: 647 for path in scaffold}, f"{app}/lib/main.dart": 320},
             "long_lines": [*([path, 2, 281] for path in scaffold), [f"{app}/lib/main.dart", 9, 200]]}
    languages = {name: flat(effective({}, name)) for name in ("kotlin", "dart")}
    style = {"general": flat(effective({})), "languages": languages}
    assert {item.path for item in findings(style, sizes)} == {f"{app}/lib/main.dart"}
