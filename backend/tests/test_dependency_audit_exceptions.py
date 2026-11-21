"""Every advisory the backend dependency audit ignores must be a recorded, reasoned exception.

The audit is a gate only as long as "green" means "no finding". An advisory with no fixed release cannot be
remediated, so `scripts/dependency_audit.sh` suppresses it with `pip-audit --ignore-vuln <id>`. That flag on
its own is indistinguishable from a finding nobody triaged, and it survives the reason for it silently.

These tests bind the flag to `dependency_gates.audit_exceptions`: the script may not ignore an advisory the registry
does not record, the registry may not carry an exception the script no longer uses, and every record has to name the
distribution, why no release fixes it, why the vulnerable path is unreachable here, what would invalidate that, and
the decision in words; its key is a public advisory ID.

Offline, without the application fixtures:

    backend/.venv/bin/python -m pytest backend/tests/test_dependency_audit_exceptions.py -q --noconftest
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dependency_gates.audit_exceptions import (
    ADVISORY_ID,
    AUDIT_EXCEPTIONS,
    AUDIT_SCRIPT,
    AuditException,
    script_ignored_advisories,
)

RECORDED = sorted(AUDIT_EXCEPTIONS.items())


def test_the_script_ignores_only_recorded_advisories():
    unrecorded = sorted(script_ignored_advisories() - set(AUDIT_EXCEPTIONS))
    assert not unrecorded, (
        "dependency_audit.sh passes --ignore-vuln for advisories with no entry in "
        f"dependency_gates.audit_exceptions.AUDIT_EXCEPTIONS: {unrecorded}. An audit that reports 'no known "
        "vulnerabilities' while silently ignoring one is worse than a red gate."
    )


def test_every_recorded_exception_is_still_used_by_the_script():
    """A stale exception weakens the next matching advisory instead of failing the gate."""
    stale = sorted(set(AUDIT_EXCEPTIONS) - script_ignored_advisories())
    assert not stale, f"recorded audit exceptions the script no longer passes to pip-audit: {stale}"


def test_the_script_actually_carries_the_audit_command():
    """Anti-vacuity: if the flag or the file moved, both directions above would pass on an empty set."""
    assert AUDIT_SCRIPT.is_file(), AUDIT_SCRIPT
    text = AUDIT_SCRIPT.read_text(encoding="utf-8")
    assert "pip-audit" in text, "dependency_audit.sh no longer runs pip-audit; this gate is checking nothing"
    assert "--ignore-vuln" in text or not AUDIT_EXCEPTIONS, "records without any --ignore-vuln flag in the script"


@pytest.mark.parametrize(("advisory", "exception"), RECORDED)
def test_every_recorded_exception_is_keyed_by_a_public_advisory_id(advisory: str, exception: AuditException):
    assert ADVISORY_ID.match(advisory), f"{advisory!r} is not a CVE, GHSA or PYSEC id"
    assert all(ADVISORY_ID.match(alias) for alias in exception.aliases), f"{advisory} has a non-advisory alias"


@pytest.mark.parametrize("advisory", ["CVE-2024-12345", "GHSA-jfhm-5ghh-2f97", "PYSEC-2026-1325"])
def test_public_advisory_ids_are_accepted(advisory: str):
    assert ADVISORY_ID.match(advisory)


@pytest.mark.parametrize("advisory", ["#866", "issue-866", "GHSA-aaaa-bbbb-cccc", "CVE-24-1"])
def test_internal_references_and_malformed_ids_are_refused(advisory: str):
    assert not ADVISORY_ID.match(advisory)


@pytest.mark.parametrize(("advisory", "exception"), RECORDED)
def test_every_recorded_exception_carries_its_evidence(advisory: str, exception: AuditException):
    assert exception.distribution.strip(), f"{advisory} does not name the affected distribution"
    for field, minimum in (("no_fix", 120), ("reachability", 120), ("invalidated_by", 40), ("decision", 40)):
        value = getattr(exception, field)
        assert len(value.strip()) >= minimum, (
            f"{advisory}.{field} is {len(value.strip())} characters; an exception needs an argument, not a label"
        )


# --- negative controls -----------------------------------------------------------------------------------------


def _script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "dependency_audit.sh"
    path.write_text(body, encoding="utf-8")
    return path


def test_an_unrecorded_ignore_flag_is_detected(tmp_path: Path):
    path = _script(tmp_path, "pip-audit -r runtime.txt --ignore-vuln GHSA-aaaa-bbbb-cccc\n")
    assert script_ignored_advisories(path) - set(AUDIT_EXCEPTIONS) == {"GHSA-aaaa-bbbb-cccc"}


def test_a_script_without_ignore_flags_yields_no_advisories(tmp_path: Path):
    path = _script(tmp_path, "pip-audit -r runtime.txt\n")
    assert script_ignored_advisories(path) == set()


def test_ignore_flags_are_found_across_line_continuations_and_equals_form(tmp_path: Path):
    """The real command is a multi-line shell continuation; an id hidden by formatting must not slip the check."""
    path = _script(
        tmp_path,
        "pip-audit -r runtime.txt \\\n  --ignore-vuln PYSEC-1111-1 \\\n  --ignore-vuln=CVE-2222-3333\n",
    )
    assert script_ignored_advisories(path) == {"PYSEC-1111-1", "CVE-2222-3333"}
