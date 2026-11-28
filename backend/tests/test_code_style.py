"""The code style is defined once for the installation (file, test and function lengths, the Flutter layout),
overridable per Workspace, repository and language, every value with its source."""

from __future__ import annotations

import pytest

from app.services.code_style.resolve import effective, flat
from app.services.code_style.schema import normalize_profile
from app.services.code_style.schema_values import CodeStyleError
from app.services.code_style.store import repository_profile, workspace_profile
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


def test_the_most_specific_level_wins_per_field_and_excludes_add_up():
    levels = {
        "installation": {"max_lines_per_file": 400, "comments": {"todo_requires_ticket": False}},
        "workspace": {"max_lines_per_file": 350, "languages": {"dart": {"max_lines_per_file": 250}},
                      "exclude": [{"glob": "lib/legacy/**", "reason": "other"}]},
        "repository": {"tests_max_lines": 800, "exclude": [{"glob": "assets/**", "reason": "assets"}]},
    }
    dart = effective(levels, "dart")
    assert dart["max_lines_per_file"] == {"value": 250, "source": "workspace.languages.dart"}
    assert effective(levels, "python")["max_lines_per_file"] == {"value": 350, "source": "workspace"}
    assert dart["tests_max_lines"] == {"value": 800, "source": "repository"}
    assert dart["max_function_lines"] == {"value": 60, "source": "built_in"}
    assert dart["comments"]["todo_requires_ticket"] == {"value": False, "source": "installation"}
    assert dart["comments"]["no_commented_code"]["source"] == "built_in"
    sources = {row["glob"]: row["source"] for row in dart["exclude"]["value"]}
    assert sources["assets/**"] == "repository" and sources["lib/legacy/**"] == "workspace"
    assert sources["**/*.g.dart"] == "built_in"  # a repository's own excludes never drop the generated-code ones
    layout = flat(dart)["layout"]["patterns"]
    assert "lib/features/*/presentation/**" in layout and "lib/core/**" in layout and "lib/app/**" in layout
    assert flat(effective({}, None))["layout"] == {}


def test_a_profile_is_validated_field_by_field():
    assert normalize_profile({"max_lines_per_file": 200, "languages": {"dart": {"naming": {"file": "^[a-z_]+$"}}}}) \
        == {"max_lines_per_file": 200, "languages": {"dart": {"naming": {"file": "^[a-z_]+$"}}}}
    for bad, path in (({"max_lines_per_file": -1}, "code_style.max_lines_per_file"),
                      ({"comments": {"todo_pattern": "("}}, "code_style.comments.todo_pattern"),
                      ({"exclude": [{"glob": "x", "reason": "because"}]}, "code_style.exclude[0]"),
                      ({"languages": {"cobol": {}}}, "code_style.languages"),
                      ({"colour": "blue"}, "code_style")):
        with pytest.raises(CodeStyleError) as raised:
            normalize_profile(bad)
        assert raised.value.path == path


def test_the_workspace_and_the_repository_read_only_their_code_style():
    from types import SimpleNamespace

    project = SimpleNamespace(config={"agent_gateway_policy": {"device_runs": {"code_conventions": {
        "max_file_lines": 280, "max_function_lines": 0, "exclude": ["tests/**"], "rules": "src/ only"}}}})
    assert workspace_profile(project) == {}
    project.config["code_style"] = {"max_lines_per_file": 280}
    assert workspace_profile(project) == {"max_lines_per_file": 280}
    record = SimpleNamespace(config_json={"coding_setup": {"code_conventions": {"max_file_lines": 120},
                                                           "code_style": {"tests_max_lines": 900}}})
    assert repository_profile(record) == {"tests_max_lines": 900}
    assert repository_profile(SimpleNamespace(config_json={"coding_setup": {"code_conventions": {
        "max_file_lines": 120}}})) == {}


