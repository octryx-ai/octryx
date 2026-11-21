"""The advisory IDs the backend dependency audit may ignore, with the evidence that makes each one an exception.

The backend dependency audit (`scripts/dependency_audit.sh`, `pip-audit` over the locked export) fails on any
finding. An advisory with no fixed release cannot be remediated by a version choice, so the only ways to
keep the gate meaningful are to remove the distribution from the closure or to ignore that one advisory ID
explicitly. `pip-audit --ignore-vuln <id>` does the latter, and it is the dangerous option: a bare flag in a script
is indistinguishable from a finding nobody looked at, and it stays green long after the reason for it is gone.

This registry is the other half of that flag. Every ID the script ignores has an entry here naming the affected
distribution, why no release fixes it, why the vulnerable code path is not reached by this product, what would
invalidate that, and the decision itself in words. The key is the advisory ID (CVE, GHSA or PYSEC), never an internal
reference. `backend/tests/test_dependency_audit_exceptions.py` enforces both directions: an
unrecorded ignore fails, and a recorded exception the script no longer uses fails as stale.

Offline: it reads the script as text and imports nothing. A reachability claim is an argument about the *current*
source, never a property of the distribution, so every entry states what would invalidate it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .manifest import BACKEND_ROOT

AUDIT_SCRIPT = BACKEND_ROOT.parent / "scripts" / "dependency_audit.sh"

# `pip-audit --ignore-vuln <id>`, the only mechanism that suppresses a finding. Matching the flag rather than parsing
# the shell keeps the check honest about the literal command the audit runs, including inside a shell continuation.
_IGNORE_FLAG = re.compile(r"--ignore-vuln[\s=]+([A-Za-z0-9-]+)")

# An exception is keyed by a public advisory ID, so anyone can look the finding up.
ADVISORY_ID = re.compile(r"^(CVE-\d{4}-\d{4,}|GHSA(-[23456789cfghjmpqrvwx]{4}){3}|PYSEC-\d{4}-\d+)$")


@dataclass(frozen=True, slots=True)
class AuditException:
    """One advisory the audit ignores, and the recorded evidence for doing so."""

    distribution: str
    aliases: tuple[str, ...]
    no_fix: str
    reachability: str
    invalidated_by: str
    decision: str


# Empty: no advisory is ignored. The last one went with the only distribution that brought it into the closure.
AUDIT_EXCEPTIONS: dict[str, AuditException] = {}


def script_ignored_advisories(path: Path = AUDIT_SCRIPT) -> set[str]:
    """Return every advisory ID the audit script passes to ``pip-audit --ignore-vuln``."""
    return set(_IGNORE_FLAG.findall(path.read_text(encoding="utf-8")))
