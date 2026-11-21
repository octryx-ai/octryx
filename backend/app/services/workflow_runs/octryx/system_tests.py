"""System tests of a changing phase: the app tested running, like CI.

The last **full** run counts, in any form (``shell_rules.full_suite_run``: the command's whole
selection, also with ``-q`` or piped into ``tail``), not only the command typed verbatim: the launcher runs every test
run outside Claude Code's sandbox with the device's Chrome (``octryx-claude`` ``local_tests``, ``browser``), so the rule
(``rule_text``) does not restrict the browser to the exact command.

Across several models, Gemma, MiniMax and Nemotron all passed their own unit tests' idea of the work while
ticking an item hung (the new handler read the request body a second time); nobody started the server. Hence the agent
must test that it works, since building a UI without ever seeing it is bad for a model too, and the tests must be
re-runnable like CI.

The repository declares a ``system_test`` command (``coding_setup.environment.system_test`` or
``coding_setup.system_test_commands``), e.g. ``.venv/bin/python -m pytest -v tests/system``: a Playwright suite in the
repository whose fixtures start the app and drive it over HTTP (``request``) and in a real browser. Every changing
phase gets the command and the rule (``rule_text``) in its contract (in a benchmark run the tests
saved one screenshot per page and a few states; cook mode showed the German heading "ingredients (for 2 servings)"
above nothing, a sidebar
stopped mid-page and "tbsp" stood on a German screen, and no test asserted any of it: so the rule asks for every
screen in every state a user reaches after an interaction, named per state, with its content asserted); at Stop the
pass's **last** run of that command must be green,
else a failed blocking check names what failed, so the phase stays open like a red unit test. A repository without the
command is unchanged.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from ....models import ToolCall
from ...workflow_checks.library import FAILED, PASSED, CheckResult
from .declared_commands import UNKNOWN, full_suite_run, run_outcome

CHECK_TYPE = "system_tests"
CHANGING = ("change", "deliver")
MAX_EXCERPT = 20_000
def rule_text(command: str) -> str:
    """The system test rule of a building phase (catalog ``run.system_tests.rule``) with ``command``'s full-run
    options (stack data ``test_runner.full_run_hint``)."""
    from ...engineering_knowledge.stacks import full_run_hint
    from ..run_texts import run_text

    return run_text("system_tests.rule", full_run_hint=full_run_hint(command))


def pipeline_rule_text(plain: bool) -> str:
    """The rule when the pipeline runs the system test (``agent_system_test: "pipeline"``): write tests, never run."""
    from ..run_texts import run_text

    return run_text("system_tests.plain_pipeline_rule" if plain else "system_tests.pipeline_rule")


def plain_rule_text() -> str:
    """The rule of a plain Claude Code session (catalog ``run.system_tests.plain_rule``)."""
    from ..run_texts import run_text

    return run_text("system_tests.plain_rule")


# The rule of a plain Claude Code session (epic-delivery, ``config.brief: "plain"``), at plain Claude Code's level
# Without this, the full rule's system test with a full-page
# screenshot per acceptance criterion and state, each Read back, made the session Read PNGs of 58-430K characters and
# cost ~+70 % output tokens against a plain control; the brief's one-sentence browser look stays.

_COUNT = re.compile(r"(\d+) (passed|skipped|xfailed|failed|errors?)")


_NODE_COUNT = re.compile(r"^ℹ (?P<kind>pass|fail|skipped|cancelled) (?P<number>\d+)$", re.MULTILINE)
_NODE_KINDS = {"pass": "passed", "fail": "failed", "skipped": "skipped", "cancelled": "error"}


def summary_counts(text: str) -> dict[str, int]:
    """The counts of pytest's last summary line in ``text`` (``passed``, ``skipped``, ...), or of node's spec summary
    ("ℹ pass 7", "ℹ fail 0"; otherwise a piped green `node --test` read as no summary)."""
    node = {_NODE_KINDS[kind]: int(number) for kind, number in _NODE_COUNT.findall(str(text or ""))}
    if node:
        return {kind: number for kind, number in node.items() if number or kind == "passed"}
    lines = [line for line in str(text or "").splitlines() if " in " in line and _COUNT.search(line)]
    found: dict[str, int] = {}
    for number, kind in _COUNT.findall(lines[-1] if lines else ""):
        found[kind.rstrip("s") if kind.startswith("error") else kind] = int(number)
    return found


async def declared_system_test_commands(db: Any, workspace_id: str | None) -> list[str]:
    """The declared system test commands of the Workspace's active repositories."""
    if not workspace_id:
        return []
    from sqlalchemy import select

    from ....models import CodeRepository
    from ..workspace.spec import declared_environment

    rows = (await db.execute(select(CodeRepository).where(
        CodeRepository.project_id == workspace_id, CodeRepository.is_active.is_(True)))).scalars().all()
    found: list[str] = []
    for row in rows:
        setup = dict(row.config_json or {}).get("coding_setup")
        environment = declared_environment(dict(setup)) if isinstance(setup, dict) else None
        command = str((environment or {}).get("system_test") or "").strip()
        if command and command not in found:
            found.append(command)
    return found


