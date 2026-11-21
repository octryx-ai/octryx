"""Console reporting for the secret containment checks.

Output carries path, line, key name and reason code only. Never a value.
"""

from __future__ import annotations

import sys

from .contract import Finding

GUIDANCE = (
    "Local secret input belongs in an untracked *.local.yaml file; tracked deployment\n"
    "material may only carry explicit placeholders such as REPLACE_WITH_<NAME>.\n"
    "changeme-style and empty-with-weak-chart-default values are deployable and are\n"
    "therefore rejected. Treat any value that reached a commit as exposed and rotate it\n"
    "through the owning system."
)


def report(findings: list[Finding], clean_message: str, guidance: str = GUIDANCE) -> int:
    """Print findings without values and return the process exit code."""
    if not findings:
        print(clean_message)
        return 0
    print("Secret containment findings (values intentionally not shown):", file=sys.stderr)
    for finding in findings:
        print(f"  {finding.render()}", file=sys.stderr)
    print(f"\n{guidance}", file=sys.stderr)
    return 1
