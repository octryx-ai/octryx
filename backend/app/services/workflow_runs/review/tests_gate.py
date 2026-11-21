"""A review of a phase that may not change tests never blocks on a test request.

The bug flow's fix phase protects the confirmed tests (``path_rules.protect_confirmed_tests``): it changes no test and
adds none (a new test module could patch what the confirmed tests import). The review after it asked twice for "a
unit test for GrinderScale.initial" (medium, blocking), the phase's Write was refused ("is a test file: phase 'Minimal
fix' … changes no test"), the WIP stayed unchanged and the review ended at its loop limit: no legal move. Such a
finding stays visible but low (not blocking), marked for a follow-up; the reviewer is told the phase's limit.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from ..protected_paths import fold, is_test_path

TESTS_PROTECTED_RULE = (
    "The phase under review may not add or change any test (it makes the code pass the confirmed tests). Do not ask "
    "it for a new or changed test: name a missing test as a low finding for a follow-up, never as medium or high.")
FOLLOW_UP_MARK = "(Follow-up, not blocking: this phase may not change tests.) "
_ASKS_FOR_TEST = re.compile(r"\b(add|write|extend|create|update|change|cover)\b[^.]{0,80}\btests?\b", re.IGNORECASE)


def asks_for_test(finding: Any) -> bool:
    return is_test_path(fold(str(getattr(finding, "file", "") or ""))) or bool(
        _ASKS_FOR_TEST.search(str(getattr(finding, "fix", "") or "")))


def tests_gate(settled: Any) -> Any:
    """The settled verdict with every test request low and marked; ``pass`` when nothing blocking is left."""
    from .verdict import BLOCKING_SEVERITIES, VERDICT_CHANGES, VERDICT_PASS

    if settled is None:
        return settled
    verdict = settled.verdict
    changed = False
    findings = []
    for finding in verdict.findings:
        if finding.severity in BLOCKING_SEVERITIES and asks_for_test(finding):
            finding = dataclasses.replace(finding, severity="low", fix=FOLLOW_UP_MARK + finding.fix)
            changed = True
        findings.append(finding)
    if not changed:
        return settled
    blocking = any(item.severity in BLOCKING_SEVERITIES for item in findings)
    state = VERDICT_PASS if verdict.verdict == VERDICT_CHANGES and not blocking else verdict.verdict
    return dataclasses.replace(settled, verdict=dataclasses.replace(verdict, findings=tuple(findings), verdict=state))


__all__ = ["TESTS_PROTECTED_RULE", "asks_for_test", "tests_gate"]
