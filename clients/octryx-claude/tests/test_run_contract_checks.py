from __future__ import annotations

import hashlib

from octryx_claude import run_contract
from tests.run_contract_support import _contract

from .gitrepo import make_repo, requires_git


def test_the_platform_runs_the_official_formatter_and_linter_and_reports_a_missing_one(
        tmp_path, monkeypatch):
    import stat

    from octryx_claude.style_tools import run_tools

    tools = tmp_path / ".venv" / "bin"
    tools.mkdir(parents=True)
    ruff = tools / "ruff"
    ruff.write_text("#!/bin/sh\nif [ \"$1\" = check ]; then\n  echo \"app.py:1:1: F401 unused\"; echo \"$@\"; exit 1\n"
                    "fi\nexit 0\n")
    ruff.chmod(ruff.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "app.py").write_text("import os\n")
    (tmp_path / "web.ts").write_text("export const x = 1\n")
    style = {"languages": {
        "python": {"formatter": {"command": "ruff format --check {files}"},
                   "linter": {"command": "ruff check --select E,F,I,B {files}",
                              "repo_config_command": "ruff check {files}", "config_files": ["ruff.toml"]}},
        "typescript": {"formatter": {"command": "octryx-no-such-prettier --check {files}"}}}}
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    results = {(item["language"], item["kind"]): item for item in run_tools(tmp_path, style, ["app.py", "web.ts"])}
    assert results[("python", "formatter")]["state"] == "ok"
    lint = results[("python", "linter")]
    assert (lint["state"], lint["config"]) == ("failed", "platform") and "--select E,F,I,B app.py" in lint["output"]
    assert results[("typescript", "formatter")]["state"] == "missing"
    (tmp_path / "ruff.toml").write_text("line-length = 100\n")
    lint = {item["kind"]: item for item in run_tools(tmp_path, style, ["app.py"])}["linter"]
    assert lint["config"] == "repo" and "--select" not in lint["output"]  # the repository's own config wins


def test_the_builds_own_formatter_wins_and_each_package_is_its_build_folder(tmp_path, monkeypatch):
    import stat

    from octryx_claude.style_tools import run_tools

    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    service = tmp_path / "service"
    (service / "src" / "main" / "java" / "app").mkdir(parents=True)
    (service / "src" / "main" / "java" / "app" / "Main.java").write_text("class Main {}\n")
    (service / "build.gradle").write_text("plugins { id 'com.diffplug.spotless' }\nspotless { java {} }\n")
    gradlew = service / "gradlew"
    gradlew.write_text("#!/bin/sh\necho \"gradle $@\"\nexit 0\n")
    gradlew.chmod(gradlew.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "engine" / "src").mkdir(parents=True)
    (tmp_path / "engine" / "Cargo.toml").write_text("[package]\nname = 'engine'\n")
    (tmp_path / "engine" / "src" / "lib.rs").write_text("pub fn f() {}\n")
    style = {"languages": {
        "java": {"formatter": {"variants": [{"when": ["build.gradle*:spotless"],
                                             "command": "./gradlew -q spotlessCheck"}],
                               "command": "google-java-format --dry-run --set-exit-if-changed {files}"}},
        "rust": {"formatter": {"command": "cargo fmt --check"}}}}
    results = {item["language"]: item for item in run_tools(
        tmp_path, style, ["service/src/main/java/app/Main.java", "engine/src/lib.rs"])}
    assert (results["java"]["tool"], results["java"]["state"], results["java"]["folder"]) == (
        "./gradlew", "ok", "service")
    assert results["rust"]["folder"] == "engine" and results["rust"]["tool"] == "cargo"