TEST_ROLE = "test"


def phase_system_tests(capability_class: str, environment: Any, *, write: list[str] | None = None,
                       role: str = "", plain: bool = False, protects_tests: bool = False,
                       by_pipeline: bool = False) -> dict[str, Any] | None:
    """The system tests of this phase: the declared command and the rule, for a changing phase that may write the
    system test folder (no write rules, a write rule that covers the folder, or a teamwork ``test`` item).

    Without this, the rule ("add or extend a test in the system test folder") went to
    backend and frontend items whose paths exclude ``tests/system/**`` and to the coordinator item, which may write only
    ``docs/stories/**``; a small model followed it into path-rule refusals."""
    if capability_class not in CHANGING or not isinstance(environment, dict) or protects_tests or \
            tests_only(write, system_folder(str(environment.get("system_test") or ""))):
        # A phase that may not write tests (a bug's fix, ``protect_confirmed_tests``) is never asked to add one
        # (otherwise the stop check demanded a new system test the phase's path rules refused).
        return None
    command = str(environment.get("system_test") or "").strip()
    if not command or not writes_system_tests(command, write, role):
        return None
    if by_pipeline:  # the pipeline runs it on every pass; the Stop asks nothing of the agent
        return {"command": command, "rule": pipeline_rule_text(plain), "by_pipeline": True,
                **({"app_folder": str(environment["app_folder"])} if environment.get("app_folder") else {})}
    return {"command": command, "rule": plain_rule_text() if plain else rule_text(command),
            **({"app_folder": str(environment["app_folder"])} if environment.get("app_folder") else {})}


_TEST_PATTERN = ("test", "spec")


def tests_only(write: list[str] | None, folder: str = "") -> bool:
    """A phase that may write only tests (a bug's reproduce: ``tests/**``, ``**/*_test.*``): it shows a failure on the
    unchanged app, so no green system test run is asked of it (otherwise reproduce paused on "the last
    run of the system tests failed" while the bug it reproduces was present)."""
    # A phase whose rules name the system test folder itself writes system tests (a teamwork ``test`` item).
    names_folder = bool(folder) and any(str(pattern).startswith(folder) for pattern in write or [])
    return bool(write) and not names_folder and all(any(word in str(pattern).lower() for word in _TEST_PATTERN)
                                                    for pattern in write)


def writes_system_tests(command: str, write: list[str] | None, role: str = "") -> bool:
    """Whether a phase with these write rules (``None`` / ``[]``: no rules) may write the command's test folder."""
    from ..teamwork.plan import overlaps

    if role == TEST_ROLE or not write:
        return True
    folder = system_folder(command)
    return not folder or any(overlaps(pattern, f"{folder}/**") for pattern in write)


