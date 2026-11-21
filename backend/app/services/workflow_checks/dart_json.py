"""Per-test results of Dart's JSON reporter (``flutter test --reporter json``, ``dart test --reporter json``).

The expanded reporter's counters cannot be attributed when several test files run concurrently (``flutter test``'s
default), so such a run kept only its failures and paused ``evidence_unresolved``. The JSON
reporter names every test's suite (``suiteID`` → the suite's file) and its own result, so a concurrent run is
attributed exactly. Events, one JSON object per line: ``suite`` (id, path), ``testStart`` (test id, name, suiteID,
hidden loader tests named ``loading <file>``), ``error`` (testID, error), ``testDone`` (testID, result: success |
failure | error, skipped, hidden), ``done``.
"""

from __future__ import annotations

import json
from typing import Any

from .test_output import ERROR, FAILED, PASSED, SCOPE_COLLECTION, SKIPPED, ParsedTests, _dart_file

_RESULTS = {"success": PASSED, "failure": FAILED, "error": ERROR}


def is_dart_json(text: str) -> bool:
    return any(_event(line).get("type") in ("testStart", "suite") for line in str(text or "").splitlines()[:400])


def _event(line: str) -> dict[str, Any]:
    line = line.strip()
    if not line.startswith("{"):
        return {}
    try:
        value = json.loads(line)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def parse_dart_json(text: str) -> ParsedTests:
    parsed = ParsedTests(format="dart")
    suites: dict[int, str] = {}
    tests: dict[int, tuple[str, str, bool]] = {}  # id -> (file, name, hidden)
    errors: dict[int, list[str]] = {}
    finished = False
    for line in str(text or "").splitlines():
        event = _event(line)
        kind = event.get("type")
        if kind == "suite" and isinstance(event.get("suite"), dict):
            suite = event["suite"]
            if isinstance(suite.get("id"), int) and suite.get("path"):
                suites[suite["id"]] = _dart_file(str(suite["path"]))
        elif kind == "testStart" and isinstance(event.get("test"), dict):
            test = event["test"]
            file = suites.get(test.get("suiteID"), "")
            hidden = str(test.get("name") or "").startswith("loading ")  # the suite's loader, not a test
            if isinstance(test.get("id"), int):
                tests[test["id"]] = (file, str(test.get("name") or ""), hidden)
        elif kind == "error" and isinstance(event.get("testID"), int):
            errors.setdefault(event["testID"], []).append(" ".join(str(event.get("error") or "").split())[:400])
        elif kind == "testDone" and isinstance(event.get("testID"), int) and event["testID"] in tests:
            file, name, hidden = tests[event["testID"]]
            outcome = SKIPPED if event.get("skipped") else _RESULTS.get(str(event.get("result")), ERROR)
            message = " ".join(errors.get(event["testID"], []))
            if hidden or event.get("hidden"):
                if outcome != PASSED and file:  # the suite failed to load: an error of the whole file
                    parsed.add(file, ERROR, message, scope=SCOPE_COLLECTION)
                continue
            if file and name:
                parsed.add(f"{file}::{name}", outcome, message)
        elif kind == "done":
            finished = True
    if not finished:
        parsed.problems.append("the JSON reporter's output ended before its done event (the run was cut)")
    return parsed


__all__ = ["is_dart_json", "parse_dart_json"]