def test_the_translations_and_new_ui_text_are_read_for_the_platforms_check(tmp_path):
    import json
    import subprocess

    from octryx_claude.style_l10n import catalogs, hardcoded

    app = tmp_path / "coffee" / "web" / "claude"
    (app / "lib" / "l10n").mkdir(parents=True)
    (app / "lib" / "l10n" / "app_en.arb").write_text(json.dumps({
        "@@locale": "en", "cartTitle": "Cart", "itemsCount": "{count, plural, one{1 item} other{{count} items}}",
        "@itemsCount": {"placeholders": {"count": {}}}}))
    (app / "lib" / "l10n" / "app_de.arb").write_text(json.dumps({"@@locale": "de", "itemsCount": "{n} Artikel"}))
    (tmp_path / "locales" / "en").mkdir(parents=True)
    (tmp_path / "locales" / "en" / "checkout.json").write_text(json.dumps({"checkout": {"pay": {"button": "Pay"}}}))
    style = {"languages": {
        "dart": {"l10n": {"format": "arb", "files": ["lib/l10n/app_<lang>.arb"]}},
        "typescript": {"l10n": {"format": "i18next", "files": ["locales/<lang>/<namespace>.json"]}}}}
    found = {(item["language"], item["namespace"]): item for item in catalogs(tmp_path, style)}
    dart = found[("dart", "app")]["files"]
    assert dart["en"]["path"] == "coffee/web/claude/lib/l10n/app_en.arb" and dart["en"]["keys"] == [
        "cartTitle", "itemsCount"]
    assert dart["en"]["placeholders"] == {"itemsCount": ["count"]} and dart["de"]["placeholders"] == {
        "itemsCount": ["n"]}
    assert found[("typescript", "checkout")]["files"]["en"]["keys"] == ["checkout.pay.button"]

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    page = app / "lib" / "cart_page.dart"
    page.write_text("final a = Text(context.l10n.cartTitle);\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "b"],
                   check=True)
    base = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    page.write_text("final a = Text(context.l10n.cartTitle);\nfinal b = Text('Proceed to payment');\n"
                    "final c = AppBar(title: const Text('Your cart'));\n")
    assert hardcoded(tmp_path, base, ["coffee/web/claude/lib/cart_page.dart"]) == [
        ["coffee/web/claude/lib/cart_page.dart", 2, "Proceed to payment", "dart"],
        ["coffee/web/claude/lib/cart_page.dart", 3, "Your cart", "dart"]]


def test_the_features_translations_merge_per_language_and_a_shared_key_fails(tmp_path, monkeypatch):
    import json

    from octryx_claude import l10n_merge

    for feature, keys in (("beans", {"beansTitle": "Beans", "@beansTitle": {"description": "x"}}),
                          ("cart", {"cartTotal": "Total {sum}"})):
        folder = tmp_path / "lib" / "features" / feature / "l10n"
        folder.mkdir(parents=True)
        (folder / "en.arb").write_text(json.dumps({"@@locale": "en", **keys}))
    monkeypatch.chdir(tmp_path)
    assert l10n_merge.main(["arb", "lib/features/*/l10n/<lang>.arb", "lib/l10n/app_<lang>.arb"]) == 0
    merged = json.loads((tmp_path / "lib" / "l10n" / "app_en.arb").read_text())
    assert merged["@@locale"] == "en" and merged[l10n_merge.MARKER_KEY].startswith("by octryx-claude l10n-merge")
    assert (merged["beansTitle"], merged["cartTotal"], merged["@beansTitle"]) == ("Beans", "Total {sum}",
                                                                                   {"description": "x"})
    (tmp_path / "lib" / "features" / "cart" / "l10n" / "en.arb").write_text(json.dumps({"beansTitle": "Again"}))
    assert l10n_merge.main(["arb", "lib/features/*/l10n/<lang>.arb", "lib/l10n/app_<lang>.arb"]) == 1


@requires_git
def test_a_confirmed_test_of_an_app_in_a_subfolder_is_found_in_its_app_folder(state, tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    app = repo / "coffee" / "flutter" / "claude" / "test" / "app"
    app.mkdir(parents=True)
    (app / "x_test.dart").write_text("void main() {}\n")
    contract = _contract(phase={**_contract()["phase"], "protected_files": ["test/app/x_test.dart"]},
                         run={**_contract()["run"], "entry": 7, "current_node": {"id": "fix"}})
    contract["preparation"] = {"environment": {"source": "environment_file", "app_folder": "coffee/flutter/claude"}}
    reported = run_contract.facts(contract, root=repo.resolve(), with_diff=False)
    expected = "sha256:" + hashlib.sha256((app / "x_test.dart").read_bytes()).hexdigest()
    assert reported["confirmed_test_digests"] == {"test/app/x_test.dart": expected}