@pytest.mark.asyncio
async def test_the_levels_are_written_by_their_admins_and_the_preview_names_the_sources(client, db):
    from app.models.runtime.code_intelligence import CodeRepository
    from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
    from tests.phased_workflow_fixtures import admin_user
    from tests.policy_engine_support import bearer

    workspace_id = await seed_workspace(db)
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    admin = await admin_user(db)
    repo = CodeRepository(project_id=workspace_id, name="octryx-ai/coffee", provider="github", repo_root="/r")
    db.add(repo)
    await db.commit()

    assert (await client.put("/api/v1/admin/code-style", json={"max_lines_per_file": 280},
                             headers=bearer(owner))).status_code == 403
    assert (await client.put("/api/v1/admin/code-style", json={"max_lines_per_file": 280},
                             headers=bearer(admin.id))).json() == {"profile": {"max_lines_per_file": 280}}
    base = f"/api/v1/workspaces/{workspace_id}"
    assert (await client.put(f"{base}/code-style", json={"tests_max_lines": 450},
                             headers=bearer(member))).status_code == 403
    assert (await client.put(f"{base}/code-style", json={"tests_max_lines": 450},
                             headers=bearer(owner))).status_code == 200
    refused = await client.put(f"{base}/repositories/{repo.id}/code-style", json={"max_function_lines": "x"},
                               headers=bearer(owner))
    assert refused.status_code == 400 and refused.json()["path"] == "repository.max_function_lines"
    assert (await client.put(f"{base}/repositories/{repo.id}/code-style",
                             json={"languages": {"dart": {"max_function_lines": 40}}},
                             headers=bearer(owner))).status_code == 200

    preview = (await client.get(f"{base}/code-style/effective", params={"repository": repo.id, "language": "dart"},
                                headers=bearer(member))).json()["effective"]
    assert preview["max_lines_per_file"] == {"value": 280, "source": "installation"}
    assert preview["tests_max_lines"] == {"value": 450, "source": "workspace"}
    assert preview["max_function_lines"] == {"value": 40, "source": "repository.languages.dart"}
    assert (await client.get(f"{base}/code-style/effective", params={"language": "cobol"},
                             headers=bearer(member))).status_code == 400


def test_the_platform_judges_the_change_by_the_resolved_style():
    from app.services.code_style.check import findings

    dart = flat(effective({}, "dart"))
    style = {"general": flat(effective({}, None)), "languages": {"dart": dart, "python": flat(effective({}, "python"))}}
    sizes = {
        "files": {"lib/features/cart/presentation/cart_page.dart": 420, "lib/core/http.dart": 310,
                  "lib/core/legacy.dart": 900, "lib/core/old.dart": 800, "test/cart_test.dart": 480,
                  "lib/widgets/Button.dart": 20, "lib/l10n/app_de.arb": 5000, "lib/core/x.g.dart": 3000,
                  "app/api.py": 100},
        "base_files": {"lib/core/http.dart": 250, "lib/core/legacy.dart": 850, "lib/core/old.dart": 800},
        "functions": [["app/api.py", "handle", 75]],
        "todos": [["app/api.py", 3, "# TODO fix later"], ["app/api.py", 4, "# TODO(CAF-42) after the reset"]],
        "commented_code": [["app/api.py", 10, 4]],
    }
    found = {(item.rule, item.path, item.severity) for item in findings(style, sizes)}
    assert ("max_lines_per_file", "lib/features/cart/presentation/cart_page.dart", "error") in found  # new, over
    assert ("max_lines_per_file", "lib/core/http.dart", "error") in found  # grown past the limit
    assert ("max_lines_per_file", "lib/core/legacy.dart", "error") in found  # over before and grew
    assert ("max_lines_per_file", "lib/core/old.dart", "warning") in found  # over before, not grown
    assert not any(path == "test/cart_test.dart" for _rule, path, _s in found)  # tests: 500
    assert ("naming", "lib/widgets/Button.dart", "error") in found and \
        ("layout", "lib/widgets/Button.dart", "error") in found
    assert not any(path.endswith((".arb", ".g.dart")) for _rule, path, _s in found)  # l10n and generated excluded
    assert ("max_function_lines", "app/api.py", "error") in found
    assert [item.line for item in findings(style, sizes) if item.rule == "todo_requires_ticket"] == [3]
    assert ("no_commented_code", "app/api.py", "error") in found


@pytest.mark.asyncio
async def test_a_changing_phase_gets_the_style_brief_and_the_reviewer_its_checklist(db, monkeypatch):
    from app.services.code_style.brief import REVIEW_INSTRUCTION, reviewer_checklist
    from app.services.workflow_runs.octryx.hooks import session_contract
    from tests.server_build_lock import lift_server_build_lock
    from tests.workflow_run_octryx_support import _bound_run, _fix_definition

    lift_server_build_lock(monkeypatch)
    _run, gateway, _key, _workspace_id = await _bound_run(db, _fix_definition(protect=False))
    phase = (await session_contract(db, gateway))["phase"]
    assert phase["code_style_brief"].startswith("Code style of this installation")
    assert "Files at most 300 lines (tests 500); functions at most 60 lines" in phase["code_style_brief"]
    assert phase["code_style"]["languages"]["dart"]["max_lines_per_file"] == 300
    assert "code_conventions" not in phase
    checklist = reviewer_checklist(phase["code_style"])
    assert not checklist.startswith("Code style of this installation") and "lib/features/*/presentation/**" in checklist
    assert "Style (<rule>):" in REVIEW_INSTRUCTION and "never high" in REVIEW_INSTRUCTION


