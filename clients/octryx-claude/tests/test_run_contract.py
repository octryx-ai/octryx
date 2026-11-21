"""S10: the launcher relays the workflow run contract and reports the working copy's facts; it decides nothing."""

from __future__ import annotations

import hashlib
import subprocess

from octryx_claude import run_contract
from tests.run_contract_support import _contract

from .gitrepo import git, make_repo, requires_git


@requires_git
def test_facts_are_bound_to_the_pass_and_the_change_carries_new_files(state, tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_totals.py").write_text("def test_x():\n    assert 1\n")
    (repo / "src" / "app.py").write_text("print('changed')\n")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "src" / "rounding.py").write_text("def half_up(x):\n    return x\n")  # untracked

    contract = _contract(facts={"base_sha": base}, run={**_contract()["run"], "entry": 7,
                                                        "current_node": {"id": "fix"}})
    reported = run_contract.facts(contract, root=repo.resolve(), with_diff=True)
    expected = "sha256:" + hashlib.sha256((repo / "tests" / "test_totals.py").read_bytes()).hexdigest()
    assert (reported["node_id"], reported["entry"]) == ("fix", 7)
    assert reported["confirmed_test_digests"] == {"tests/test_totals.py": expected}
    # The text goes along, so the server can tell a reformatted confirmed test from a changed one (kalt run 3b).
    assert reported["confirmed_test_texts"] == {"tests/test_totals.py": "def test_x():\n    assert 1\n"}
    assert "+print('changed')" in reported["change"]["patch"]
    assert "+def half_up(x):" in reported["change"]["patch"]  # the reviewer sees new files too
    assert git(repo, "status", "--porcelain").count("??") == 2  # the user's own index is untouched
    assert "change" not in run_contract.facts(contract, root=repo.resolve(), with_diff=False)
    unknown = _contract(facts={"base_sha": "f" * 40})
    assert run_contract.facts(unknown, root=repo.resolve(), with_diff=True)["change"]["base_unavailable"] is True
    (repo / "tests" / "test_totals.py").unlink()
    gone = run_contract.facts(contract, root=repo.resolve(), with_diff=False)
    assert gone["confirmed_test_digests"] == {} and gone["checked_files"] == ["tests/test_totals.py"]
    escape = _contract(phase={**contract["phase"], "protected_files": ["../outside.py"]})
    assert run_contract.facts(escape, root=repo.resolve(), with_diff=False)["confirmed_test_digests"] == {}
    assert run_contract.facts(None, root=repo.resolve(), with_diff=True) is None


def test_a_new_package_named_like_an_installed_distribution_is_reported(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    site = repo / ".venv" / "lib" / "python3.12" / "site-packages"
    (site / "iniconfig").mkdir(parents=True)
    (site / "evil-1.0.dist-info").mkdir()
    (repo / "pay").mkdir()
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    assert run_contract.shadows_installed(repo, "iniconfig/__init__.py") is True
    assert run_contract.shadows_installed(repo, "src/iniconfig/__init__.py") is True
    assert run_contract.shadows_installed(repo, "src/evil.py") is True  # a distribution's name, as a module
    assert run_contract.shadows_installed(repo, "pay/new.py") is False  # inside a package the repo has
    assert run_contract.shadows_installed(repo, "src/rounding.py") is False


def test_an_edit_reports_the_path_it_really_writes(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_totals.py").write_text("x")
    (repo / "link.py").symlink_to(repo / "tests" / "test_totals.py")
    (repo / "out.py").symlink_to(tmp_path)
    edit = {"tool_name": "Edit", "cwd": str(repo), "tool_input": {"file_path": str(repo / "link.py")}}
    assert run_contract.resolved_path(edit, repo) == "tests/test_totals.py"
    outside = {**edit, "tool_input": {"file_path": str(repo / "out.py" / "x.py")}}
    assert run_contract.resolved_path(outside, repo) == ".."
    assert run_contract.resolved_path({**edit, "tool_name": "Read"}, repo) is None


@requires_git
def test_a_text_file_that_is_not_utf8_reaches_the_change_byte_for_byte(tmp_path, monkeypatch):
    """A Latin-1 file without a NUL byte raised ``UnicodeDecodeError`` in ``change``; the
    work-git job ended without a report and was resent three times."""
    import subprocess

    from octryx_claude.contract_change import change

    repo = make_repo(tmp_path, monkeypatch)
    base = git(repo, "rev-parse", "HEAD")
    latin = "Café crème, Zürich\n".encode("latin-1")
    (repo / "menu notes [fr].txt").write_bytes(latin)
    (repo / "src" / "app.py").write_text("print('hällo')\n")

    result = change(repo, base)

    assert result.get("patch") and not result.get("base_unavailable"), result
    assert "hällo" in result["patch"]  # UTF-8 text stays a readable diff
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(repo), str(clone))
    subprocess.run(["git", "apply", "--binary", "-"], cwd=clone, input=result["patch"].encode(), check=True)
    assert (clone / "menu notes [fr].txt").read_bytes() == latin


@requires_git
def test_a_failed_git_step_is_tried_once_more_and_the_report_says_which_and_why(tmp_path, monkeypatch):
    """A failed git step is tried once more, and the report names the step and git's words."""
    from octryx_claude import contract_change, run_contract

    repo = make_repo(tmp_path, monkeypatch)
    base = git(repo, "rev-parse", "HEAD")
    (repo / "src" / "app.py").write_text("print('fixed')\n")
    real = contract_change._git
    failures = {"add": 1}

    def flaky(root, *args, **kwargs):
        if args[:2] == ("add", "-A") and failures["add"]:
            failures["add"] -= 1
            return subprocess.CompletedProcess(args, 128, "", "error: short read while indexing src/app.py")
        return real(root, *args, **kwargs)

    monkeypatch.setattr(contract_change, "_git", flaky)
    monkeypatch.setattr(contract_change, "CHANGE_RETRY_SECONDS", 0)
    result = run_contract.change(repo, base)
    assert "fixed" in result["patch"] and result["attempts"] == 2 and not result.get("base_unavailable")

    failures["add"] = 5
    gone = run_contract.change(repo, base)
    assert gone["base_unavailable"] and gone["attempts"] == 2
    assert gone["reason"] == "add -A: exit 128: error: short read while indexing src/app.py"
    assert run_contract.change(repo, "")["reason"] == "no base commit in the run contract"


def test_the_style_facts_find_todos_and_commented_out_code():
    """The platform checks TODOs without a ticket and commented-out code itself."""
    from octryx_claude.style_facts import commented_code, todos

    text = "\n".join(["def f():", "    # TODO fix", "    return 1", "# old = compute(x)", "# if old:",
                      "#     print(old)", "", "# A prose comment explains", "# why this exists", "# in words"])
    assert todos("a.py", text) == [["a.py", 2, "# TODO fix"]]
    assert commented_code("a.py", text) == [["a.py", 4, 3]]
    assert commented_code("b.dart", "/// Doc line one.\n/// final x = y;\n/// call(z);") == []  # doc comments
    assert commented_code("c.css", "/* x */") == []
