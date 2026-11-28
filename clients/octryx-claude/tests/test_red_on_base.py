import sys

from octryx_claude.red_on_base import run

from .gitrepo import git, make_repo, requires_git

# stacks.json test_runner.only_files of the python stack, as the platform sends it.
UNIT = [["python", "-m", "unittest"], ["python3", "-m", "unittest"]]
ONLY_FILES = [
    {"commands": [["pytest"], ["python", "-m", "pytest"], ["python3", "-m", "pytest"]], "argv": "{test} {files}"},
    {"commands": UNIT, "contains": "discover", "single_file": True, "argv": "{test} -v -p {basename}"},
    {"commands": UNIT, "lacks": "discover", "argv": "{prefix} -v {modules}"},
    {"commands": [["flutter", "test"]], "argv": "{test} {files}"},
]
UNITTEST = ("import unittest\n\n\nclass GrindTest(unittest.TestCase):\n    def test_grind_starts_at_15(self):\n"
            "        from grind import start\n        self.assertEqual(start(), 15)\n")
TEST = "def test_grind_starts_at_15():\n    from grind import start\n    assert start() == 15\n"


def _repo(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    app = repo / "app"
    (app / "tests").mkdir(parents=True)
    (app / "grind.py").write_text("def start():\n    return 1\n")  # the reported bug
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


@requires_git
def test_the_changes_confirmed_test_runs_on_the_base_and_fails_there_with_nothing_left_behind(tmp_path, monkeypatch):
    repo, base = _repo(tmp_path, monkeypatch)
    (repo / "app" / "grind.py").write_text("def start():\n    return 15\n")  # the fix, in the working copy
    (repo / "app" / "tests" / "test_grind.py").write_text(TEST)  # and its reproduction test, not committed
    environment = {"test": f"{sys.executable} -m pytest -v -p no:cacheprovider"}
    report = run({"base": base, "files": ["tests/test_grind.py"], "only_files": ONLY_FILES}, repo, "app", environment,
                 [])
    assert report["exit_code"] == 1 and "test_grind_starts_at_15 FAILED" in report["output_tail"]
    assert report["command"].endswith("tests/test_grind.py")
    assert git(repo, "worktree", "list").count("\n") == 0  # the base checkout is gone again
    assert (repo / "app" / "grind.py").read_text().endswith("return 15\n")  # the working copy is untouched


@requires_git
def test_a_weakened_test_passes_on_the_base_and_an_unknown_base_is_reported(tmp_path, monkeypatch):
    repo, base = _repo(tmp_path, monkeypatch)
    (repo / "app" / "tests" / "test_grind.py").write_text(
        "def test_grind_starts_at_15():\n    from grind import start\n    assert start() in (1, 15)\n")
    environment = {"test": f"{sys.executable} -m pytest -v -p no:cacheprovider"}
    assert run({"base": base, "files": ["tests/test_grind.py"], "only_files": ONLY_FILES}, repo, "app", environment,
               [])["exit_code"] == 0
    missing = run({"base": "0" * 40, "files": ["tests/test_grind.py"]}, repo, "app", environment, [])
    assert missing == {"reason": "the base commit could not be checked out"}


def test_a_step_asks_for_the_base_run_only_when_its_view_says_so_and_a_missing_environment_says_why(tmp_path):
    from octryx_claude.red_on_base import for_view

    assert for_view({"mode": "reproduce"}, tmp_path) is None
    asked = {"red_on_base": {"base": "b" * 40, "files": ["tests/test_grind.py"]},
             "environment_file": {"file": "app/.octryx/environment.json", "app_folder": "app"}}
    assert for_view(asked, tmp_path) == {"reason": "the environment file is not usable for the base run"}


@requires_git
def test_a_unittest_discover_command_runs_only_the_confirmed_file_from_its_own_start_folder(tmp_path, monkeypatch):
    repo, base = _repo(tmp_path, monkeypatch)
    (repo / "app" / "grind.py").write_text("def start():\n    return 15\n")
    (repo / "app" / "tests" / "helpers.py").write_text("EXPECTED = 15\n")
    (repo / "app" / "tests" / "test_grind.py").write_text(UNITTEST.replace(
        "self.assertEqual(start(), 15)", "from helpers import EXPECTED\n        self.assertEqual(start(), EXPECTED)"))
    environment = {"test": f"{sys.executable} -m unittest discover -s tests"}
    appended = run({"base": base, "files": ["tests/test_grind.py"], "only_files": []}, repo, "app",
                   {"test": f"{environment['test']} tests/test_grind.py"}, [])
    assert "test_grind_starts_at_15" not in appended["output_tail"]  # before: the guessed append ran no test
    python = [{"commands": [[sys.executable, "-m", "unittest"]], "contains": "discover", "single_file": True,
               "argv": "{test} -v -p {basename}"}]
    report = run({"base": base, "files": ["tests/test_grind.py"], "only_files": python}, repo, "app", environment, [])
    assert report["command"] == f"{sys.executable} -m unittest discover -s tests -v -p test_grind.py"
    assert report["exit_code"] == 1 and "test_grind_starts_at_15 (test_grind.GrindTest" in report["output_tail"]
    assert "FAIL" in report["output_tail"] and "ImportError" not in report["output_tail"]


def test_without_a_fitting_template_the_full_command_runs_never_a_guessed_append():
    from octryx_claude.red_on_base import _command

    def command(test: str, *files: str) -> str:
        return _command({"test": test}, [], list(files), ONLY_FILES)

    assert command("npm test", "test/a.test.js") == "npm test"
    assert command("pytest -q", "tests/test_a.py") == "pytest -q tests/test_a.py"
    assert command("cd app && python3 -m unittest discover -s tests", "tests/test_a.py") == \
        "cd app && python3 -m unittest discover -s tests -v -p test_a.py"
    assert command("python3 -m unittest discover -s tests", "tests/test_a.py", "tests/test_b.py") == \
        "python3 -m unittest discover -s tests"  # -p takes one pattern: the full run
    assert command("python3 -m unittest", "tests/test_a.py") == "python3 -m unittest -v tests.test_a"
    assert command("python3 -m unittest", "tests/data.json") == "python3 -m unittest"
    assert command('python3 -m unittest discover -s "my tests"', "my tests/test_a.py") == \
        'python3 -m unittest discover -s "my tests" -v -p test_a.py'
    assert command("flutter test --dart-define=ENV=ci", "test/a_test.dart") == \
        "flutter test --dart-define=ENV=ci test/a_test.dart"  # its options stay