def test_a_formatter_or_linter_problem_or_a_missing_tool_is_red():
    from app.services.code_style.tool_check import tool_findings

    found = tool_findings([
        {"language": "dart", "kind": "formatter", "tool": "dart", "state": "missing"},
        {"language": "python", "kind": "linter", "tool": "ruff", "state": "failed", "config": "repo",
         "output": "app.py:1:1: F401 unused"},
        {"language": "go", "kind": "linter", "tool": "go", "state": "skipped"},
        {"language": "python", "kind": "formatter", "tool": "ruff", "state": "ok"}])
    assert [item.text() for item in found] == [
        "dart: formatter dart is not installed (dart): install the Flutter SDK (flutter.dev) and put it on PATH "
        "[formatter]",
        "python: ruff found problems (python, the repository's configuration): app.py:1:1: F401 unused [linter]"]
    from app.services.code_style.brief import agent_brief
    from app.services.code_style.resolve import effective, flat

    brief = agent_brief({"general": flat(effective({}, None)), "languages": {"dart": flat(effective({}, "dart"))}})
    assert "run `dart format --output=none --set-exit-if-changed` and `flutter analyze --no-pub`" in brief


def test_rust_java_and_kotlin_have_their_official_tools_and_layout():
    java = flat(effective({}, "java"))
    assert java["formatter"]["variants"][0]["command"] == "./gradlew -q spotlessCheck"
    assert java["linter"]["command"] == "checkstyle -c /google_checks.xml {files}"
    assert "src/main/java/**" in java["layout"]["patterns"] and java["naming"]["file"] == r"^[A-Z][A-Za-z0-9]*\.java$"
    rust = flat(effective({}, "rust"))
    assert (rust["formatter"]["command"], rust["linter"]["command"]) == (
        "cargo fmt --check", "cargo clippy --all-targets -- -D warnings")
    assert flat(effective({}, "kotlin"))["formatter"]["command"] == "ktlint {files}"
    with pytest.raises(CodeStyleError):
        normalize_profile({"languages": {"java": {"formatter": {"variants": [{"when": "x", "command": 1}]}}}})


def test_the_translations_have_the_same_keys_and_placeholders_in_every_language():
    from app.services.code_style.l10n_check import l10n_findings

    style = {"general": flat(effective({}, None)), "languages": {"dart": flat(effective({}, "dart"))}}
    facts = {"catalogs": [{"language": "dart", "namespace": "app", "files": {
        "en": {"path": "lib/l10n/app_en.arb", "keys": ["cartTitle", "itemsCount", "checkout_now"], "count": 3,
               "placeholders": {"itemsCount": ["count"]}},
        "de": {"path": "lib/l10n/app_de.arb", "keys": ["itemsCount", "checkout_now", "legacyKey"], "count": 3,
               "placeholders": {"itemsCount": ["n"]}},
        "fr": {"path": "lib/l10n/app_fr.arb", "keys": [f"k{n}" for n in range(3)], "count": 401}}}],
        "hardcoded": [["lib/cart_page.dart", 2, "Proceed to payment", "dart"]]}
    found = {(item.rule, item.path, item.severity) for item in l10n_findings(style, facts)}
    assert ("l10n_missing_keys", "lib/l10n/app_de.arb", "error") in found  # cartTitle
    assert ("l10n_extra_keys", "lib/l10n/app_de.arb", "warning") in found  # legacyKey
    assert ("l10n_placeholders", "lib/l10n/app_de.arb", "error") in found  # count vs n
    assert ("l10n_max_keys", "lib/l10n/app_fr.arb", "error") in found  # 401 > 400
    assert ("l10n_key_pattern", "lib/l10n/app_en.arb", "warning") in found  # checkout_now is not camelCase
    assert ("l10n_hardcoded_text", "lib/cart_page.dart", "warning") in found  # a warning by default
    strict = {"general": style["general"], "languages": {"dart": {**style["languages"]["dart"], "l10n": {
        **style["languages"]["dart"]["l10n"], "hardcoded_text": "error"}}}}
    assert [item.severity for item in l10n_findings(strict, {"hardcoded": facts["hardcoded"]})] == ["error"]


