"""A unittest suite has no per-test report file: the pipeline runs it verbosely and sends the whole output, so the
platform reads every test's outcome (team-delivery's proofs) without the output tail cutting early tests off."""

from __future__ import annotations

import sys

from octryx_claude.output_redact import redact_outputs
from octryx_claude.pipeline_commands import run_commands, verbose_command

UNITTEST = [{"commands": [["python", "-m", "unittest"], ["python3", "-m", "unittest"]], "add": "-v",
             "unless": ["-v", "--verbose"]}]


def test_a_plain_unittest_call_gets_the_verbose_flag_and_nothing_else_does():
    assert verbose_command("python3 -m unittest discover -s tests", UNITTEST) == (
        "python3 -m unittest discover -s tests -v")
    assert verbose_command("cd app && python -m unittest", UNITTEST) == "cd app && python -m unittest -v"
    assert verbose_command("python3 -m unittest discover -s tests -v", UNITTEST) is None
    assert verbose_command("python3 -m unittest --verbose", UNITTEST) is None
    assert verbose_command("python3 -m unittest discover 2>&1 | tail -5", UNITTEST) is None
    assert verbose_command("python3 -m pytest -q", UNITTEST) is None
    assert verbose_command("python3 -m unittest", None) is None


def test_the_run_reports_under_the_declared_command_with_every_test_in_its_report(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    cases = "".join(f"    def test_{index:03d}(self):\n        self.assertTrue(True)\n\n" for index in range(600))
    (tmp_path / "tests" / "test_many.py").write_text(
        f"import unittest\n\n\nclass ManyTest(unittest.TestCase):\n{cases}", encoding="utf-8")
    command = f"{sys.executable} -m unittest discover -s tests"
    spec = [{**UNITTEST[0], "commands": [[sys.executable, "-m", "unittest"]]}]
    [result] = run_commands({"commands": [command], "report_args": spec}, tmp_path)
    assert result["command"] == command and result["ran"] == f"{command} -v" and result["exit_code"] == 0
    assert "test_000 (" in result["report_text"] and "test_599 (" in result["report_text"]
    assert "test_000 (" not in result["output_tail"]  # the tail alone would have lost the first tests


def test_a_secret_a_test_prints_leaves_the_device_redacted_in_the_report(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    # The test builds the token at run time: no secret-shaped literal sits in this repository.
    (tmp_path / "tests" / "test_leak.py").write_text(
        "import sys\nimport unittest\n\n\nclass LeakTest(unittest.TestCase):\n    def test_leak(self):\n"
        "        print('clone with ghp_' + 'a1B2' * 9, file=sys.stderr)\n", encoding="utf-8")
    command = f"{sys.executable} -m unittest discover -s tests"
    spec = [{**UNITTEST[0], "commands": [[sys.executable, "-m", "unittest"]]}]
    [result] = run_commands({"commands": [command], "report_args": spec}, tmp_path)
    token = "ghp_" + "a1B2" * 9
    assert token in result["report_text"]  # what the run printed, before it leaves the device
    sent = redact_outputs({"results": [result]})["results"][0]
    assert token not in sent["report_text"] and "test_leak (" in sent["report_text"]
