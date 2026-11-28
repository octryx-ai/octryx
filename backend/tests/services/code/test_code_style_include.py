"""Which files a rule judges is data with levels: an ``include`` judges a file a
less specific level excludes; the most specific level decides and ``include`` wins a tie. One test per level."""

from __future__ import annotations

import pytest

from app.services.code_style.check import findings
from app.services.code_style.defaults import BUILT_IN
from app.services.code_style.resolve import effective, flat
from app.services.code_style.schema import normalize_profile
from app.services.code_style.schema_values import CodeStyleError

SIZES = {"files": {"docs/SPEC.md": 320, "web/style.css": 400, "lib/main.py": 10},
         "long_lines": [["docs/SPEC.md", 3, 400], ["web/style.css", 1, 4974]]}


def _paths(levels: dict) -> set[tuple[str, str]]:
    style = {"general": flat(effective(levels)), "languages": {"python": flat(effective(levels, "python"))}}
    return {(item.path, item.rule) for item in findings(style, SIZES)}


def test_built_in_documentation_is_never_judged_and_a_stylesheet_keeps_its_line_length():
    assert {"glob": "**/*.md", "reason": "documentation"} in BUILT_IN["exclude"]
    assert _paths({}) == {("web/style.css", "max_line_length")}


@pytest.mark.parametrize("level", ["installation", "workspace", "repository"])
def test_an_include_at_any_level_judges_a_built_in_exclude(level):
    assert ("docs/SPEC.md", "max_lines_per_file") in _paths({level: normalize_profile({"include": ["**/*.md"]})})


def test_the_most_specific_level_decides():
    workspace_includes = normalize_profile({"include": ["docs/**"]})
    repository_excludes = normalize_profile({"exclude": [{"glob": "docs/**", "reason": "other"}]})
    assert not {path for path, _rule in _paths({"workspace": workspace_includes, "repository": repository_excludes})
                if path.startswith("docs/")}
    repository_includes = normalize_profile({"include": ["docs/**"]})
    workspace_excludes = normalize_profile({"exclude": [{"glob": "docs/**", "reason": "other"}]})
    assert ("docs/SPEC.md", "max_lines_per_file") in _paths({"workspace": workspace_excludes,
                                                               "repository": repository_includes})


def test_on_the_same_level_include_wins():
    both = normalize_profile({"exclude": [{"glob": "docs/**", "reason": "other"}], "include": ["docs/**"]})
    assert ("docs/SPEC.md", "max_lines_per_file") in _paths({"workspace": both})


def test_keep_names_only_known_rules():
    with pytest.raises(CodeStyleError):
        normalize_profile({"exclude": [{"glob": "**/*.css", "reason": "stylesheet", "keep": ["anything"]}]})


def test_the_engine_module_names_no_file_types():
    from pathlib import Path

    import app.services.code_style.check as check

    source = Path(check.__file__).read_text(encoding="utf-8")
    for term in ('".md"', '".css"', '".txt"', "pbxproj", "storyboard", "gradle", "pubspec"):
        assert term not in source, term


def test_the_l10n_merge_command_is_data():
    from app.services.code_style.l10n_check import l10n_findings, merge_command

    own = normalize_profile({"languages": {"dart": {"l10n": {
        "format": "arb", "files": ["lib/features/<namespace>/l10n/<lang>.arb"],
        "merged": {"target": "lib/l10n/app_<lang>.arb", "hand_edit": "error", "command": "make l10n TARGET={target}"}}}}})
    dart = flat(effective({"workspace": own}, "dart"))
    assert merge_command(dart["l10n"]) == "make l10n TARGET=lib/l10n/app_<lang>.arb"
    style = {"general": flat(effective({"workspace": own})), "languages": {"dart": dart}}
    [finding] = l10n_findings(style, {"catalogs": [], "changed": ["lib/l10n/app_de.arb"]})
    assert "make l10n TARGET=" in finding.message and finding.severity == "error"
    from pathlib import Path

    import app.services.code_style.brief as brief
    import app.services.code_style.check as check
    for module in (brief, check):
        assert "l10n-merge" not in Path(module.__file__).read_text(encoding="utf-8"), module.__name__


def test_an_analyzer_info_is_a_note_and_a_warning_or_error_blocks():
    from app.services.code_style.tool_check import tool_findings

    style = {"general": flat(effective({})), "languages": {"dart": flat(effective({}, "dart"))}}

    def run(output):
        [finding] = tool_findings([{"language": "dart", "kind": "linter", "tool": "flutter analyze",
                                    "state": "failed", "output": output}], style)
        return finding.severity

    info = ("Analyzing app...\n   info • 'material.dart' is deprecated, use package:material_ui • "
            "lib/main.dart:1:8 • deprecated_member_use\n1 issue found.")
    assert run(info) == "warning"
    assert run(info + "\n  error • Undefined name 'x' • lib/a.dart:3:1 • undefined_identifier") == "error"
    assert run("warning • Unused import • lib/b.dart:2:8 • unused_import") == "error"
    assert run("something unexpected") == "error"
    assert run(("   info • x • lib/a.dart:1:1 • y\n" * 100)[-2000:]) == "error"  # cut output may hide an error
    workspace = normalize_profile({"languages": {"dart": {"linter": {"blocking": ["warning", "error", "info"]}}}})
    strict = {"general": flat(effective({"workspace": workspace})),
              "languages": {"dart": flat(effective({"workspace": workspace}, "dart"))}}
    [finding] = tool_findings([{"language": "dart", "kind": "linter", "tool": "flutter analyze", "state": "failed",
                                "output": info}], strict)
    assert finding.severity == "error"
    from pathlib import Path

    import app.services.code_style.check as check
    assert "info •" not in Path(check.__file__).read_text(encoding="utf-8")