def system_command(contract: dict[str, Any]) -> tuple[str, ...]:
    system = dict(dict(contract.get("phase") or {}).get("system_tests") or {})
    command = str(system.get("command") or "").strip()
    return (command,) if command else ()


def _command(row: ToolCall) -> str:
    parameters = row.parameters if isinstance(row.parameters, dict) else {}
    data = parameters.get("input") if isinstance(parameters.get("input"), dict) else parameters
    return str(data.get("command") or "")


def _green(row: ToolCall) -> bool:
    result = row.result if isinstance(row.result, dict) else None
    return row.status == "success" and result is not None and result.get("is_error") is False


def _text(row: ToolCall) -> str:
    result = row.result if isinstance(row.result, dict) else {}
    return str(result.get("excerpt") or result.get("stdout") or "")


def _excerpt(row: ToolCall) -> str:
    return " ".join(_text(row).split())[-MAX_EXCERPT:]


_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.MULTILINE)


def changed_files(change: Any) -> list[str] | None:
    """The files of the launcher's reported change (``facts.change.patch``); ``None`` when it cannot be judged."""
    if not isinstance(change, dict) or change.get("base_unavailable") or change.get("truncated"):
        return None
    patch = change.get("patch")
    if not isinstance(patch, str):
        return None
    return sorted({match.group(2) for match in _DIFF_FILE.finditer(patch)})


DOC_SUFFIXES = (".md", ".txt", ".rst", ".adoc")


def docs_only(change: Any) -> bool:
    """The change touches documentation only (e.g. a spec draft that changed only
    benchmark/SPEC.md, may not run tests, and the test gates held it until it paused)."""
    files = changed_files(change)
    return bool(files) and all(name.lower().endswith(DOC_SUFFIXES) for name in files)


def system_folder(command: str) -> str:
    """The test folder the system test command runs (its last path-like argument), e.g. ``tests/system``; a script
    (``system_test/run_system_test.py``) names its folder."""
    paths = [word for word in command.split() if "/" in word and not word.startswith(("-", ".venv", "/"))]
    if not paths:
        return ""
    last = paths[-1].rstrip("/")
    return posixpath.dirname(last) if posixpath.splitext(last)[1] else last


def _app_relative(name: str, app_folder: str) -> str:
    prefix = app_folder.strip("/") + "/" if app_folder.strip("/") else ""
    return name[len(prefix):] if prefix and name.startswith(prefix) else name


def uncovered_change(command: str, change: Any, app_folder: str = "") -> str:
    """Why the change has no system test ("" when it has one or cannot be judged). Example: a model built
    the checklist API, ran only the two existing system tests and the phase passed."""
    files = changed_files(change)
    folder = system_folder(command)
    if not files or not folder:
        return ""
    # The command runs in the app folder (an app in a subfolder: coffee/flutter/claude), the diff names repo paths.
    files = [_app_relative(name, app_folder) for name in files]
    product = [name for name in files if not name.startswith(("tests/", "test/", folder + "/"))
               and not name.endswith((".md", ".txt"))]
    if not product or any(name.startswith(folder + "/") for name in files):
        return ""
    shown = ", ".join(product[:4]) + (" ..." if len(product) > 4 else "")
    return (f"the change touches {shown} but adds or changes no system test in {folder}/: test each new criterion "
            "a user or client can observe on the running app there")


_DEF_TEST = re.compile(r"^\+(\s*)def (test_\w+)\(")
_CHECKS = re.compile(r"\bassert\b|\bexpect\(|pytest\.raises|\.to_(be|have)_")
_NO_OP = re.compile(r"^\s*(pass|\.\.\.|#.*|\"\"\".*\"\"\"|\'\'\'.*\'\'\'|)\s*$")


