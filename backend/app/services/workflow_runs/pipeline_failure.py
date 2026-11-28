"""The last red pipeline for the building agent's next pass: failed commands and tests, tasks without proof."""

from __future__ import annotations

from typing import Any

from ...models import WorkflowRun
from .pipeline import STATE_RED, state
from .pipeline_results import _green


def failure_for_agent(run: WorkflowRun) -> dict[str, Any] | None:
    current = state(run)
    if current.get("state") != STATE_RED:
        return None
    problem = file_problem(current)
    if problem is not None:
        return problem
    failed = [item for item in current.get("results") or [] if not _green(item) and not item.get("skipped")]
    red = {"note": "The CI pipeline ran the repository's declared commands on your change and they are not green, "
                   "or a task's proof test did not pass. Fix the cause; the pipeline runs again after this pass.",
           "failed": [{"command": item.get("command"), "exit_code": item.get("exit_code"),
                       "failed_tests": item.get("failed_tests") or [], "output_end": item.get("output_tail")}
                      for item in failed]}
    if waiting := [item for item in current.get("results") or [] if item.get("skipped")]:
        # Fail fast: the system test did not start this pass (an earlier check or the code style
        # was red); it runs once the checks above pass.
        red["not_run"] = [{"command": item.get("command"),
                           "reason": f"{item['skipped']}; it runs once the checks above and the code style are green"}
                          for item in waiting]
    if current.get("red_on_base_errors"):
        red["red_on_base"] = list(current["red_on_base_errors"])[:20]
    if current.get("code_style_errors"):
        # The agent's contract must name what is red, also when only the code style is.
        red["code_style_errors"] = list(current["code_style_errors"])[:40]
        red["code_style_rule"] = ("The installation's code style is part of the pipeline: fix every finding listed "
                                  "here exactly as named (file, line, rule) before anything else.")
    again = [test for item in failed for test in item.get("flaky_again") or []]
    if again:
        red["flaky_again"] = again
        red["flaky_rule"] = ("These tests failed and then passed on a re-run with no change in between, and not for "
                             "the first time in this run: they are flaky. Make each one deterministic (no fixed "
                             "ports, sleeps, shared state or order between tests); do not skip or weaken it.")
    if current.get("unproven"):
        red["missing_proof_tests"] = list(current["unproven"])
        red["missing_proof_rule"] = ("Each task is proven by its named proof test passing in the pipeline: write or "
                                     "fix the test under exactly the named file and function, inside the declared "
                                     "test command's selection, and make it pass.")
    return red


def file_problem(current: dict[str, Any]) -> dict[str, Any] | None:
    from .workspace.spec import ENVIRONMENT_FILE_FORMAT

    audit = dict(current.get("audit") or {})
    pointer = dict(current.get("environment_file") or {})
    if not pointer or audit.get("file_state") in (None, "ok"):
        return None
    file, folder, what = pointer.get("file"), pointer.get("app_folder"), audit.get("file_state")
    note = {
        "missing": f"The pipeline found no {file} in your change. Create it: declare this story's test commands in "
                   f"{file}; the pipeline runs exactly those in {folder}/.",
        "setup_failed": f"The setup commands of {file} failed in {folder}/. Fix the setup (or the file) so it "
                        "succeeds; the pipeline runs it before the tests.",
    }.get(str(what), f"{file} is not a valid environment file; the pipeline ran nothing. Fix it.")
    return {"note": note, "environment_file": {"file": file, "app_folder": folder, "state": what,
                                               "errors": list(audit.get("file_errors") or []),
                                               **({"setup": audit["setup"]} if audit.get("setup") else {}),
                                               "format": ENVIRONMENT_FILE_FORMAT},
            "failed": []}
