"""PR review bot: where to look closely, and why.

- each carefully read file is scored from its history (churn, bug fixes), its area (sensitive paths, the
  repository's own globs) and its size; the top five are listed with their reasons and the first changed line;
- skimmed and mechanical files are never hotspots; a file without a reason is none.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.pr_review_bot import hotspots
from app.services.pr_review_bot.render import build_post
from app.services.pr_review_bot.settings import BotSettingsError, parse_settings


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.autocrlf=false", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_the_sensitive_areas_and_the_score_with_reasons():
    assert hotspots.sensitive("app/auth/session.py") == "auth" and hotspots.sensitive("db/migrations/0042.sql")
    assert hotspots.sensitive("pay/totals.py") == "" and hotspots.sensitive("pay/rates.py", ("pay/rate*",)) == (
        "pay/rate*")
    points, reasons = hotspots.score("app/auth/session.py", commits=4, bug_fixes=2, area="auth", lines=120)
    assert reasons == ("touches a sensitive area (auth)", "2 bug fix(es) in the last 90 days",
                       "changed in 4 commits in the last 90 days", "a large change (120 lines)")
    assert points == pytest.approx(4 + 6 + 4 + 2.4)
    assert hotspots.score("x.py", commits=1, bug_fixes=0, area="", lines=5) == (0.0, ())


async def test_the_hotspots_of_a_pull_request_come_from_its_history(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "pay").mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    for index, subject in enumerate(["add totals", "fix rounding bug", "hotfix: negative totals", "tune totals"]):
        (root / "pay/totals.py").write_text(f"VALUE = {index}\n")
        (root / "pay/notes.py").write_text("NOTE = 1\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", subject)
    base = _git(root, "rev-parse", "HEAD")
    (root / "pay/totals.py").write_text("VALUE = 10\nOTHER = 2\n")
    (root / "pay/notes.py").write_text("NOTE = 2\n")
    _git(root, "commit", "-qam", "change both")
    head = _git(root, "rev-parse", "HEAD")
    files = [{"path": "pay/totals.py", "kind": "careful", "lines": 3}, {"path": "pay/notes.py", "kind": "careful",
                                                                        "lines": 2},
             {"path": "tests/test_auth.py", "kind": "skim", "lines": 400}]
    spots = await hotspots.hotspots(str(root), base, head, files)
    assert [spot.to_dict() for spot in spots] == [{"path": "pay/totals.py", "line": 1, "score": 10.0, "reasons": [
        "2 bug fix(es) in the last 90 days", "changed in 4 commits in the last 90 days"]}]
    # the pull request's own commit is not the file's past; notes.py changed in one commit before it, and the
    # skimmed test file is never a hotspot


def test_the_summary_says_where_to_look_closely():
    post = build_post({"verdict": "pass", "summary": "", "findings": []}, {}, provider="github", facts={
        "sha": "a" * 40, "triage": {"hotspots": [{"path": "app/auth/session.py", "line": 12, "score": 8, "reasons": [
            "touches a sensitive area (auth)", "a large change (120 lines)"]}]}})
    assert "**Look closely here:**" in post.summary
    assert "- `app/auth/session.py:12`: touches a sensitive area (auth); a large change (120 lines)" in post.summary


def test_the_repositorys_own_hotspot_globs_are_a_setting():
    assert parse_settings({"hotspot_paths": ["pay/rate*", "pay/rate*"]}).hotspot_paths == ("pay/rate*",)
    with pytest.raises(BotSettingsError):
        parse_settings({"trigger": "both", "hotspot_paths": "pay/*"}, strict=True)


async def test_an_empty_file_is_no_hotspot_and_the_larger_change_comes_first(tmp_path: Path):
    """An empty file such as pay/regions/__init__.py (+0 -0) is never listed."""
    root = tmp_path / "repo"
    (root / "pay/regions").mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    base = _git(root, "rev-parse", "HEAD")
    (root / "pay/regions/__init__.py").write_text("")
    (root / "pay/regions/a.py").write_text("A = 1\n")
    (root / "pay/regions/b.py").write_text("B = 1\nC = 2\nD = 3\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "regions")
    head = _git(root, "rev-parse", "HEAD")
    files = [{"path": "pay/regions/__init__.py", "kind": "careful", "lines": 0},
             {"path": "pay/regions/a.py", "kind": "careful", "lines": 1},
             {"path": "pay/regions/b.py", "kind": "careful", "lines": 3}]
    spots = await hotspots.hotspots(str(root), base, head, files, ("pay/regions/*",))
    assert [spot.path for spot in spots] == ["pay/regions/b.py", "pay/regions/a.py"]


async def test_the_pull_requests_own_commits_are_no_churn(tmp_path: Path):
    """"changed in 3 commits in the last 90 days" must not count the base's one commit and the pull request's
    two."""
    root = tmp_path / "repo"
    (root / "shop").mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "shop/pricing.py").write_text("A = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "Demo shop")
    base = _git(root, "rev-parse", "HEAD")
    for index, subject in enumerate(["Add coupon codes", "Unknown coupon codes are refused"]):
        (root / "shop/pricing.py").write_text(f"A = 1\nB = {index}\n")
        _git(root, "commit", "-qam", subject)
    head = _git(root, "rev-parse", "HEAD")
    files = [{"path": "shop/pricing.py", "kind": "careful", "lines": 11}]
    assert await hotspots.hotspots(str(root), base, head, files) == []