def test_translations_live_per_feature_keys_are_unique_and_the_merged_file_is_never_edited_by_hand():
    from app.services.code_style.brief import agent_brief
    from app.services.code_style.l10n_check import l10n_findings

    dart = flat(effective({}, "dart"))
    assert dart["l10n"]["files"] == ["lib/features/<namespace>/l10n/<lang>.arb"]
    assert dart["l10n"]["merged"] == {"target": "lib/l10n/app_<lang>.arb",
                                      "generated": ["lib/l10n/app_localizations*.dart"], "hand_edit": "error",
                                      "command": "octryx-claude l10n-merge {format} '{features}' {target}"}
    style = {"general": flat(effective({}, None)), "languages": {"dart": dart}}
    assert "octryx-claude l10n-merge arb 'lib/features/*/l10n/<lang>.arb' lib/l10n/app_<lang>.arb" in agent_brief(
        style)

    def catalog(feature, keys):
        return {"language": "dart", "namespace": feature, "files": {
            "en": {"path": f"lib/features/{feature}/l10n/en.arb", "keys": keys, "count": len(keys)}}}

    facts = {"catalogs": [catalog("beans", ["beansTitle", "cartTotal"]), catalog("cart", ["cartTotal"])],
             "changed": ["lib/l10n/app_de.arb"]}
    found = {(item.rule, item.path, item.severity) for item in l10n_findings(style, facts)}
    assert ("l10n_duplicate_key", "lib/features/beans/l10n/en.arb", "error") in found
    assert ("l10n_key_prefix", "lib/features/beans/l10n/en.arb", "warning") in found  # cartTotal in beans
    assert ("l10n_generated_edited", "lib/l10n/app_de.arb", "error") in found
    merged_run = {**facts, "changed": ["lib/l10n/app_de.arb", "lib/features/beans/l10n/de.arb"]}
    assert not any(item.rule == "l10n_generated_edited" for item in l10n_findings(style, merged_run))
    # The generated localizations edited by hand are red too, naming the merge.
    by_hand = [item for item in l10n_findings(style, {**facts, "changed": ["lib/l10n/app_localizations_de.dart"]})
               if item.rule == "l10n_generated_edited"]
    assert [(item.path, item.severity) for item in by_hand] == [("lib/l10n/app_localizations_de.dart", "error")]
    assert "octryx-claude l10n-merge arb 'lib/features/*/l10n/<lang>.arb'" in by_hand[0].message


def test_a_missing_tool_warns_with_how_to_install_it_unless_the_profile_makes_it_red():
    from app.services.code_style.tool_check import tool_findings

    style = {"general": flat(effective({}, None)), "languages": {"python": flat(effective({}, "python"))}}
    found = tool_findings([
        {"language": "python", "kind": "formatter", "tool": "ruff", "state": "missing", "os": "Darwin"},
        {"language": "python", "kind": "linter", "tool": "ruff", "state": "failed", "output": "F401"}], style)
    assert [(item.severity, item.message) for item in found] == [
        ("warning", "formatter ruff is not installed (python): brew install ruff"),
        ("error", "ruff found problems (python, the platform's defaults): F401")]
    strict = {**style, "languages": {"python": {**style["languages"]["python"], "missing_tool": "error"}}}
    assert tool_findings([{"language": "python", "kind": "formatter", "tool": "ruff", "state": "missing",
                           "os": "Linux"}], strict)[0].severity == "error"
    assert "uv tool install ruff" in tool_findings([{"language": "python", "kind": "formatter", "tool": "ruff",
                                                     "state": "missing", "os": "Linux"}], style)[0].message


def test_an_app_in_a_subfolder_is_laid_out_from_its_own_root():
    from app.services.code_style.check import app_relative, findings

    dart = flat(effective({}, "dart"))
    style = {"general": flat(effective({}, None)), "languages": {"dart": dart}}
    app = "coffee/flutter/claude"
    sizes = {"files": {f"{app}/test/app/persistence_reload_test.dart": 25, f"{app}/lib/core/store.dart": 40,
                       f"{app}/lib/widgets/button.dart": 20}, "base_files": {}}
    found = {(item.rule, item.path) for item in findings(style, sizes)}
    assert found == {("layout", f"{app}/lib/widgets/button.dart")}
    assert app_relative("tools/build.dart", ["lib/", "test/"]) == "tools/build.dart"


def test_a_function_already_over_its_limit_only_warns_unless_it_grows():
    from app.services.code_style.check import findings

    style = {"general": flat(effective({}, None)), "languages": {"python": flat(effective({}, "python"))}}
    path = "coffee/flutter/claude/system_test/run_system_test.py"
    sizes = {"files": {path: 400}, "base_files": {path: 410},
             "functions": [[path, "run_s2", 66], [path, "run_s4", 90], [path, "run_new", 70], [path, "run_s9", 62]],
             "base_functions": [[path, "run_s2", 82], [path, "run_s4", 77]]}
    found = {(item.path, item.message.split(" has ")[0], item.severity) for item in findings(style, sizes)
             if item.rule == "max_function_lines"}
    assert found == {(path, "function run_s2", "warning"), (path, "function run_s4", "error"),
                     (path, "function run_new", "error"), (path, "function run_s9", "error")}


def test_a_tool_result_that_is_only_old_debt_warns():
    from app.services.code_style.tool_check import tool_findings

    base = {"language": "python", "kind": "linter", "tool": "ruff", "state": "failed", "output": "E501 x.py:9"}
    assert [item.severity for item in tool_findings([base])] == ["error"]
    [old] = tool_findings([{**base, "old_debt": True}])
    assert old.severity == "warning" and "already had before this change" in old.message
