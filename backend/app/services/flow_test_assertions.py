from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def evaluate_flow_test_output(
    *,
    run_status: str | None,
    output: Mapping[str, Any],
    expected_output: Mapping[str, Any] | None,
    assertions: list[Any] | None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    if run_status != "completed":
        return _summary(
            status="failed",
            results=[
                {
                    "path": "$",
                    "operator": "run_completed",
                    "passed": False,
                    "message": f"Flow run ended with status {run_status or 'unknown'}.",
                }
            ],
            warnings=warnings,
        )

    expected = dict(expected_output or {})
    if expected:
        results.append(
            {
                "path": "$",
                "operator": "matches_expected_output",
                "expected": expected,
                "actual": dict(output),
                "passed": _contains_expected(dict(output), expected),
                "message": "Output includes expected fields.",
            }
        )

    for assertion in assertions or []:
        if isinstance(assertion, dict):
            results.append(_evaluate_assertion(output, assertion))

    if not results:
        warnings.append("no_assertions_configured")
        return _summary(status="passed", results=results, warnings=warnings)

    status = "passed" if all(result.get("passed") for result in results) else "failed"
    return _summary(status=status, results=results, warnings=warnings)


def _summary(*, status: str, results: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    passed_count = sum(1 for result in results if result.get("passed") is True)
    failed_count = sum(1 for result in results if result.get("passed") is False)
    return {
        "status": status,
        "passed": status == "passed",
        "total": len(results),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "warnings": warnings,
        "results": results,
    }


def _evaluate_assertion(output: Mapping[str, Any], assertion: Mapping[str, Any]) -> dict[str, Any]:
    path = str(assertion.get("path") or "$").strip() or "$"
    operator = str(assertion.get("operator") or "equals").strip() or "equals"
    actual = _resolve_path(output, path)
    expected = assertion.get("expected")
    if operator == "exists":
        passed = actual is not _MISSING
    elif operator == "not_empty":
        passed = actual not in (_MISSING, None, "", [], {})
    elif operator == "contains":
        passed = isinstance(actual, str) and str(expected) in actual
    elif operator == "not_equals":
        passed = actual is _MISSING or actual != expected
    else:
        operator = "equals"
        passed = actual is not _MISSING and actual == expected
    return {
        "path": path,
        "operator": operator,
        "expected": expected,
        "actual": None if actual is _MISSING else actual,
        "passed": passed,
        "message": "Assertion passed." if passed else "Assertion failed.",
    }


def _resolve_path(value: Mapping[str, Any], path: str) -> Any:
    if path in ("$", ""):
        return dict(value)
    current: Any = value
    for part in path.removeprefix("$.").split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


def _contains_expected(actual: Any, expected: Any) -> bool:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return False
        return all(
            key in actual and _contains_expected(actual[key], expected_value)
            for key, expected_value in expected.items()
        )
    if isinstance(expected, list):
        return actual == expected
    return actual == expected


class _Missing:
    pass


_MISSING = _Missing()


__all__ = ["evaluate_flow_test_output"]