def empty_tests(command: str, change: Any) -> list[str]:
    """System tests the change adds whose body does nothing (``pass``, ``...``, comments, a docstring).
    Example: a placeholder ``test_..._fails_with_invalid_corpus`` with only ``pass``."""
    folder = system_folder(command)
    if not folder or not isinstance(change, dict) or not isinstance(change.get("patch"), str):
        return []
    found: list[str] = []
    current_file = ""
    name, indent, body = "", 0, []

    def close() -> None:
        # benchmark T5: a system test that only took a screenshot and checked nothing.
        if name and (all(_NO_OP.match(line) for line in body) or not any(_CHECKS.search(line) for line in body)):
            found.append(f"{current_file}::{name}")

    for raw in change["patch"].splitlines():
        header = _DIFF_FILE.match(raw)
        if header:
            close()
            current_file, name, body = header.group(2), "", []
            continue
        if not current_file.startswith(folder + "/"):
            continue
        test = _DEF_TEST.match(raw)
        if test:
            close()
            name, indent, body = test.group(2), len(test.group(1)), []
            continue
        if not name or not raw.startswith("+"):
            continue
        line = raw[1:]
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            close()
            name, body = "", []
            continue
        body.append(line)
    close()
    return found


def system_tests_result(system: Any, rows: Sequence[ToolCall], since: datetime | None, *,
                        change: Any = None) -> CheckResult | None:
    """A failed blocking check unless the pass's last system test run is green and the change has system tests;
    ``None`` without system tests."""
    command = str(dict(system or {}).get("command") or "").strip() if isinstance(system, dict) else ""
    if not command or docs_only(change):
        return None
    folder = str(dict(system or {}).get("app_folder") or "")
    uncovered = uncovered_change(command, change, folder)
    empty = empty_tests(command, change)
    if empty and not uncovered:
        uncovered = ("these system tests check nothing (no assert or expect, or only pass): " + ", ".join(empty[:5])
                     + "; write the real test or remove it")
    if uncovered:
        return CheckResult(type=CHECK_TYPE, outcome=FAILED, blocking=True,
                           description="System tests (the app running): " + uncovered, detail="")
    runs = [row for row in sorted(rows, key=lambda item: item.created_at or datetime.min)
            if row.tool_name == "Bash" and (since is None or (row.created_at is not None and row.created_at >= since))
            and full_suite_run(_command(row), command, folder)]
    outcome = run_outcome(_command(runs[-1]), command, succeeded=_green(runs[-1]), output=_text(runs[-1]),
                          app_folder=folder) if runs else ""
    if outcome == UNKNOWN:
        # Fail open: a pipe hid the exit code and no summary was readable.
        return CheckResult(type=CHECK_TYPE, outcome=PASSED, blocking=True, description="", detail="",
                           uncertain=f"`{command}` ran, but its piped output showed no summary")
    if not runs:
        why = f"never run in this pass: run `{command}` (it starts the app and tests it like a user)"
    elif outcome == "green":
        counts = summary_counts(_text(runs[-1]))
        if counts.get("passed") and not counts.get("skipped") and not counts.get("xfailed"):
            return None
        if not counts:
            return None  # no summary line in the recorded excerpt: the exit code decides
        why = (f"the last run of `{command}` passed {counts.get('passed', 0)} and skipped "
               f"{counts.get('skipped', 0) + counts.get('xfailed', 0)}: system tests never skip; make the app and "
               "the browser start, or say why they cannot")
    else:
        tail = _excerpt(runs[-1])
        why = f"the last run of `{command}` failed" + (f": {tail}" if tail else "")
    return CheckResult(type=CHECK_TYPE, outcome=FAILED, blocking=True,
                       description="System tests (the app running): " + why, detail="")


__all__ = ["CHECK_TYPE", "tests_only", "DOC_SUFFIXES", "TEST_ROLE", "plain_rule_text", "rule_text",
           "writes_system_tests",
           "changed_files", "docs_only", "declared_system_test_commands", "empty_tests", "uncovered_change",
           "phase_system_tests", "summary_counts",
           "system_command", "system_tests_result"]
