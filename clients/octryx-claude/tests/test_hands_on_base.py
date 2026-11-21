"""Red regression scenarios run again on the base commit in a temporary worktree (finding 24)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from octryx_claude import hands_on_base


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    _git(tmp_path, "init", "-q", str(root))
    _git(root, "config", "user.name", "t")
    _git(root, "config", "user.email", "t@example.invalid")
    (root / "app" / "main.txt").write_text("base\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    (root / "app" / "main.txt").write_text("work\n")
    _git(root, "commit", "-qam", "work")
    return root, base


SCENARIOS = [{"id": "S1", "part": "feature"}, {"id": "S2", "part": "regression"}, {"id": "S3", "part": "regression"}]


def test_only_failed_regressions_are_rechecked():
    results = [{"id": "S1", "passed": False}, {"id": "S2", "passed": False}, {"id": "S3", "passed": True},
               {"id": "repo:tests/hands_on/x.json#1", "passed": False}]
    assert hands_on_base.failed_regressions(SCENARIOS, results) == ["S2", "repo:tests/hands_on/x.json#1"]


def test_a_regression_red_on_the_base_too_is_marked_and_the_worktree_is_gone(tmp_path):
    root, base = _repo(tmp_path)
    seen = {}

    def run(folder: Path, items: list[dict]) -> list[dict]:
        seen["text"] = (folder / "main.txt").read_text()
        seen["ids"] = [item["id"] for item in items]
        return [{"id": "S2", "passed": False}]

    again = hands_on_base.recheck_on_base(root, root / "app", base, SCENARIOS, ["S2"], run)
    assert set(again) == {"S2"} and seen == {"text": "base\n", "ids": ["S2"]}  # the base checkout, only the red one
    assert len(_git(root, "worktree", "list").splitlines()) == 1
    marked = hands_on_base.mark([{"id": "S2", "passed": False}, {"id": "S3", "passed": True}], again, base)
    assert marked[0]["pre_existing"] == base and "pre_existing" not in marked[1]


def test_green_on_the_base_stays_red_and_a_missing_base_is_no_comparison(tmp_path):
    root, base = _repo(tmp_path)
    assert hands_on_base.recheck_on_base(root, root / "app", base, SCENARIOS, ["S2"],
                                         lambda _folder, _items: [{"id": "S2", "passed": True}]) == {}
    assert hands_on_base.recheck_on_base(root, root / "app", "0" * 40, SCENARIOS, ["S2"],
                                         lambda _folder, _items: [{"id": "S2", "passed": False}]) == {}
    assert hands_on_base.recheck_on_base(root, root / "app", base, SCENARIOS, ["S2"],
                                         lambda _folder, _items: None) == {}  # the app did not start there


# A feature scenario whose seed created grinder M1, then the browser restarted; the in-memory app
# had lost M1, so "click M1" failed before the check of the grind setting, on the fix and on the base alike.
OE175 = {"id": "S1", "part": "feature",
         "seed": [{"do": "goto", "path": "/"}, {"do": "click", "text": "Add grinder"},
                  {"do": "fill", "label": "Name", "value": "M1"}, {"do": "click", "text": "Save"},
                  {"do": "expect_text", "text": "M1"}],
         "steps": [{"do": "goto", "path": "/"}, {"do": "click", "text": "Grinder"}, {"do": "click", "text": "M1"},
                   {"do": "expect_text", "text": "Grind setting"}, {"do": "expect_text", "text": "15"}]}


def test_a_feature_scenario_failing_on_the_base_at_the_same_setup_step_is_invalid_not_red():
    assert hands_on_base.target_step(OE175) == 9  # its last expect: the grind setting 15
    red = {"id": "S1", "passed": False, "failed_step": 7, "error": "nothing visible shows 'M1'"}
    assert hands_on_base.failed_features([OE175], [red]) == ["S1"]
    marked = hands_on_base.mark([red], {"S1": dict(red)}, "b" * 40, [OE175], {"S1"})
    assert marked[0]["invalid"] == {"reason": "data_lost_after_restart", "base": "b" * 40,
                                    "error": "nothing visible shows 'M1'"}
    at_check = {"id": "S1", "passed": False, "failed_step": 9}
    assert hands_on_base.failed_features([OE175], [at_check]) == []  # red at the checked step: the fix's to fix
    other_step = hands_on_base.mark([red], {"S1": {**red, "failed_step": 9}}, "b" * 40, [OE175], {"S1"})
    assert "invalid" not in other_step[0]  # red elsewhere on the base: the work broke the setup
    plain = {**OE175, "seed": []}
    assert hands_on_base.invalid_reason(plain, 2) == "setup_fails_on_base"


def test_the_launcher_ignores_an_unknown_key_with_a_warning():
    from octryx_claude.environment_file import validate_environment

    environment, errors = validate_environment({"test": "x", "serve": {"command": "npm start",
                                                                        "url": "http://127.0.0.1:3000/", "new": 1}})
    assert errors == [] and "new" in environment["warnings"][0]
