"""PR review bot: how to read a pull request (a mechanical file is left out of the reviewer's diff):

- mechanical only when it surely is: a rename at 100 %, line endings only, whitespace only where it carries no
  meaning, Python with the same syntax tree and the same pragmas; a Python indentation change never is;
- the review's evidence checks every claimed path again: a path the check does not confirm stays in the diff, what is
  left out is listed and kept on the run; without the key the diff is byte-identical;
- tests, lockfiles, translations and documentation are skimmed; the size brake suggests a split, never blocks.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.pr_review_bot.render import build_post
from app.services.pr_review_bot.settings import BotSettingsError, parse_settings
from app.services.pr_review_bot.triage import CAREFUL, MECHANICAL, SKIM, FileTriage, classify, size_note
from app.services.workflow_runs.review.evidence import change_under_review
from app.services.workflow_runs.review.mechanical import mechanical_reason


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.autocrlf=false", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


BEFORE = {
    "pay/totals.py": "def total(items):\n    if items:\n        x = sum(items)\n        return x\n    return 0\n",
    "pay/fmt.py": "def f(a,b):\n    return a+b\n",
    "pay/lint.py": "import os\n",
    "web/cart.ts": "export function cart(a) { return a; }\n",
    "deploy/app.yaml": "a:\n  b: 1\n",
    "ci.yaml": "x: 1\n",
    "pay/old_name.py": "VALUE = 1\n",
    "pay/moved.py": "VALUE = 2\n",
    "tests/test_pay.py": "def test_x():\n    assert True\n",
    "README.md": "# Pay\n",
}
AFTER = {
    "pay/totals.py": "def total(items):\n    if items:\n        x = sum(items)\n    return x\n    return 0\n",  # out of if
    "pay/fmt.py": "def f(a, b):\n    return a + b  # formatted\n",
    "pay/lint.py": "import os  # noqa: F401\n",
    "web/cart.ts": "export  function cart(a) {  return a;  }\n",  # spaces only, the lines stay
    "deploy/app.yaml": "a:\n    b: 1\n",  # indentation in YAML has meaning
    "ci.yaml": "x: 1\r\n",
    "pay/new_name.py": "VALUE = 1\n",  # renamed at 100 %
    "pay/moved_and_changed.py": "VALUE = 3\n",
    "tests/test_pay.py": "def test_x():\n    assert 1\n",
    "README.md": "# Pay shop\n",
}


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "repo"
    for path, text in BEFORE.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(text.encode())
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    base = _git(root, "rev-parse", "HEAD")
    for path in ("pay/old_name.py", "pay/moved.py"):
        (root / path).unlink()
    for path, text in AFTER.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(text.encode())
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "change")
    return root, base, _git(root, "rev-parse", "HEAD")


async def test_only_surely_mechanical_changes_count(repo):
    root, base, head = repo
    reasons = {path: await mechanical_reason(root, base, path, head=head) for path in (
        "pay/totals.py", "pay/fmt.py", "pay/lint.py", "web/cart.ts", "deploy/app.yaml", "ci.yaml")}
    assert reasons == {"pay/totals.py": "", "pay/fmt.py": "same Python syntax tree (formatting or comments only)",
                       "pay/lint.py": "", "web/cart.ts": "whitespace only", "deploy/app.yaml": "",
                       "ci.yaml": "line endings only"}
    assert await mechanical_reason(root, base, "pay/new_name.py", old="pay/old_name.py", head=head) == (
        "renamed from pay/old_name.py without a change")
    assert await mechanical_reason(root, base, "pay/moved_and_changed.py", old="pay/moved.py", head=head) == ""


async def test_the_files_are_read_carefully_skimmed_or_left_out(repo):
    root, base, head = repo
    kinds = {item.path: (item.kind, item.reason) for item in await classify(str(root), base, head, {})}
    assert kinds["pay/totals.py"] == (CAREFUL, "") and kinds["deploy/app.yaml"] == (CAREFUL, "")
    assert kinds["tests/test_pay.py"] == (SKIM, "test") and kinds["README.md"] == (SKIM, "documentation")
    assert kinds["web/cart.ts"][0] == MECHANICAL and kinds["ci.yaml"][0] == MECHANICAL


async def test_the_evidence_leaves_out_only_what_it_confirms_itself(repo):
    root, base, head = repo
    _git(root, "checkout", "-q", head)  # the staged copy is the pull request's head
    plain = SimpleNamespace(context={"base_sha": base})
    diff_plain, tree = await change_under_review(plain, root)
    again, _tree = await change_under_review(SimpleNamespace(context={"base_sha": base}), root)
    assert diff_plain == again and "web/cart.ts" in diff_plain  # without the key: byte-identical
    claimed = SimpleNamespace(context={"base_sha": base, "review_summarized_paths": [
        {"path": "web/cart.ts"}, {"path": "pay/totals.py"}, {"path": "pay/new_name.py", "old": "pay/old_name.py"}]})
    diff, tree_after = await change_under_review(claimed, root)
    assert tree_after == tree  # the reviewed tree never changes
    assert "+++ b/web/cart.ts" not in diff and "mechanical change (whitespace only): web/cart.ts" in diff
    assert "+++ b/pay/totals.py" in diff  # an indentation change in Python is claimed but not confirmed: shown
    assert "renamed to pay/new_name.py: pay/old_name.py" in diff
    assert claimed.context["review_left_out"] == ["web/cart.ts", "pay/new_name.py", "pay/old_name.py"]


def test_the_size_brake_suggests_a_split_and_never_blocks():
    files = [FileTriage(f"pay/core/f{n}.py", CAREFUL, "", 40) for n in range(20)] + [
        FileTriage(f"web/ui/c{n}.ts", CAREFUL, "", 30) for n in range(10)] + [
        FileTriage("tests/test_x.py", SKIM, "test", 900)]
    note = size_note(files, 800, 25)
    assert note.startswith("**Large pull request:** 30 file(s) and 1100 changed lines")
    assert "1. `pay/` (20 file(s), 800 lines: f0.py … f19.py)" in note and "2. `web/` (10 file(s), 300 lines" in note
    assert size_note(files[:5], 800, 25) == ""
    post = build_post({"verdict": "pass", "summary": "", "findings": []}, {}, provider="github", facts={
        "sha": "a" * 40, "triage": {"files": [item.to_dict() for item in files], "size_note": note}})
    assert post.state == "success" and "**Large pull request:**" in post.summary


def test_the_size_limits_are_settings_of_the_repository():
    assert (parse_settings({}).size_limit_lines, parse_settings({}).size_limit_files) == (800, 25)
    assert parse_settings({"size_limit_lines": 2000}).size_limit_lines == 2000
    with pytest.raises(BotSettingsError):
        parse_settings({"trigger": "both", "size_limit_files": 0}, strict=True)


def test_one_folder_above_the_limit_is_split_in_batches_never_shown_as_one_group():
    """"1. pay/regions/ (28 files)" must not be the whole pull request."""
    from app.services.pr_review_bot.triage import split

    regions = [FileTriage(f"pay/regions/region_{n:02}.py", CAREFUL, "", 25) for n in range(1, 28)]
    groups = split(regions, 800, 12)
    assert [(name, len(items)) for name, items in groups] == [
        ("pay/regions/ (1/3)", 12), ("pay/regions/ (2/3)", 12), ("pay/regions/ (3/3)", 3)]
    assert groups[0][1][0].path.endswith("region_01.py") and groups[1][1][0].path.endswith("region_13.py")
    nested = [FileTriage(f"app/{part}/m{n}.py", CAREFUL, "", 10) for part in ("api", "db") for n in range(10)]
    assert [name for name, _items in split(nested, 800, 12)] == ["app/api/", "app/db/"]  # one level deeper
