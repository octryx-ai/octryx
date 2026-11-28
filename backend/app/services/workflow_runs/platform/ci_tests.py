"""CI's per-test results keyed by the canonical test id."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ...workflow_checks.test_ids import Resolver
from ...workflow_checks.test_output import ERROR, FAILED, PASSED, SKIPPED, ParsedTests, parse_junit
from .dispatch import dispatch_tool

_STATUSES = {"success": PASSED, "passed": PASSED, "successful": PASSED, "fixed": PASSED, "failed": FAILED,
             "failure": FAILED, "regression": FAILED, "error": ERROR, "skipped": SKIPPED, "disabled": SKIPPED}


def from_cases(cases: Iterable[dict[str, Any]]) -> ParsedTests:
    parsed = ParsedTests(format="ci")
    resolver = Resolver()  # ids that need the repository's files resolve when the run records the result
    for case in cases:
        status = _STATUSES.get(str(case.get("status") or "").strip().lower())
        if status is None:
            continue
        parsed.add_reported(resolver, classname=str(case.get("classname") or ""), name=str(case.get("name") or ""),
                            file=str(case.get("file") or ""), outcome=status,
                            message=str(case.get("message") or ""))
    return parsed


def from_junit(reports: Iterable[dict[str, Any]]) -> ParsedTests:
    merged = ParsedTests(format="junit")
    for report in reports:
        parsed = parse_junit(str(report.get("junit_xml") or ""))
        merged.results.update(parsed.results)
        merged.unresolved += parsed.unresolved
        merged.problems += [f"{report.get('path') or 'report'}: {problem}" for problem in parsed.problems]
    return merged


def jenkins_report(report: dict[str, Any]) -> ParsedTests:
    return from_cases({"classname": case.get("className"), "name": case.get("name"), "status": case.get("status"),
                       "message": case.get("errorDetails")}
                      for suite in report.get("suites") or [] for case in (suite or {}).get("cases") or [])


async def github_tests(db: AsyncSession, run: WorkflowRun, ref: Any, runs: list[dict[str, Any]]) -> ParsedTests | None:
    reports: list[dict[str, Any]] = []
    for item in runs:
        outcome = await dispatch_tool(db, run, "get_test_results",
                                      {"provider": "github", **ref.args(), "run_id": str(item.get("id") or ""),
                                       "include_cases": True}, capability_class="read_only")
        if outcome.ok:
            reports += list(outcome.result.get("junit_reports") or [])
    return from_junit(reports) if reports else None


async def gitlab_tests(db: AsyncSession, run: WorkflowRun, ref: Any, pipeline_id: str) -> ParsedTests | None:
    outcome = await dispatch_tool(db, run, "get_test_results",
                                  {"provider": "gitlab", **ref.args(), "pipeline_id": pipeline_id,
                                   "include_cases": True}, capability_class="read_only")
    cases = list(outcome.result.get("cases") or []) if outcome.ok else []
    return from_cases(cases) if cases else None


def bitbucket_tests(statuses: list[dict[str, Any]]) -> ParsedTests | None:
    cases = [case for status in statuses for case in status.get("test_cases") or []]
    return from_cases(cases) if cases else None


__all__ = ["bitbucket_tests", "from_cases", "from_junit", "github_tests", "gitlab_tests", "jenkins_report"]
