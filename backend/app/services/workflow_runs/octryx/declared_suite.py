"""The repository's declared test commands must pass after the pass's last change.

Gemma ran only its two new test files after the last edit; they passed and the phase finished, while the declared
unit test command failed on an "import file mismatch" with two tests of the same name. A changing phase of a
repository with a declared test command finishes only when that command, run as a **full run** after the last file
change (an edit, ``rm`` or ``git restore`` of named files), is green.

An advisory check before a pipeline step let implement pass on single test files while only the pipeline ran the whole
suite, red, again and again. So it blocks in every phase that changes code (``stop``; a teamwork item, which builds one
part of a story, stays advisory), and a full run is any form with the declared selection
(``shell_rules.full_suite_run``: ``-q``, ``-x``, ``timeout``, ``| tail``), judged by its exit code or, piped, by
pytest's summary (``run_green``). Before a pipeline step the system test command counts too (``commands``); without one,
``system_tests`` judges it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from ....models import ToolCall
from ...agent_gateway.capability import FILE_MUTATION_TOOLS
from ...engineering_knowledge.stacks import full_run_hint
from ...workflow_checks.library import FAILED, PASSED, CheckResult
from ..run_texts import run_text
from .declared_commands import UNKNOWN, full_suite_run, run_outcome

CHECK_TYPE = "declared_tests"
CHANGING = ("change", "deliver")


def _command(row: ToolCall) -> str:
    parameters = row.parameters if isinstance(row.parameters, dict) else {}
    data = parameters.get("input") if isinstance(parameters.get("input"), dict) else parameters
    return str(data.get("command") or "")


def _green(row: ToolCall) -> bool:
    result = row.result if isinstance(row.result, dict) else None
    return row.status == "success" and result is not None and result.get("is_error") is False


def _changes(row: ToolCall) -> bool:
    from .removal_rules import removal_paths

    if row.tool_name in FILE_MUTATION_TOOLS:
        return row.status == "success"
    return row.tool_name == "Bash" and row.status == "success" and removal_paths(_command(row)) is not None


def _path(row: ToolCall) -> str:
    parameters = row.parameters if isinstance(row.parameters, dict) else {}
    data = parameters.get("input") if isinstance(parameters.get("input"), dict) else parameters
    return str(data.get("file_path") or data.get("notebook_path") or data.get("path") or "")


def _docs_only(changes: Sequence[ToolCall]) -> bool:
    """Every change of the pass is an edit of a documentation file (a spec draft): no test run is due."""
    from .system_tests import DOC_SUFFIXES

    return bool(changes) and all(row.tool_name in FILE_MUTATION_TOOLS and _path(row).lower().endswith(DOC_SUFFIXES)
                                 for row in changes)


def _text(row: ToolCall) -> str:
    result = row.result if isinstance(row.result, dict) else {}
    return str(result.get("excerpt") or result.get("stdout") or "")


def declared_suite_result(contract: dict[str, Any], rows: Sequence[ToolCall],
                          since: datetime | None, *, change: Any = None,
                          keys: tuple[str, ...] = ("test",)) -> CheckResult | None:
    """A failed blocking check unless each declared command (``keys`` of the environment) had a green full run after
    the pass's last change; a change of documentation only (``facts.change`` or the pass's edits) needs no test run."""
    from .system_tests import docs_only

    if docs_only(change):
        return None
    phase = dict(contract.get("phase") or {})
    from .system_tests import tests_only

    if tests_only(list(dict(phase.get("path_rules") or {}).get("write") or [])):
        # A phase that writes only tests shows a failure on purpose (a bug's reproduce): its suite is red by design
        # (otherwise reproduce pauses on "the full test suite must be green" with its confirmed
        # tests failing on the bug, once the environment file's `flutter test` is a declared command).
        return None
    environment = dict(dict(contract.get("preparation") or {}).get("environment") or {})
    commands = [str(environment.get(key) or "").strip() for key in keys if str(environment.get(key) or "").strip()]
    if str(phase.get("capability_class") or "") not in CHANGING or not commands:
        return None
    ordered = [row for row in sorted(rows, key=lambda item: item.created_at or datetime.min)
               if since is None or (row.created_at is not None and row.created_at >= since)]
    last_change = max((index for index, row in enumerate(ordered) if _changes(row)), default=None)
    if last_change is None:
        return None  # nothing changed in this pass
    if _docs_only([row for row in ordered if _changes(row)]):
        return None
    missing, unsure = [], []
    folder = str(environment.get("app_folder") or "")  # the declared commands' working directory
    for command in commands:
        runs = [row for row in ordered[last_change + 1:]
                if row.tool_name == "Bash" and full_suite_run(_command(row), command, folder)]
        outcome = run_outcome(_command(runs[-1]), command, succeeded=_green(runs[-1]), output=_text(runs[-1]),
                              app_folder=folder) if runs else ""
        if outcome == UNKNOWN:
            # Fail open: a pipe hid the exit code and no summary was readable.
            unsure.append(f"`{command}` ran in full after the last change, but its piped output showed no summary")
            continue
        if outcome == "green":
            continue
        missing.append(run_text("full_suite.failed" if runs else "full_suite.not_run", command=command))
    if not missing:
        return CheckResult(type=CHECK_TYPE, outcome=PASSED, blocking=True, description="", detail="",
                           uncertain="; ".join(unsure)) if unsure else None
    # The runner's own full-run options (stack data), never another runner's ("-q, -x are fine" would send a
    # Flutter agent to `flutter test -q`, which the shell policy refuses).
    hint = full_run_hint(commands[0])
    return CheckResult(type=CHECK_TYPE, outcome=FAILED, blocking=True,
                       description=run_text("full_suite.required", missing="; ".join(missing), full_run_hint=hint),
                       detail="")


__all__ = ["CHECK_TYPE", "declared_suite_result"]
