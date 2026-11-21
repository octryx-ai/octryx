from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET


def parse_pytest_summary(text: str) -> dict[str, int | None]:
    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    patterns = {
        "passed": r"(\d+)\s+passed",
        "failed": r"(\d+)\s+failed",
        "errors": r"(\d+)\s+error[s]?",
        "skipped": r"(\d+)\s+skipped",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            summary[key] = int(match.group(1))
    return summary


def parse_pytest_failed_tests(text: str) -> list[str]:
    failed = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("FAILED "):
            failed.append(stripped.removeprefix("FAILED ").split(" - ", 1)[0].strip())
    return failed


def parse_go_failed_tests(text: str) -> list[str]:
    return [match.group(1) for match in re.finditer(r"^--- FAIL: (\S+)", text, re.MULTILINE)]


def parse_maven_test_summary(text: str) -> dict[str, int]:
    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    matches = re.findall(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)", text)
    for tests_run, failures, errors, skipped in matches:
        total = int(tests_run)
        failed = int(failures)
        error_count = int(errors)
        skipped_count = int(skipped)
        summary["failed"] += failed
        summary["errors"] += error_count
        summary["skipped"] += skipped_count
        summary["passed"] += max(0, total - failed - error_count - skipped_count)
    return summary


def parse_surefire_reports(repo_root: Path) -> dict[str, int]:
    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    reports_dir = repo_root / "target" / "surefire-reports"
    if not reports_dir.exists():
        return summary
    for report in reports_dir.glob("TEST-*.xml"):
        try:
            root = ET.fromstring(report.read_text(encoding="utf-8"))
        except (OSError, ET.ParseError):
            continue
        tests = int(root.attrib.get("tests", "0") or 0)
        failures = int(root.attrib.get("failures", "0") or 0)
        errors = int(root.attrib.get("errors", "0") or 0)
        skipped = int(root.attrib.get("skipped", "0") or 0)
        summary["failed"] += failures
        summary["errors"] += errors
        summary["skipped"] += skipped
        summary["passed"] += max(0, tests - failures - errors - skipped)
    return summary
