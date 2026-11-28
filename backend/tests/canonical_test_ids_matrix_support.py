"""Shared helpers for the test_canonical_test_ids_matrix_* modules."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.workflow_checks.library import TurnEvidence, evaluate_checks
from app.services.workflow_checks.test_ids import Resolver
from app.services.workflow_checks.test_results import test_run_from_tool as run_from_tool
from app.services.workflow_runs.gateway_tests import bash_test_results, gateway_test_run
from app.services.workflow_runs.test_resolution import resolve_entry

TEXTKIT = '''import re


def slugify(text):
    return text  # not implemented yet


def normalize_whitespace(text):
    return " ".join(text.split())
'''


TEXTKIT_TESTS = '''from textkit import normalize_whitespace, slugify


def test_slugify_lowercases():
    assert slugify("Hello") == "hello"


def test_slugify_replaces_spaces():
    assert slugify("a b") == "a-b"


def test_normalize_whitespace_collapses_and_trims():
    assert normalize_whitespace("  a   b ") == "a b"


def test_normalize_whitespace_empty():
    assert normalize_whitespace("") == ""
'''


NEW = ["tests/test_textkit.py::test_slugify_lowercases", "tests/test_textkit.py::test_slugify_replaces_spaces"]


RED = [{"type": "tests_red", "params": {}, "blocking": True, "description": "Red"}]


GREEN = [{"type": "tests_green", "params": {"require_red_first": False}, "blocking": True, "description": "Green"}]


def _repo(root: Path, files: dict[str, str]) -> Path:
    for relative, content in {"pytest.ini": "[pytest]\n", **files}.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def _environment() -> dict[str, str]:
    # The outer test session's pytest/xdist settings never leak into the repository's own run.
    return {key: value for key, value in os.environ.items() if not key.startswith(("PYTEST", "PYTHONPATH"))}


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=root, capture_output=True, text=True, timeout=180,
                          env={**_environment(), "PYTHONPATH": str(root)})


def _pytest(root: Path, *args: str, junit: bool = False) -> tuple[subprocess.CompletedProcess, str | None]:
    report = root / "test-reports" / "report.xml"
    extra = ["--junitxml=test-reports/report.xml"] if junit else []
    done = _run(root, "-m", "pytest", "-p", "no:cacheprovider", "-o", "addopts=", *args, *extra)
    return done, (report.read_text() if junit and report.exists() else None)


def _chat_run(done: subprocess.CompletedProcess, root: Path | None, files=()) -> dict:
    entry = run_from_tool("run_test_suite", {"stdout": done.stdout, "stderr": done.stderr,
                                                  "exit_code": done.returncode}, source="chat")
    return resolve_entry(entry, Resolver(files, root))


def _device_run(done: subprocess.CompletedProcess, xml: str | None, *, files=(), report_files=()) -> dict:
    params = {"test_report": {"format": "junit", "junit_xml": xml, "files": list(report_files)}} if xml else {}
    parsed, hints = bash_test_results(params, done.stdout)
    return resolve_entry(gateway_test_run(parsed, hints, green=done.returncode == 0), Resolver(files))


def _decide(checks: list[dict], run: dict, confirmed: list[str], roles: dict | None = None):
    [result] = evaluate_checks(checks, TurnEvidence(test_runs=[run], confirmed_tests=confirmed,
                                                    confirmed_test_roles=roles or {}))
    return result


def _ids(run: dict) -> dict[str, str]:
    return {test_id: value["outcome"] for test_id, value in run["results"].items()}


@pytest.fixture
def textkit(tmp_path) -> Path:
    return _repo(tmp_path, {"textkit.py": TEXTKIT, "tests/test_textkit.py": TEXTKIT_TESTS})
